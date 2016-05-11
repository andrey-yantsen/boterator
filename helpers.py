import logging
from time import time
from ujson import loads, dumps
from urllib.parse import urlencode

from tornado.gen import coroutine
from tornado.httpclient import AsyncHTTPClient
from tornado.ioloop import PeriodicCallback
from tornado.options import options

from globals import get_db


@coroutine
def report_botan(message, event_name):
    token = options.botan_token
    if not token:
        return

    uid = message['from']['id']

    params = {
        'token': token,
        'uid': uid,
        'name': event_name,
    }

    resp = yield AsyncHTTPClient().fetch('https://api.botan.io/track?' + urlencode(params), body=dumps(message),
                                         method='POST')

    return loads(resp.body.decode('utf-8'))


@coroutine
def is_allowed_user(user, bot_id):
    query = """
        INSERT INTO users (bot_id, user_id, first_name, last_name, username, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT ON CONSTRAINT users_pkey
        DO UPDATE SET first_name = EXCLUDED.first_name, last_name = COALESCE(EXCLUDED.last_name, users.last_name),
         username = COALESCE(EXCLUDED.username, users.username), updated_at = EXCLUDED.updated_at
    """

    yield get_db().execute(query, (bot_id, user['id'], user['first_name'], user.get('last_name'), user.get('username')))

    cur = yield get_db().execute('SELECT banned_at FROM users WHERE bot_id = %s AND user_id = %s', (bot_id, user['id']))
    row = cur.fetchone()
    if row and row[0]:
        return False

    return True


def append_pgettext(f):
    def wrapper(self, *args, **kwargs):
        return f(self, *args, pgettext=self.locale.pgettext, **kwargs)

    return wrapper


def append_npgettext(f):
    def wrapper(self, *args, **kwargs):
        return f(self, *args, npgettext=self.locale.pgettext, **kwargs)

    return wrapper


def append_stage_key(f):
    def wrapper(self, message=None, *args, user_id=None, chat_id=None, **kwargs):
        if message:
            user_id = message['from']['id']
            chat_id = message['chat']['id']
            stage_key = '%s-%s' % (chat_id, user_id)
        elif not kwargs.get('stage_key'):
            assert user_id and chat_id
            stage_key = '%s-%s' % (chat_id, user_id)
        else:
            stage_key = kwargs['stage_key']

        return f(self, message, *args, stage_key=stage_key, **kwargs)

    return wrapper


class StagesStorage:
    def __init__(self, ttl=7200):
        self.stages = {}
        self.ttl = ttl
        self.cleaner = PeriodicCallback(self.drop_expired, 600)
        self.cleaner.start()

    @append_stage_key
    def set(self, message, stage_id, stage_key=None, **kwargs):
        if stage_key not in self.stages:
            self.stages[stage_key] = {'meta': {}, 'code': 0}

        self.stages[stage_key]['code'] = stage_id
        self.stages[stage_key]['meta'].update(kwargs)
        self.stages[stage_key]['timestamp'] = time()

        if message is not None:
            self.stages[stage_key]['meta']['last_message'] = message

    @append_stage_key
    def get(self, message, stage_key=None):
        if stage_key in self.stages:
            return self.stages[stage_key]['code'], self.stages[stage_key]['meta'], self.stages[stage_key]['timestamp']

        return None, {}, 0

    def get_id(self, *args, **kwargs):
        return self.get(*args, **kwargs)[0]

    @append_stage_key
    def drop(self, message, stage_key=None):
        if stage_key in self.stages:
            del self.stages[stage_key]

    def drop_expired(self):
        drop_list = []
        for stage_key, stage_info in self.stages.items():
            if time() - stage_info['timestamp'] > self.ttl:
                drop_list.append(stage_key)

        for stage_key in drop_list:
            logging.info('Cancelling last action for #%s', stage_key)
            self.drop(stage_key)

        return len(drop_list)

    @staticmethod
    def __key(chat_id, user_id):
        return '%s-%s' % (chat_id, user_id)
