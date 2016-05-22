import logging
from copy import deepcopy
from time import time
from ujson import dumps

from tornado.gen import coroutine, sleep

from core.bot import Base, CommandFilterTextCmd, CommandFilterTextAny
from core.handlers.boterator.cancel import cancel_command
from core.handlers.boterator.reg import reg_command, plaintext_token, plaintext_channel_name, \
    plaintext_set_start_message, change_start_command, plaintext_set_hello, change_hello_command
from core.handlers.boterator.start import start_command
from core.handlers.emoji_end import emoji_end
from core.handlers.setlanguage import setlanguage, setlanguage_plaintext
from core.handlers.setlanguage_at_start import setlanguage_at_start, setlanguage_at_start_plaintext
from core.handlers.unknown_command import unknown_command
from core.handlers.validate_user import validate_user
from core.queues import boterator_queues, QUEUE_SLAVEHOLDER_GET_BOT_INFO, QUEUE_BOTERATOR_BOT_INFO
from helpers import pgettext
from telegram import Api


class Boterator(Base):
    SETTINGS_TYPE = Base.SETTINGS_PER_USER

    def __init__(self, token, db, queue, **kwargs):
        super().__init__(token, db, **kwargs)
        self.queue = queue

    @coroutine
    def _load_user_settings_per_user(self):
        ret = {}
        cur = yield self.db.execute('SELECT user_id, settings FROM users WHERE bot_id = %s', (self.bot_id, ))
        while True:
            row = cur.fetchone()
            if not row:
                break

            ret[row[0]] = row[1]
        return ret

    def _init_handlers(self):
        self.cancellation_handler = cancel_command
        self.unknown_command_handler = unknown_command
        self._add_handler(validate_user, CommandFilterTextAny())
        self._add_handler(setlanguage, CommandFilterTextCmd('/setlanguage'), is_final=False)
        self._add_handler(emoji_end, CommandFilterTextAny(), None, setlanguage)
        self._add_handler(setlanguage_plaintext, CommandFilterTextAny(), None, setlanguage)
        self._add_handler(setlanguage_at_start, CommandFilterTextCmd('/start'), is_final=False)
        self._add_handler(setlanguage_at_start_plaintext, CommandFilterTextAny(), None, setlanguage_at_start)
        self._add_handler(start_command, CommandFilterTextCmd('/start'))
        self._add_handler(cancel_command, CommandFilterTextCmd('/cancel'))
        self._add_handler(reg_command, CommandFilterTextCmd('/reg'), pgettext('Command name',
                                                                              '/reg — register a new bot'),
                          is_final=False)
        self._add_handler(plaintext_token, CommandFilterTextAny(), pgettext('Action description', 'Waiting for the '
                                                                                                  'token'),
                          previous_handler=reg_command, is_final=False)

        self._add_handler(change_hello_command, CommandFilterTextCmd('/sethello'), None,
                          previous_handler=plaintext_token, is_final=False)
        self._add_handler(plaintext_set_hello, CommandFilterTextAny(), None,
                          previous_handler=change_hello_command, is_final=False)
        self._add_handler(change_hello_command, CommandFilterTextCmd('/sethello'), None,
                          previous_handler=plaintext_set_hello, is_final=False)
        self._add_handler(change_start_command, CommandFilterTextCmd('/setstart'), None,
                          previous_handler=plaintext_set_hello, is_final=False)
        self._add_handler(plaintext_channel_name, CommandFilterTextAny(), None,
                          previous_handler=plaintext_set_hello, is_final=True)

        self._add_handler(change_start_command, CommandFilterTextCmd('/setstart'), None,
                          previous_handler=plaintext_token, is_final=False)
        self._add_handler(plaintext_set_start_message, CommandFilterTextAny(), None,
                          previous_handler=change_start_command, is_final=False)
        self._add_handler(change_start_command, CommandFilterTextCmd('/setstart'), None,
                          previous_handler=plaintext_set_start_message, is_final=False)
        self._add_handler(change_hello_command, CommandFilterTextCmd('/sethello'), None,
                          previous_handler=plaintext_set_start_message, is_final=False)
        self._add_handler(plaintext_channel_name, CommandFilterTextAny(), None,
                          previous_handler=plaintext_set_start_message, is_final=True)

        self._add_handler(plaintext_channel_name, CommandFilterTextAny(), pgettext('Action description',
                                                                                   'Waiting for the channel name'),
                          previous_handler=plaintext_token, is_final=True)

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
        pass

    @coroutine
    def slave_revoked(self, bot_id, token, owner_id, pgettext):
        yield DB.execute('UPDATE registered_bots SET active = FALSE WHERE id = %s', (bot_id,))
        if bot_id in self.slaves:
            del self.slaves[bot_id]

        try:
            yield self.bot.send_message(pgettext('Boterator: unable to establish startup connection with bot',
                                                 'I\'m failed to establish connection to your bot with token %s. Your '
                                                 'bot was deactivated, to enable it again - perform registration '
                                                 'process from the beginning.') % token, chat_id=owner_id)
        except:
            pass
