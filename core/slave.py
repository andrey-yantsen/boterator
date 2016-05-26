import logging
from datetime import datetime, timedelta

from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado import locale
from ujson import dumps

from tobot import Base
from tobot.stages import PersistentStages
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
from core.handlers.slave.toggle_vote import togglevote_command
from core.handlers.slave.vote import vote_yes, vote_no
from core.handlers.unknown_command import unknown_command
from core.handlers.validate_user import validate_user
from core.settings import DEFAULT_SLAVE_SETTINGS
from tobot.helpers import report_botan, npgettext, pgettext, Emoji
from tobot.helpers.lazy_gettext import set_locale_recursive
from tobot.telegram import InlineKeyboardMarkup, InlineKeyboardButton, ApiError


class Slave(Base):
    def __init__(self, token, db, **kwargs):
        bot_settings = kwargs.pop('settings', {})
        if 'hello' in bot_settings:
            del bot_settings['hello']
        bot_settings = self.merge_settings_recursive(DEFAULT_SLAVE_SETTINGS, bot_settings)
        self.db = db
        super().__init__(token, stages_builder=lambda bot_id: PersistentStages(bot_id, db), settings=bot_settings,
                         **kwargs)
        self.administrators = [kwargs['owner_id']]

    @coroutine
    def _update_settings_for_user(self, user_id, settings):
        yield self.db.execute('UPDATE users SET settings = %s WHERE bot_id = %s AND user_id = %s',
                              (dumps(self.user_settings[user_id]), self.bot_id, user_id))

    def merge_settings_recursive(self, base_settings, bot_settings):
        for key, value in base_settings.items():
            if type(value) is dict:
                bot_settings[key] = self.merge_settings_recursive(value, bot_settings.get(key, {}))
            else:
                bot_settings.setdefault(key, value)

        return bot_settings

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
        self._add_handler(togglevote_command, None)

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
            cur = yield self.db.execute('SELECT message, moderation_message_id FROM incoming_messages WHERE bot_id = %s '
                                        'AND is_voting_success = TRUE AND is_published = FALSE '
                                        'ORDER BY created_at LIMIT 1', (self.bot_id,))

            row = cur.fetchone()

            if row:
                yield self.publish_message(row[0], row[1])

        if not self._finished.is_set():
            IOLoop.current().add_timeout(timedelta(minutes=1), self.check_votes_success)

    @coroutine
    def publish_message(self, message, moderation_message_id):
        report_botan(message, 'slave_publish')
        try:
            yield self.api.forward_message(self.target_channel, message['chat']['id'], message['message_id'])
            yield self.db.execute(
                'UPDATE incoming_messages SET is_published = TRUE WHERE id = %s AND original_chat_id = %s',
                (message['message_id'], message['chat']['id']))
            yield self.db.execute('UPDATE registered_bots SET last_channel_message_at = NOW() WHERE id = %s',
                                  (self.bot_id,))

            msg, keyboard = yield self.get_verification_message(message['message_id'], message['chat']['id'], True)
            yield self.edit_message_text(msg, chat_id=self.moderator_chat_id, message_id=moderation_message_id,
                                             reply_markup=keyboard)
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
                yield self.decline_message(message, yes_votes)
            except:
                logging.exception('Got exception while declining message')

        if not self._finished.is_set():
            IOLoop.current().add_timeout(timedelta(minutes=10), self.check_votes_failures)

    @coroutine
    def decline_message(self, message, yes_votes):
        cur = yield self.db.execute('SELECT moderation_message_id FROM incoming_messages WHERE bot_id = %s AND '
                                    'original_chat_id = %s AND id = %s', (self.bot_id, message['chat']['id'],
                                                                          message['message_id']))

        row = cur.fetchone()

        if row and row[0]:
            moderation_message_id = row[0]

            msg, keyboard = yield self.get_verification_message(message['message_id'], message['chat']['id'], True)
            try:
                yield self.edit_message_text(msg, chat_id=self.moderator_chat_id, message_id=moderation_message_id,
                                             reply_markup=keyboard)
            except Exception as e:
                # Ignore `message is not modified` errors
                if not isinstance(e, ApiError) or not e.code == 400 or 'message is not modified' not in e.description:
                    raise

        yield self.db.execute('UPDATE incoming_messages SET is_voting_fail = TRUE WHERE bot_id = %s AND '
                              'is_voting_success = FALSE AND is_voting_fail = FALSE AND original_chat_id = %s '
                              'AND id = %s',
                              (self.bot_id, message['chat']['id'], message['message_id']))

        received_votes_msg = npgettext('Received votes count', '{votes_received} vote',
                                       '{votes_received} votes',
                                       yes_votes).format(votes_received=yes_votes)
        required_votes_msg = npgettext('Required votes count', '{votes_required}', '{votes_required}',
                                       self.settings['votes']).format(votes_required=self.settings['votes'])

        yield self.send_message(pgettext('Voting failed', 'Unfortunately your message got only {votes_received_msg} '
                                                          'out of required {votes_required_msg} and won\'t be '
                                                          'published to the channel.')
                                .format(votes_received_msg=received_votes_msg,
                                        votes_required_msg=required_votes_msg), reply_to_message=message)

    @property
    def language(self):
        return self.settings.get('locale', 'en_US')

    @property
    def locale(self):
        return locale.get(self.language)

    @coroutine
    def send_moderation_request(self, message_owner_id, chat_id, message_id):
        yield self.forward_message(self.moderator_chat_id, chat_id, message_id)

        msg, voting_keyboard = yield self.get_verification_message(message_id, chat_id)

        moderation_msg = yield self.send_message(msg, chat_id=self.moderator_chat_id, reply_markup=voting_keyboard)
        cur = yield self.db.execute('SELECT moderation_message_id FROM incoming_messages WHERE id = %s AND '
                                    'original_chat_id = %s AND bot_id = %s', (message_id, chat_id, self.bot_id))
        row = cur.fetchone()
        if row and row[0]:
            self.edit_message_text(pgettext('Newer poll for this message posted below', '_Outdated_'),
                                   chat_id=self.moderator_chat_id, message_id=row[0], parse_mode=self.PARSE_MODE_MD)

        yield self.db.execute('UPDATE incoming_messages SET moderation_message_id = %s WHERE id = %s AND '
                              'original_chat_id = %s AND bot_id = %s',
                              (moderation_msg['message_id'], message_id, chat_id,
                               self.bot_id))
        yield self.db.execute('UPDATE registered_bots SET last_moderation_message_at = NOW() WHERE id = %s',
                              (self.bot_id,))

    @coroutine
    def _build_voting_status(self, message_id, chat_id, voting_finished):
        cur = yield self.db.execute('SELECT count(*), sum(vote_yes::int) FROM votes_history WHERE message_id = %s AND '
                                    'original_chat_id = %s', (message_id, chat_id))

        total_votes, approves = cur.fetchone()
        if total_votes == 0:
            percent_yes = 0
            percent_no = 0
            approves = 0
        else:
            percent_yes = approves / total_votes
            percent_no = 1 - percent_yes

        max_thumbs = 8

        thumb_ups = Emoji.THUMBS_UP_SIGN * round(max_thumbs * percent_yes)
        thumb_downs = Emoji.THUMBS_DOWN_SIGN * round(max_thumbs * percent_no)

        message = [pgettext('Beginning of poll message', 'Current poll progress:'),
                   npgettext('Count of voted moderators', '{cnt} vote', '{cnt} votes', total_votes).format(
                       cnt=total_votes)]

        if voting_finished or self.settings.get('public_vote', True):
            message.append("{thumb_up}{thumbs_up} — {percent_yes}%\n" \
                           "{thumb_down}{thumbs_down} — {percent_no}%\n".format(thumb_up=Emoji.THUMBS_UP_SIGN,
                                                                                thumbs_up=thumb_ups,
                                                                                percent_yes=round(percent_yes * 100),
                                                                                thumb_down=Emoji.THUMBS_DOWN_SIGN,
                                                                                thumbs_down=thumb_downs,
                                                                                percent_no=round(percent_no * 100)))

        if voting_finished:
            message.append(pgettext('Poll finished', 'Poll is closed.'))
            if approves >= self.settings['votes']:
                cur = yield self.db.execute('SELECT is_published FROM incoming_messages WHERE bot_id = %s AND '
                                            'id = %s AND original_chat_id = %s', (self.bot_id, message_id, chat_id))

                row = cur.fetchone()
                if row and row[0]:
                    message.append(pgettext('Vote successful, message is published', 'The message is published.'))
                else:
                    message.append(pgettext('Vote successful', 'The message will be published soon.'))
            else:
                message.append(pgettext('Vote failed', 'The message will not be published.'))

        return message

    @staticmethod
    def build_voting_keyboard(message_owner_id, message_id, chat_id):
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton(Emoji.THUMBS_UP_SIGN,
                                     callback_data='vote_%s_%s_yes' % (chat_id, message_id)),
                InlineKeyboardButton(Emoji.THUMBS_DOWN_SIGN,
                                     callback_data='vote_%s_%s_no' % (chat_id, message_id)),
            ],
            [
                InlineKeyboardButton(pgettext('Reply to user button', 'Reply'),
                                     callback_data='reply_%s_%s' % (chat_id, message_id)),
                InlineKeyboardButton(pgettext('Ban user button', 'Ban this ass'),
                                     callback_data='ban_%s' % (message_owner_id,)),
            ],
        ])

    @coroutine
    def get_verification_message(self, message_id, chat_id, voting_finished=False):
        msg = yield self._build_voting_status(message_id, chat_id, voting_finished)

        if voting_finished:
            voting_keyboard = None
        else:
            cur = yield self.db.execute('SELECT owner_id FROM incoming_messages WHERE bot_id = %s AND id = %s AND '
                                        'original_chat_id = %s', (self.bot_id, message_id, chat_id))
            row = cur.fetchone()
            if row and row[0]:
                message_owner_id = row[0]
            else:
                message_owner_id = chat_id
            msg.insert(0, pgettext('Verification message', 'What will we do with this message?'))
            voting_keyboard = self.build_voting_keyboard(message_owner_id, message_id, chat_id)

        return '\n'.join(set_locale_recursive(msg, self.locale)), voting_keyboard
