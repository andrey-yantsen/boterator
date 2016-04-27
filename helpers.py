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


class StagesStorage:
    def __init__(self, ttl=7200):
        self.stages = {}
        self.ttl = ttl
        self.cleaner = PeriodicCallback(self.drop_expired, 600)
        self.cleaner.start()

    def set(self, user_id, stage_id, do_not_validate=False, **kwargs):
        if user_id not in self.stages:
            self.stages[user_id] = {'meta': {}, 'code': 0}

        assert do_not_validate or self.stages[user_id]['code'] == 0 or stage_id == self.stages[user_id]['code'] + 1

        self.stages[user_id]['code'] = stage_id
        self.stages[user_id]['meta'].update(kwargs)
        self.stages[user_id]['timestamp'] = time()

    def get(self, user_id):
        if user_id in self.stages:
            return self.stages[user_id]['code'], self.stages[user_id]['meta'], self.stages[user_id]['timestamp']

        return None, {}, 0

    def get_id(self, user_id):
        return self.get(user_id)[0]

    def drop(self, user_id):
        if self.get_id(user_id) is not None:
            del self.stages[user_id]

    def drop_expired(self):
        drop_list = []
        for user_id, stage_info in self.stages.items():
            if time() - stage_info['timestamp'] > self.ttl:
                drop_list.append(user_id)

        for user_id in drop_list:
            logging.info('Cancelling last action for user#%d', user_id)
            del self.stages[user_id]

        return len(drop_list)
