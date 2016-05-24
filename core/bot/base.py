import logging
from copy import deepcopy
from functools import wraps

from datetime import timedelta
from tornado import locale
from tornado.gen import coroutine, maybe_future, Return
from tornado.locks import Event
from tornado.queues import Queue
from ujson import dumps

import telegram
from core.bot.command_filter import CommandFilterBase, CommandFilterAny, CommandFilterTextCmd
from core.bot.stages import Stages
from helpers.lazy_gettext import set_locale_recursive, pgettext
from .command import Command


class Base:
    SETTINGS_PER_BOT = 1
    SETTINGS_PER_USER = 2
    SETTINGS_TYPE = SETTINGS_PER_BOT

    def __init__(self, token, db, **kwargs):
        self.token = token
        self.settings = kwargs.pop('settings', {})

        for key, value in kwargs.items():
            self.__dict__[key] = value

        self.api = telegram.Api(token, self.process_update)
        self.db = db
        self.user_settings = {}
        self.commands = {}
        self.raw_commands_tree = {}
        self.cancellation_handler = None
        self.unknown_command_handler = None
        self.updates_queue = Queue(kwargs.get('updates_queue_handlers', 4) * 10)
        self._init_handlers()
        self._stages = Stages(self.bot_id, db)
        self._finished = Event()
        self._supported_languages = tuple([])

    def _init_handlers(self):
        raise NotImplementedError()

    def _add_handler(self, handler: callable, name: pgettext=None, previous_handler: callable=None, is_final=True):
        if handler not in self.commands:
            self.commands[handler] = Command(self, handler, name)

        if previous_handler and previous_handler not in self.commands:
            raise BotError('Previous command is unknown')

        previous_handler_name = previous_handler.__name__ if previous_handler else 'none'

        if previous_handler_name not in self.raw_commands_tree:
            self.raw_commands_tree[previous_handler_name] = []
        else:
            for h, _ in self.raw_commands_tree[previous_handler_name]:
                if h.handler == handler and handler != self.cancellation_handler:
                    raise BotError('Command already registered')
                elif h.handler == handler:
                    return

        self.raw_commands_tree[previous_handler_name].append((self.commands[handler], is_final))

        if not is_final and self.cancellation_handler:
            self._add_handler(self.cancellation_handler, previous_handler=handler, is_final=True)

    def _load_user_settings_per_user(self):
        return {}

    @coroutine
    def update_settings(self, user_id, **kwargs):
        if self.SETTINGS_TYPE == self.SETTINGS_PER_BOT:
            self.settings.update(kwargs)
            yield self.db.execute('UPDATE registered_bots SET settings = %s WHERE id = %s', (dumps(self.settings),
                                                                                             self.bot_id))
        else:
            if user_id not in self.user_settings:
                self.user_settings[user_id] = kwargs
            else:
                self.user_settings[user_id].update(kwargs)

            yield self.db.execute('UPDATE users SET settings = %s WHERE bot_id = %s AND user_id = %s',
                                  (dumps(self.user_settings[user_id]), self.bot_id, user_id))

    def get_settings(self, user_id):
        if self.SETTINGS_TYPE == self.SETTINGS_PER_BOT:
            return deepcopy(self.settings)
        else:
            return deepcopy(self.user_settings.get(user_id, {}))

    @coroutine
    def start(self):
        logging.debug('[bot#%s] Starting', self.bot_id)
        self._finished.clear()
        self.user_settings = yield maybe_future(self._load_user_settings_per_user())
        handlers_f = [self._update_processor() for _ in range(self.settings.get('updates_queue_handlers', 4))]
        yield self._stages.restore()
        try:
            yield self.api.wait_commands()
        finally:
            self._finished.set()
            yield handlers_f

    def stop(self):
        assert not self._finished.is_set()
        logging.debug('[bot#%s] Terminating', self.bot_id)
        self._finished.set()
        if self.api.is_alive():
            self.api.stop()

    @coroutine
    def process_update(self, update):
        yield self.updates_queue.put(update)

    @staticmethod
    def get_stage_key(update):
        if 'message' in update:
            chat_id = update['message']['chat']['id']
            user_id = update['message']['from']['id']
        elif 'callback_query' in update:
            if 'message' in update['callback_query']:
                chat_id = update['callback_query']['message']['chat']['id']
            else:
                chat_id = update['callback_query']['from']['id']
            user_id = update['callback_query']['from']['id']
        else:
            raise BotError('Unable to get stage_key for this type of update')

        return '%s-%s' % (user_id, chat_id)

    @coroutine
    def _update_processor(self):
        while not self._finished.is_set():
            try:
                received_update = yield self.updates_queue.get(timedelta(seconds=3))
            except:
                continue

            del received_update['update_id']

            try:
                stage_key = self.get_stage_key(received_update)
                current_stage = self._stages[stage_key]
                if current_stage:
                    stage_data = current_stage[1]
                    received_update.update(current_stage[1])
                    commands_tree = self.raw_commands_tree[current_stage[0]]
                else:
                    stage_data = {}
                    commands_tree = self.raw_commands_tree['none']

                processing_result = False
                for command_in_tree in commands_tree:
                    processing_result = yield command_in_tree[0](**received_update)
                    if processing_result is not False:
                        if not command_in_tree[1] and processing_result is not None:
                            if processing_result is True:
                                processing_result = {}
                            stage_data.update(processing_result)
                            self._stages[stage_key] = command_in_tree[0].handler, stage_data
                        elif processing_result is not None:
                            del self._stages[stage_key]
                        break

                    if processing_result is not False:
                        break

                if processing_result is False:
                    logging.debug('Handler not found: %s', dumps(received_update, indent=2))
                    if self.unknown_command_handler:
                        yield maybe_future(self.unknown_command_handler(self, **received_update))
            except:
                logging.exception('[bot#%s] Got error while processing message %s', self.bot_id,
                                  dumps(received_update, indent=2))

            self.updates_queue.task_done()

    def __getattr__(self, name):
        def outer_wrapper(f):
            @wraps(f)
            def wrapper(*args, **kwargs):
                l = locale.get('en_US')
                if self.SETTINGS_TYPE == self.SETTINGS_PER_BOT:
                    l = locale.get(self.settings.get('locale', 'en_US'))
                elif self.SETTINGS_TYPE == self.SETTINGS_PER_USER:
                    chat_id = None
                    if 'reply_to_message' in kwargs:
                        if 'chat' in kwargs['reply_to_message']:
                            chat_id = kwargs['reply_to_message']['chat']['id']
                        elif 'from' in kwargs['reply_to_message']:
                            chat_id = kwargs['reply_to_message']['from']['id']
                    elif 'chat_id' in kwargs:
                        chat_id = kwargs['chat_id']

                    if chat_id in self.user_settings:
                        l = locale.get(self.user_settings[chat_id].get('locale', 'en_US'))

                return f(*set_locale_recursive(args, l), **set_locale_recursive(kwargs, l))

            return wrapper

        if hasattr(self.api, name):
            attr = getattr(self.api, name)
            if isinstance(attr, type(self.stop)):
                return outer_wrapper(attr)
            else:
                return attr
        else:
            raise AttributeError("'%s' object has no attribute '%s'" % (self.__class__.__name__, name))


class BotError(Exception):
    pass


class AccessDeniedError(BotError):
    pass


class UserBannedError(BotError):
    pass
