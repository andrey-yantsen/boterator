import logging
from ujson import loads, dumps

from tornado.gen import coroutine

from tobot import Base
from tobot.stages import PersistentStages
from core.handlers.cancel import cancel_command
from core.handlers.boterator.reg import reg_command, plaintext_token, plaintext_channel_name, \
    plaintext_set_start_message, change_start_command, plaintext_set_hello, change_hello_command
from core.handlers.boterator.start import start_command
from core.handlers.emoji_end import emoji_end
from core.handlers.boterator.setlanguage import setlanguage, setlanguage_plaintext
from core.handlers.boterator.setlanguage_at_start import setlanguage_at_start, setlanguage_at_start_plaintext
from core.handlers.unknown_command import unknown_command
from core.handlers.validate_user import validate_user
from core.queues import boterator_queues, QUEUE_BOTERATOR_BOT_REVOKE
from tobot.helpers import pgettext
from tobot.telegram import Api


class Boterator(Base):
    SETTINGS_TYPE = Base.SETTINGS_PER_USER

    def __init__(self, token, db, queue, **kwargs):
        self.db = db
        super().__init__(token, stages_builder=lambda bot_id: PersistentStages(bot_id, db), **kwargs)
        self.queue = queue

    @coroutine
    def _load_user_settings_per_user(self):
        ret = {}
        cur = yield self.db.execute('SELECT user_id, settings FROM users WHERE bot_id = %s', (self.bot_id,))
        while True:
            row = cur.fetchone()
            if not row:
                break

            ret[row[0]] = row[1]
        return ret

    def _init_handlers(self):
        self.cancellation_handler = cancel_command
        self.unknown_command_handler = unknown_command
        self._add_handler(validate_user)
        self._add_handler(setlanguage, is_final=False)
        self._add_handler(emoji_end, None, setlanguage)
        self._add_handler(setlanguage_plaintext, None, setlanguage)
        self._add_handler(setlanguage_at_start, is_final=False)
        self._add_handler(setlanguage_at_start_plaintext, None, setlanguage_at_start)
        self._add_handler(start_command)
        self._add_handler(cancel_command)
        self._add_handler(reg_command, pgettext('Command name', '/reg - register a new bot'), is_final=False)
        self._add_handler(plaintext_token, pgettext('Action description', 'Waiting for the token'),
                          previous_handler=reg_command, is_final=False)

        self._add_handler(change_hello_command, None, previous_handler=plaintext_token, is_final=False)
        self._add_handler(plaintext_set_hello, None, previous_handler=change_hello_command, is_final=False)
        self._add_handler(change_hello_command, None, previous_handler=plaintext_set_hello, is_final=False)
        self._add_handler(change_start_command, None, previous_handler=plaintext_set_hello, is_final=False)
        self._add_handler(plaintext_channel_name, None, previous_handler=plaintext_set_hello, is_final=True)

        self._add_handler(change_start_command, None, previous_handler=plaintext_token, is_final=False)
        self._add_handler(plaintext_set_start_message, None, previous_handler=change_start_command, is_final=False)
        self._add_handler(change_start_command, None, previous_handler=plaintext_set_start_message, is_final=False)
        self._add_handler(change_hello_command, None, previous_handler=plaintext_set_start_message, is_final=False)
        self._add_handler(plaintext_channel_name, None, previous_handler=plaintext_set_start_message, is_final=True)

        self._add_handler(plaintext_channel_name, pgettext('Action description', 'Waiting for the channel name'),
                          previous_handler=plaintext_token, is_final=True)

    @coroutine
    def _update_settings_for_user(self, user_id, settings):
        yield self.db.execute('UPDATE users SET settings = %s WHERE bot_id = %s AND user_id = %s',
                              (dumps(self.user_settings[user_id]), self.bot_id, user_id))

    @coroutine
    def start(self):
        queue_listen_f = self.queue.listen(boterator_queues(), self.queue_handler)
        try:
            yield super().start()
        finally:
            self.queue.stop(boterator_queues())
            yield queue_listen_f

    @coroutine
    def queue_handler(self, queue_name, body):
        body = loads(body.decode('utf-8'))
        if queue_name == QUEUE_BOTERATOR_BOT_REVOKE:
            yield self.db.execute('UPDATE registered_bots SET active = FALSE WHERE id = %s', (body['id'],))

            try:
                yield self.send_message(pgettext('Unable to establish startup connection with bot',
                                                 'I\'m failed to establish connection to your bot with token `{token}`'
                                                 ', received error: `{error}`.\n'
                                                 'Your bot was deactivated, to enable it again - perform registration '
                                                 'process from the beginning.').format(token=body['token'],
                                                                                       error=body['error']),
                                        chat_id=body['owner_id'], parse_mode=Api.PARSE_MODE_MD)
            except:
                logging.exception('Got exception while notifying user on bot disable')
        else:
            raise Exception('Unknown queue: %s', queue_name)
