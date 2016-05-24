import logging
from datetime import datetime, timedelta

from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado import locale

from core.bot import Base
from core.handlers.cancel import cancel_command
from core.handlers.emoji_end import emoji_end
from core.handlers.slave.ban import ban_command, plaintext_ban_handler, unban_command, ban_list_command
from core.handlers.slave.help import help_command
from core.handlers.slave.pollslist import polls_list_command
from core.handlers.slave.reply import reply_command, plaintext_reply_handler
from core.handlers.slave.setallowed import change_allowed_command, plaintext_contenttype_handler
from core.handlers.slave.setdelay import setdelay_command, plaintext_delay_handler
from core.handlers.slave.setlanguage import setlanguage, setlanguage_plaintext
from core.handlers.slave.chat import new_chat, left_chat
from core.handlers.slave.post import plaintext_post_handler, multimedia_post_handler, cbq_message_review, \
    cbq_cancel_publishing
from core.handlers.slave.setstartmessage import plaintext_startmessage_handler
from core.handlers.slave.setstartmessage import setstartmessage_command
from core.handlers.slave.settextlimits import plaintext_textlimits_handler, settextlimits_command
from core.handlers.slave.settimeout import plaintext_timeout_handler
from core.handlers.slave.settimeout import settimeout_command
from core.handlers.slave.setvotes import plaintext_votes_handler
from core.handlers.slave.setvotes import setvotes_command
from core.handlers.slave.start import start_command
from core.handlers.slave.stats import stats_command
from core.handlers.slave.toggle_power import togglepower_command
from core.handlers.slave.vote import vote_yes, vote_no
from core.handlers.unknown_command import unknown_command
from core.handlers.validate_user import validate_user
from helpers import report_botan, npgettext, pgettext


class Slave(Base):
    def __init__(self, token, db, **kwargs):
        super().__init__(token, db, **kwargs)
        self.administrators = [kwargs['owner_id']]

    def _init_handlers(self):
        self.cancellation_handler = cancel_command
        self.unknown_command_handler = unknown_command
        self._add_handler(validate_user, None)
        self._add_handler(cancel_command, None)
        self._add_handler(start_command, None)
        self._add_handler(new_chat, None)
        self._add_handler(left_chat, None)
        self._add_handler(vote_yes, None)
        self._add_handler(vote_no, None)

        self._add_handler(setlanguage, is_final=False)
        self._add_handler(emoji_end, None, setlanguage)
        self._add_handler(setlanguage_plaintext, None, setlanguage)

        self._add_handler(ban_command, None, is_final=False)
        self._add_handler(plaintext_ban_handler, None, ban_command)
        self._add_handler(unban_command, None)
        self._add_handler(ban_list_command, None)

        self._add_handler(reply_command, None, is_final=False)
        self._add_handler(plaintext_reply_handler, None, reply_command)

        self._add_handler(setdelay_command, None, is_final=False)
        self._add_handler(plaintext_delay_handler, None, setdelay_command)

        self._add_handler(setstartmessage_command, None, is_final=False)
        self._add_handler(plaintext_startmessage_handler, None, setstartmessage_command)

        self._add_handler(settimeout_command, None, is_final=False)
        self._add_handler(plaintext_timeout_handler, None, settimeout_command)

        self._add_handler(setvotes_command, None, is_final=False)
        self._add_handler(plaintext_votes_handler, None, setvotes_command)

        self._add_handler(settextlimits_command, None, is_final=False)
        self._add_handler(plaintext_textlimits_handler, None, settextlimits_command)

        self._add_handler(change_allowed_command, None, is_final=False)
        self._add_handler(emoji_end, None, change_allowed_command)
        self._add_handler(plaintext_contenttype_handler, None, change_allowed_command)

        self._add_handler(togglepower_command, None)

        self._add_handler(stats_command, None)
        self._add_handler(help_command, None)
        self._add_handler(polls_list_command, None)

        self._add_handler(plaintext_post_handler, None, is_final=False)
        self._add_handler(cbq_message_review, None, plaintext_post_handler)
        self._add_handler(cbq_cancel_publishing, None, plaintext_post_handler)

        self._add_handler(multimedia_post_handler, None, is_final=False)
        self._add_handler(cbq_message_review, None, multimedia_post_handler)
        self._add_handler(cbq_cancel_publishing, None, multimedia_post_handler)

    @coroutine
    def start(self):
        self.check_votes_success()
        self.check_votes_failures()
        chat_info = yield self.api.get_chat(self.moderator_chat_id)
        if chat_info['type'] == 'private':
            self.administrators = [chat_info['id']]
        else:
            admins = yield self.api.get_chat_administrators(self.moderator_chat_id)
            self.administrators = [
                user['user']['id']
                for user in admins
                ]
        yield super().start()

    @coroutine
    def check_votes_success(self):
        cur = yield self.db.execute('SELECT last_channel_message_at FROM registered_bots WHERE id = %s',
                                    (self.bot_id,))
        row = cur.fetchone()
        if row and row[0]:
            allowed_time = row[0] + timedelta(minutes=self.settings.get('delay', 15))
        else:
            allowed_time = datetime.now()

        if datetime.now() >= allowed_time:
            cur = yield self.db.execute('SELECT message FROM incoming_messages WHERE bot_id = %s '
                                        'AND is_voting_success = TRUE AND is_published = FALSE '
                                        'ORDER BY created_at LIMIT 1', (self.bot_id,))

            row = cur.fetchone()

            if row:
                yield self.publish_message(row[0])

        if not self._finished.is_set():
            IOLoop.current().add_timeout(timedelta(minutes=1), self.check_votes_success)

    @coroutine
    def publish_message(self, message):
        report_botan(message, 'slave_publish')
        try:
            yield self.bot.forward_message(self.channel_name, message['chat']['id'], message['message_id'])
            yield self.db.execute(
                'UPDATE incoming_messages SET is_published = TRUE WHERE id = %s AND original_chat_id = %s',
                (message['message_id'], message['chat']['id']))
            yield self.db.execute('UPDATE registered_bots SET last_channel_message_at = NOW() WHERE id = %s',
                                  (self.bot_id,))
        except:
            logging.exception('Message forwarding failed (#%s from %s)', message['message_id'], message['chat']['id'])

    @coroutine
    def check_votes_failures(self):
        vote_timeout = datetime.now() - timedelta(hours=self.settings.get('vote_timeout', 24))
        cur = yield self.db.execute('SELECT message,'
                                    '(SELECT SUM(vote_yes::INT) FROM votes_history vh WHERE vh.message_id = im.id AND vh.original_chat_id = im.original_chat_id)'
                                    'FROM incoming_messages im WHERE bot_id = %s AND '
                                    'is_voting_success = FALSE AND is_voting_fail = FALSE AND created_at <= %s',
                                    (self.bot_id, vote_timeout))

        for message, yes_votes in cur.fetchall():
            report_botan(message, 'slave_verification_failed')
            try:
                self.decline_message(message, yes_votes)
            except:
                pass

        if not self._finished.is_set():
            IOLoop.current().add_timeout(timedelta(minutes=10), self.check_votes_failures)

    @coroutine
    def decline_message(self, message, yes_votes):
        yield self.db.execute('UPDATE incoming_messages SET is_voting_fail = TRUE WHERE bot_id = %s AND '
                              'is_voting_success = FALSE AND is_voting_fail = FALSE AND original_chat_id = %s '
                              'AND id = %s',
                              (self.bot_id, message['chat']['id'], message['message_id']))

        received_votes_msg = npgettext('Received votes count', '{votes_received} vote',
                                       '{votes_received} votes',
                                       yes_votes).format(votes_received=yes_votes)
        required_votes_msg = npgettext('Required votes count', '{votes_required}', '{votes_required}',
                                       self.settings['votes']).format(votes_required=self.settings['votes'])

        yield self.api.send_message(pgettext('Voting failed', 'Unfortunately your message got only '
                                                              '{votes_received_msg} out of required '
                                                              '{votes_required_msg} and won\'t be published to '
                                                              'the channel.')
                                    .format(votes_received_msg=received_votes_msg,
                                            votes_required_msg=required_votes_msg), reply_to_message=message)

    @property
    def language(self):
        return self.settings.get('locale', 'en_US')

    @property
    def locale(self):
        return locale.get(self.language)
