import logging
import re
from copy import deepcopy
from datetime import datetime, timedelta
from itertools import groupby
from time import time
from ujson import dumps

from math import floor

from babel.dates import format_date
from babel.numbers import format_number
from tornado.gen import coroutine, sleep
from tornado.ioloop import IOLoop
from tornado import locale
from tornado.locale import load_gettext_translations

from emoji import Emoji
from globals import get_db
from telegram import Api, ForceReply, ReplyKeyboardHide, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, \
    InlineKeyboardButton, ApiError

from helpers import report_botan, is_allowed_user, StagesStorage, append_pgettext, append_npgettext
from telegram_log_handler import TelegramHandler


class BotMother:
    STAGE_WAITING_TOKEN = 1
    STAGE_MODERATION_GROUP = 2
    STAGE_WAITING_PUBLIC_CHANNEL = 3
    STAGE_REGISTERED = 4
    STAGE_WAITING_HELLO = 6
    STAGE_WAITING_START_MESSAGE = 8

    def __init__(self, token, logging_user_id):
        bot = Api(token)
        bot.add_handler(self.validate_user, False, Api.UPDATE_TYPE_MSG_ANY)
        bot.add_handler(self.start_command, '/start')
        bot.add_handler(self.reg_command, '/reg')
        bot.add_handler(self.plaintext_token)
        bot.add_handler(self.cancel_command, '/cancel')
        bot.add_handler(self.change_hello_command, '/changehello')
        bot.add_handler(self.plaintext_set_hello)
        bot.add_handler(self.change_start_command, '/changestart')
        bot.add_handler(self.plaintext_set_start_message)
        bot.add_handler(self.plaintext_channel_name)
        self.bot = bot
        self.stages = StagesStorage()
        self.slaves = {}

        load_gettext_translations('./locales', 'boterator')
        self.locale = locale.get('en')

        logger = logging.getLogger()
        logger.addHandler(TelegramHandler(bot, logging_user_id, level=logging.WARNING))

        self.default_slave_settings = {}

    @coroutine
    @append_pgettext
    def validate_user(self, message, pgettext):
        bot_info = yield self.bot.get_me()
        allowed = is_allowed_user(message['from'], bot_info['id'])
        if allowed:
            return False

        yield self.bot.send_message(pgettext('Boterator: User not allowed to perform this action', 'Access denied'),
                                    reply_to_message=message)

    @coroutine
    @append_pgettext
    def start_command(self, message, pgettext):
        report_botan(message, 'boterator_start')
        yield self.bot.send_message(pgettext('Boterator: /start response', 'Hello, this is Boterator. In order to '
                                                                           'start ask @BotFather to create a new bot. '
                                                                           'Then feel free to use /reg command to '
                                                                           'register new bot using token.'),
                                    reply_to_message=message)

    @coroutine
    @append_pgettext
    def reg_command(self, message, pgettext):
        if self.stages.get_id(message):
            return False

        report_botan(message, 'boterator_reg')

        yield self.bot.send_message(pgettext('Boterator: /reg response', 'Ok, please tell me the token, which you\'ve '
                                                                         'received from @BotFather'),
                                    reply_to_message=message)
        self.stages.set(message, self.STAGE_WAITING_TOKEN)

    @coroutine
    @append_pgettext
    def plaintext_token(self, message, pgettext):
        if self.stages.get_id(message) != self.STAGE_WAITING_TOKEN:
            return False

        token = message['text'].strip()
        if token == '':
            report_botan(message, 'boterator_token_empty')
            yield self.bot.send_message(pgettext('Boterator: empty token entered', 'I guess you forgot to enter the '
                                                                                   'token :)'),
                                        reply_to_message=message)
        else:
            if len(token.split(':')) != 2:
                report_botan(message, 'boterator_token_invalid')
                yield self.bot.send_message(pgettext('Boterator: non-well formatted token', 'Token is incorrect. And I '
                                                                                            'can do nothing with that.'),
                                            reply_to_message=message)
                return

            yield self.bot.send_chat_action(message['chat']['id'], self.bot.CHAT_ACTION_TYPING)

            try:
                new_bot = Api(token)
                new_bot_me = yield new_bot.get_me()
                if new_bot_me['id'] in self.slaves:
                    report_botan(message, 'boterator_token_duplicate')
                    yield self.bot.send_message(pgettext('Boterator: provided token is already registered and alive',
                                                         'It seems like this bot is already registered. Try to create '
                                                         'another one'), reply_to_message=message)
                    return

                msg = pgettext('Boterator: token received',
                               "Ok, I\'ve got basic information for @%s\n"
                               'Now add him to a group of moderators (or copy and paste `@%s '
                               '/attach` to the group, in case you’ve already added him), where '
                               'I should send messages for verification, or type /cancel')

                bot_username_escaped = new_bot_me['username'].replace('_', r'\_')
                msg = msg % (bot_username_escaped, new_bot_me['username'])

                yield self.bot.send_message(msg, reply_to_message=message, parse_mode=Api.PARSE_MODE_MD)

                hello_message = pgettext('Boterator: default channel-hello message',
                                         'Hi there, guys! Now it is possible to publish messages in this channel by '
                                         'any of you. All you need to do — is to write a message to me (bot named '
                                         '@%s), and it will be published after verification by our team.') \
                                % new_bot_me['username']

                self.stages.set(message, self.STAGE_MODERATION_GROUP, token=token, bot_info=new_bot_me,
                                hello=hello_message, start_message=self.default_slave_settings['start'])

                self.__wait_for_registration_complete(message)
                report_botan(message, 'boterator_token')
            except Exception as e:
                report_botan(message, 'boterator_token_failure')
                logging.exception(e)
                yield self.bot.send_message(pgettext('Boterator: Token check failed', 'Unable to get bot info: %s') % str(e),
                                            reply_to_message=message)

    @coroutine
    @append_pgettext
    def cancel_command(self, message, pgettext):
        report_botan(message, 'boterator_cancel')
        self.stages.drop(message)
        yield self.bot.send_message(pgettext('Boterator: /cancel response', 'Oka-a-a-a-a-ay.'),
                                    reply_to_message=message)

    @coroutine
    @append_pgettext
    def plaintext_channel_name(self, message, pgettext):
        stage = self.stages.get(message)
        if stage[0] == self.STAGE_WAITING_PUBLIC_CHANNEL:
            channel_name = message['text'].strip()
            if message['text'][0] != '@' or ' ' in channel_name:
                report_botan(message, 'boterator_channel_invalid')
                yield self.bot.send_message(pgettext('Boterator: invalid channel name received',
                                                     'Invalid channel name. Try again or type /cancel'),
                                            reply_to_message=message)
            else:
                try:
                    new_bot = Api(stage[1]['token'])
                    try:
                        yield new_bot.send_message(stage[1]['hello'], chat_id=channel_name,
                                                   parse_mode=Api.PARSE_MODE_MD)
                    except:
                        yield new_bot.send_message(stage[1]['hello'], chat_id=channel_name)
                    self.stages.set(message, self.STAGE_REGISTERED, channel=channel_name)
                    report_botan(message, 'boterator_registered')
                except Exception as e:
                    report_botan(message, 'boterator_channel_failure')
                    yield self.bot.send_message(pgettext('Boterator: sending channel-hello message failed',
                                                         'Hey, I\'m unable to send hello message, is everything ready '
                                                         'for me? Here is an error from Telegram api: %s') % str(e),
                                                reply_to_message=message)
        else:
            return False

    @coroutine
    @append_pgettext
    def listen(self, pgettext):
        self.default_slave_settings = {
            'delay': 15,
            'votes': 2,
            'vote_timeout': 24,
            'text_min': 50,
            'text_max': 1000,
            'start': pgettext('Boterator: default start message', "Just enter your message, and we're ready."),
            'content_status': {
                'text': True,
                'photo': False,
                'voice': False,
                'video': False,
                'audio': False,
                'document': False,
                'sticker': False,
            },
        }

        logging.info('Initializing slaves')
        self.slaves = dict()

        cur = yield get_db().execute('SELECT id, token, owner_id, moderator_chat_id, target_channel, settings FROM '
                                     'registered_bots WHERE active = TRUE')

        def update_settings_recursive(base_settings, bot_settings):
            base_settings = deepcopy(base_settings)

            for key, value in bot_settings.items():
                if type(value) is dict:
                    base_settings[key] = update_settings_recursive(base_settings[key], value)
                else:
                    base_settings[key] = value

            return base_settings

        for bot_id, token, owner_id, moderator_chat_id, target_channel, settings in cur.fetchall():
            slave_settings = update_settings_recursive(self.default_slave_settings, settings)
            slave = Slave(token, self, moderator_chat_id, target_channel, slave_settings, owner_id, bot_id)
            while True:
                try:
                    yield slave.bot.get_me()
                    slave.listen()
                    self.slaves[bot_id] = slave
                    break
                except Exception as e:
                    if isinstance(e, ApiError) and e.code == 401:
                        logging.exception('Bot #%s failed to connect', bot_id, token, owner_id)
                        yield self.slave_revoked(bot_id, token, owner_id)
                        break
                    else:
                        logging.exception('Something bad happened')
                        yield sleep(10)

        logging.info('Waiting for commands')
        yield self.bot.wait_commands()
        logging.info('Mother termination')

    @coroutine
    @append_pgettext
    def slave_revoked(self, bot_id, token, owner_id, pgettext):
        yield get_db().execute('UPDATE registered_bots SET active = FALSE WHERE id = %s', (bot_id,))
        if bot_id in self.slaves:
            del self.slaves[bot_id]

        try:
            yield self.bot.send_message(pgettext('Boterator: unable to establish startup connection with bot',
                                                 'I\'m failed to establish connection to your bot with token %s. Your '
                                                 'bot was deactivated, to enable it again - perform registration '
                                                 'process from the beginning.') % token, chat_id=owner_id)
        except:
            pass

    @coroutine
    @append_pgettext
    @append_npgettext
    def __wait_for_registration_complete(self, original_message, npgettext=None, pgettext=None, timeout=3600):
        stage = self.stages.get(original_message)
        slave = Slave(stage[1]['token'], self, None, None, {}, original_message['from']['id'], None)
        slave.listen()
        while True:
            stage_id, stage_meta, stage_begin = self.stages.get(original_message)

            if stage_id == self.STAGE_REGISTERED:
                settings = deepcopy(self.default_slave_settings)
                settings['start'] = stage_meta['start_message']

                yield slave.stop()

                yield self.bot.send_chat_action(original_message['chat']['id'], self.bot.CHAT_ACTION_TYPING)
                yield get_db().execute("""
                                      INSERT INTO registered_bots (id, token, owner_id, moderator_chat_id, target_channel, active, settings)
                                      VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                                      ON CONFLICT (id) DO UPDATE SET token = EXCLUDED.token, owner_id = EXCLUDED.owner_id,
                                      moderator_chat_id = EXCLUDED.moderator_chat_id, target_channel=EXCLUDED.target_channel,
                                      active = EXCLUDED.active, settings = EXCLUDED.settings
                                      """, (stage_meta['bot_info']['id'], stage_meta['token'],
                                            original_message['from']['id'], stage_meta['moderation'],
                                            stage_meta['channel'], dumps(settings)))
                slave = Slave(stage_meta['token'], self, stage_meta['moderation'], stage_meta['channel'],
                              settings, original_message['from']['id'], stage_meta['bot_info']['id'])
                slave.listen()
                self.slaves[stage_meta['bot_info']['id']] = slave

                votes_cnt_msg = npgettext('Boterator: default votes cnt', '%d vote', '%d votes',
                                          self.default_slave_settings['votes']) % self.default_slave_settings['votes']

                delay_msg = npgettext('Boterator: default delay', '%d minute', '%d minutes',
                                      self.default_slave_settings['delay']) % self.default_slave_settings['delay']

                timeout_msg = npgettext('Boterator: default timeout', '%d hour', '%d hours',
                                        self.default_slave_settings['vote_timeout']) \
                              % self.default_slave_settings['vote_timeout']

                msg = pgettext('Boterator: new bot registered',
                               "And we're ready for some magic!\n"
                               'By default the bot will wait for {votes_cnt_msg} to approve the '
                               'message, perform {delay_msg} delay between channel messages, '
                               'wait {timeout_msg} before closing a voting for each message and '
                               'allow only text messages (no multimedia content at all). To '
                               'modify this (and few other) settings send /help in PM to @{bot_username}. '
                               'By default you\'re the only user who can change these '
                               'settings and use /help command').format(votes_cnt_msg=votes_cnt_msg,
                                                                        delay_msg=delay_msg, timeout_msg=timeout_msg,
                                                                        bot_username=stage_meta['bot_info']['username'])

                try:
                    yield self.bot.send_message(msg, reply_to_message=original_message)
                except:
                    pass
                break
            elif time() - stage_begin >= timeout:
                yield slave.stop()
                try:
                    yield self.bot.send_message(pgettext('Boterator: registration cancelled due to timeout',
                                                         '@%s registration aborted due to timeout')
                                                % stage_meta['bot_info']['username'],
                                                reply_to_message=original_message)
                except:
                    pass
                break
            elif stage_id is None:
                # Action cancelled
                yield slave.stop()
                break

            yield sleep(0.05)

        self.stages.drop(original_message)

    @coroutine
    def stop(self):
        for slave in self.slaves.values():
            yield slave.stop()
        yield self.bot.stop()

    @coroutine
    @append_pgettext
    def set_slave_attached(self, message, chat, pgettext=None):
        stage = self.stages.get(message)
        yield self.bot.send_chat_action(message['chat']['id'], self.bot.CHAT_ACTION_TYPING)

        if 'title' not in chat:
            chat['title'] = '@' + message['from']['username']

        msg = pgettext('Boterator: slave attached to moderator`s channel',
                       "Ok, I'll be sending moderation requests to %s %s\n"
                       "Now you need to add your bot (@%s) to a channel as administrator and tell me the channel name "
                       "(e.g. @mobilenewsru)\n"
                       "As soon as I will receive the channel name I'll send a message with following text:\n> %s\n"
                       "You can change the message, if you mind, just send me /changehello.\n"
                       "Also there is 'start' message for your new bot:\n> %s\n"
                       "You can change it with /changestart") \
              % (chat['type'], chat['title'], stage[1]['bot_info']['username'], stage[1]['hello'],
                 stage[1]['start_message'])

        try:
            yield self.bot.send_message(msg, reply_to_message=message, parse_mode=Api.PARSE_MODE_MD)
        except:
            yield self.bot.send_message(msg, reply_to_message=message)

        self.stages.set(message, self.STAGE_WAITING_PUBLIC_CHANNEL, moderation=chat['id'])

    @coroutine
    @append_pgettext
    def change_hello_command(self, message, pgettext):
        if self.stages.get_id(message) != self.STAGE_WAITING_PUBLIC_CHANNEL:
            return False
        else:
            report_botan(message, 'boterator_change_hello_cmd')
            yield self.bot.send_message(pgettext('Boterator: /changehello response',
                                                 'Ok, I\'m listening to you. How I should say hello to your '
                                                 'subscribers?'),
                                        reply_to_message=message)
            self.stages.set(message, self.STAGE_WAITING_HELLO, do_not_validate=True)

    @coroutine
    @append_pgettext
    def plaintext_set_hello(self, message, pgettext):
        if self.stages.get_id(message) != self.STAGE_WAITING_HELLO:
            return False
        else:
            text = message['text'].strip()
            if len(text) >= 10:
                report_botan(message, 'boterator_change_hello_success')
                yield self.bot.send_message(pgettext('Boterator: channel-hello message updated',
                                                     'Ok, noted, now tell me the channel name'),
                                            reply_to_message=message)
                self.stages.set(message, self.STAGE_WAITING_PUBLIC_CHANNEL, do_not_validate=True, hello=text)
            else:
                report_botan(message, 'boterator_change_hello_short')
                yield self.bot.send_message(pgettext('Boterator: channel-hello message is too short',
                                                     'Hey, you should write at least 10 symbols'),
                                            reply_to_message=message)

    @coroutine
    @append_pgettext
    def change_start_command(self, message, pgettext):
        if self.stages.get_id(message) != self.STAGE_WAITING_PUBLIC_CHANNEL:
            return False
        else:
            report_botan(message, 'boterator_change_start_cmd')
            yield self.bot.send_message(pgettext('Boterator: /changestart response',
                                                 'Ok, I\'m listening to you. How I should say hello to your authors?'),
                                        reply_to_message=message)
            self.stages.set(message, self.STAGE_WAITING_START_MESSAGE, do_not_validate=True)

    @coroutine
    @append_pgettext
    def plaintext_set_start_message(self, message, pgettext):
        if self.stages.get_id(message) != self.STAGE_WAITING_START_MESSAGE:
            return False
        else:
            text = message['text'].strip()
            if len(text) >= 10:
                report_botan(message, 'boterator_change_start_success')
                yield self.bot.send_message(pgettext('Boterator: /start message updated',
                                                     'Ok, noted, now tell me the channel name'),
                                            reply_to_message=message)
                self.stages.set(message, self.STAGE_WAITING_PUBLIC_CHANNEL, do_not_validate=True, start_message=text)
            else:
                report_botan(message, 'boterator_change_start_short')
                yield self.bot.send_message(pgettext('Boterator: /start message is too short',
                                                     'Hey, you should write at least 10 symbols'),
                                            reply_to_message=message)


class Slave:
    STAGE_ADDING_MESSAGE = 1

    STAGE_WAIT_DELAY_VALUE = 3

    STAGE_WAIT_VOTES_VALUE = 5

    STAGE_WAIT_VOTE_TIMEOUT_VALUE = 7

    STAGE_WAIT_START_MESSAGE_VALUE = 9

    STAGE_WAIT_BAN_MESSAGE = 11

    STAGE_WAIT_REPLY_MESSAGE = 13

    STAGE_WAIT_CONTENT_TYPE = 15

    STAGE_WAIT_LANGUAGE = 17

    STAGE_WAIT_TEXT_LIMITS = 19

    LANGUAGE_LIST = (
        ('en_US', '%s English' % Emoji.FLAG_USA),
        ('ru_RU', '%s Русский' % Emoji.FLAG_RUSSIA),
    )

    RE_VOTE_YES = re.compile(r'/vote_(?P<chat_id>\d+)_(?P<message_id>\d+)_yes')
    RE_VOTE_NO = re.compile(r'/vote_(?P<chat_id>\d+)_(?P<message_id>\d+)_no')
    RE_BAN = re.compile(r'/ban_(?P<user_id>\d+)')
    RE_UNBAN = re.compile(r'/unban_(?P<user_id>\d+)')
    RE_REPLY = re.compile(r'/reply_(?P<chat_id>\d+)_(?P<message_id>\d+)')

    def __init__(self, token, m: BotMother, moderator_chat_id, channel_name, settings, owner_id, bot_id):
        bot = Api(token)
        bot.add_handler(self.validate_user, False, Api.UPDATE_TYPE_MSG_ANY)
        bot.add_handler(self.start_command, '/start')
        bot.add_handler(self.cancel_command, '/cancel')
        bot.add_handler(self.help_command, '/help')
        bot.add_handler(self.setdelay_command, '/setdelay')
        bot.add_handler(self.setvotes_command, '/setvotes')
        bot.add_handler(self.settimeout_command, '/settimeout')
        bot.add_handler(self.setstartmessage_command, '/setstartmessage')
        bot.add_handler(self.attach_command, '/attach')
        bot.add_handler(self.togglepower_command, '/togglepower')
        bot.add_handler(self.stats_command, '/stats')
        bot.add_handler(self.ban_list_command, '/banlist')
        bot.add_handler(self.polls_list_command, '/pollslist')
        bot.add_handler(self.change_allowed_command, '/changeallowed')
        bot.add_handler(self.switchlang_command, '/switchlang')
        bot.add_handler(self.settextlimits_command, '/settextlimits')
        bot.add_handler(self.cbq_message_review, 'confirm', Api.UPDATE_TYPE_CALLBACK_QUERY)
        bot.add_handler(self.cbq_cancel_publishing, 'cancel_publishing', Api.UPDATE_TYPE_CALLBACK_QUERY)
        bot.add_handler(self.plaintext_cancel_emoji_handler)
        bot.add_handler(self.plaintext_post_handler)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_AUDIO)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_VIDEO)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_PHOTO)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_VOICE)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_DOC)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_STICKER)
        bot.add_handler(self.plaintext_delay_handler)
        bot.add_handler(self.plaintext_votes_handler)
        bot.add_handler(self.plaintext_timeout_handler)
        bot.add_handler(self.plaintext_textlimits_handler)
        bot.add_handler(self.plaintext_startmessage_handler)
        bot.add_handler(self.plaintext_switchlang_handler)
        bot.add_handler(self.vote_yes, self.RE_VOTE_YES)
        bot.add_handler(self.vote_no, self.RE_VOTE_NO)
        bot.add_handler(self.ban_command, self.RE_BAN)
        bot.add_handler(self.unban_command, self.RE_UNBAN)
        bot.add_handler(self.plaintext_ban_handler)
        bot.add_handler(self.reply_command, self.RE_REPLY)
        bot.add_handler(self.plaintext_reply_handler)
        bot.add_handler(self.plaintext_contenttype_handler)
        bot.add_handler(self.new_chat, msg_type=bot.UPDATE_TYPE_MSG_NEW_CHAT_MEMBER)
        bot.add_handler(self.left_chat, msg_type=bot.UPDATE_TYPE_MSG_LEFT_CHAT_MEMBER)
        bot.add_handler(self.group_created, msg_type=bot.UPDATE_TYPE_MSG_GROUP_CHAT_CREATED)
        bot.add_handler(self.group_created, msg_type=bot.UPDATE_TYPE_MSG_SUPERGROUP_CHAT_CREATED)
        self.bot = bot
        self.mother = m
        self.moderator_chat_id = moderator_chat_id
        self.channel_name = channel_name
        self.stages = StagesStorage()
        self.settings = settings
        self.owner_id = owner_id
        self.bot_id = bot_id
        load_gettext_translations('./locales', 'boterator')
        self.locale = locale.get(self.language)

    @coroutine
    @append_pgettext
    def validate_user(self, message, pgettext):
        bot_info = yield self.bot.get_me()
        allowed = yield is_allowed_user(message['from'], bot_info['id'])
        if allowed:
            return False

        yield self.bot.send_message(pgettext('User banned', 'Access denied'), reply_to_message=message)

    @coroutine
    def listen(self):
        IOLoop.current().add_callback(self.check_votes_success)
        IOLoop.current().add_callback(self.check_votes_failures)
        while True:
            try:
                yield self.bot.wait_commands()
            except Exception as e:
                if isinstance(e, ApiError) and e.code == 401:
                    logging.warning('Bot #%s is unable to connect to api', self.bot_id)
                    yield self.mother.slave_revoked(self.bot_id, self.bot.token, self.owner_id)
                    break
                else:
                    logging.exception('Slave got exception')

            yield sleep(5)

        logging.info('Slave termination')

    @coroutine
    def check_votes_success(self):
        cur = yield get_db().execute('SELECT last_channel_message_at FROM registered_bots WHERE id = %s',
                                     (self.bot_id,))
        row = cur.fetchone()
        if row and row[0]:
            allowed_time = row[0] + timedelta(minutes=self.settings.get('delay', 15))
        else:
            allowed_time = datetime.now()

        if datetime.now() >= allowed_time:
            cur = yield get_db().execute('SELECT message FROM incoming_messages WHERE bot_id = %s '
                                         'AND is_voting_success = TRUE AND is_published = FALSE '
                                         'ORDER BY created_at LIMIT 1', (self.bot_id,))

            row = cur.fetchone()

            if row:
                yield self.publish_message(row[0])

        if self.bot.consumption_state == Api.STATE_WORKING:
            IOLoop.current().add_timeout(timedelta(minutes=1), self.check_votes_success)

    @coroutine
    def publish_message(self, message):
        report_botan(message, 'slave_publish')
        try:
            yield self.bot.forward_message(self.channel_name, message['chat']['id'], message['message_id'])
            yield get_db().execute(
                'UPDATE incoming_messages SET is_published = TRUE WHERE id = %s AND original_chat_id = %s',
                (message['message_id'], message['chat']['id']))
            yield get_db().execute('UPDATE registered_bots SET last_channel_message_at = NOW() WHERE id = %s',
                                   (self.bot_id,))
        except:
            logging.exception('Message forwarding failed (#%s from %s)', message['message_id'], message['chat']['id'])

    @coroutine
    def check_votes_failures(self):
        vote_timeout = datetime.now() - timedelta(hours=self.settings.get('vote_timeout', 24))
        cur = yield get_db().execute('SELECT message,'
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

        if self.bot.consumption_state == Api.STATE_WORKING:
            IOLoop.current().add_timeout(timedelta(minutes=10), self.check_votes_failures)

    @coroutine
    @append_npgettext
    @append_pgettext
    def decline_message(self, message, yes_votes, npgettext, pgettext):
        yield get_db().execute('UPDATE incoming_messages SET is_voting_fail = TRUE WHERE bot_id = %s AND '
                               'is_voting_success = FALSE AND is_voting_fail = FALSE AND original_chat_id = %s '
                               'AND id = %s',
                               (self.bot_id, message['chat']['id'], message['message_id']))

        received_votes_msg = npgettext('Received votes count', '{votes_received} vote',
                                       '{votes_received} votes',
                                       yes_votes).format(votes_received=yes_votes)
        required_votes_msg = npgettext('Required votes count', '{votes_required}', '{votes_required}',
                                       self.settings['votes']).format(votes_required=self.settings['votes'])

        yield self.bot.send_message(pgettext('Voting failed', 'Unfortunately your message got only '
                                                              '{votes_received_msg} out of required '
                                                              '{votes_required_msg} and won\'t be published to '
                                                              'the channel.')
                                    .format(votes_received_msg=received_votes_msg,
                                            votes_required_msg=required_votes_msg), reply_to_message=message)

    @coroutine
    def stop(self):
        yield self.bot.stop()

    @coroutine
    def start_command(self, message):
        if not self.moderator_chat_id:
            return False

        report_botan(message, 'slave_start')
        try:
            yield self.bot.send_message(self.settings['start'], reply_to_message=message, parse_mode=Api.PARSE_MODE_MD)
        except:
            yield self.bot.send_message(self.settings['start'], reply_to_message=message)

    @coroutine
    def is_moderators_chat(self, chat_id, bot_id):
        ret = yield get_db().execute('SELECT 1 FROM registered_bots WHERE moderator_chat_id = %s AND id = %s',
                                     (chat_id, bot_id,))
        return ret.fetchone() is not None

    @coroutine
    @append_pgettext
    def new_chat(self, message, pgettext):
        me = yield self.bot.get_me()

        if message['new_chat_member']['id'] == me['id']:
            known_chat = yield self.is_moderators_chat(message['chat']['id'], me['id'])
            if known_chat:
                yield get_db().execute('UPDATE registered_bots SET active = TRUE WHERE id = %s', (me['id'],))
                yield self.bot.send_message(pgettext('Bot added to a known group', 'Hi there, @{bot_username}!').format(
                    bot_username=message['from']['username']), chat_id=message['chat']['id'])
            else:
                user_id = message['from']['id']
                if self.mother.stages.get_id(user_id=user_id, chat_id=user_id) == BotMother.STAGE_MODERATION_GROUP:
                    yield self.attach_command(message)
                else:
                    yield self.bot.send_message(pgettext('Bot added to an unknown chat when he isn\'t ready for this',
                                                         'This bot wasn\'t registered for group {group_title}, type '
                                                         '/start for more info').format(
                        group_title=message['chat']['title']),
                                                chat_id=message['chat']['id'])
        else:
            return False

    @coroutine
    @append_pgettext
    def group_created(self, message, pgettext):
        user_id = message['from']['id']
        if self.mother.stages.get_id(user_id=user_id, chat_id=user_id) == BotMother.STAGE_MODERATION_GROUP:
            yield self.attach_command(message)
        else:
            try:
                yield self.bot.send_message(pgettext('New group created with bot and isn\'t ready for this',
                                                     'This bot wasn\'t registered for group {group_title}, type /start '
                                                     'for more info').format(group_title=message['chat']['title']),
                                            chat_id=user_id)
            except:
                pass

    @coroutine
    @append_pgettext
    def attach_command(self, message, pgettext):
        user_id = message['from']['id']
        stage = self.mother.stages.get(user_id=user_id, chat_id=user_id)
        report_botan(message, 'slave_attach')
        if stage[0] == BotMother.STAGE_MODERATION_GROUP:
            yield self.mother.set_slave_attached(stage[1]['last_message'], message['chat'])
        else:
            try:
                yield self.bot.send_message(pgettext('Bot received /attach command when he isn\'t ready',
                                                     'Incorrect command'), chat_id=message['chat']['id'])
            except:
                pass

    @coroutine
    def left_chat(self, message):
        me = yield self.bot.get_me()
        if message['left_chat_member']['id'] == me['id']:
            report_botan(message, 'slave_left_chat')
            yield get_db().execute('UPDATE registered_bots SET active = FALSE WHERE id = %s', (me['id'],))
        else:
            return False

    @coroutine
    @append_pgettext
    def cbq_message_review(self, message, pgettext):
        user_id = message['from']['id']
        stage = self.stages.get(user_id=user_id, chat_id=user_id)

        if stage[0] != self.STAGE_ADDING_MESSAGE:
            yield self.bot.answer_callback_query(message['id'], pgettext('User sent a command while another one is '
                                                                         'processing', 'Another action is in '
                                                                                       'progress.'))
            return

        report_botan(message, 'slave_confirm')
        user_message = stage[1]['last_message']
        yield self.bot.send_chat_action(user_id, Api.CHAT_ACTION_TYPING)
        bot_info = yield self.bot.get_me()
        yield get_db().execute("""
        INSERT INTO incoming_messages (id, original_chat_id, owner_id, bot_id, created_at, message)
        VALUES (%s, %s, %s, %s, NOW(), %s)
        """, (user_message['message_id'], user_message['chat']['id'], user_id, bot_info['id'], dumps(user_message)))
        yield self.post_new_moderation_request(user_message)

        yield self.bot.edit_message_text(pgettext('Message sent for verification', 'Okay, I\'ve sent your message for '
                                                                                   'verification. Fingers crossed!'),
                                         message['message'])
        self.stages.drop(user_id=user_id, chat_id=user_id)
        yield self.bot.answer_callback_query(message['id'])

    @coroutine
    @append_pgettext
    def cbq_cancel_publishing(self, message, pgettext):
        user_id = message['from']['id']
        self.stages.drop(user_id=user_id, chat_id=user_id)
        yield self.bot.edit_message_text(pgettext('Message publishing cancelled', 'Cancelled'), message['message'])
        yield self.bot.answer_callback_query(message['id'])

    @coroutine
    @append_pgettext
    def cancel_command(self, message, pgettext):
        report_botan(message, 'slave_cancel')
        self.stages.drop(message)
        yield self.bot.send_message(pgettext('Pending command cancelled', 'Oka-a-a-a-a-ay.'),
                                    reply_to_message=message, reply_markup=ReplyKeyboardHide())

    @coroutine
    @append_pgettext
    def _request_message_confirmation(self, message, pgettext):
        yield self.bot.forward_message(message['from']['id'], message['chat']['id'], message['message_id'])
        yield self.bot.send_message(pgettext('Message received, requesting the user to check the message once again',
                                             'Looks good for me. I\'ve printed the message in exact same way as it '
                                             'will be publised. Please, take a look on your message one more time. And '
                                             'click Confirm button if everything is fine'),
                                    reply_to_message=message,
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton(pgettext('`Confirm` button on message review keyboard',
                                                                       'Confirm'), callback_data='confirm'),
                                         InlineKeyboardButton(pgettext('`Cancel` button on message review keyboard',
                                                                       'Cancel'), callback_data='cancel_publishing'),
                                         ]
                                    ]))
        self.stages.set(message, self.STAGE_ADDING_MESSAGE)

    @coroutine
    @append_pgettext
    def plaintext_post_handler(self, message, pgettext):
        if message['chat']['type'] != 'private':
            return False  # Allow only in private

        if self.stages.get_id(message):
            return False

        if self.settings['content_status']['text'] is False:
            yield self.bot.send_message(pgettext('User send text message for verification while texts is disabled',
                                                 'Accepting text messages are disabled'),
                                        reply_to_message=message)
            return

        mes = message['text']
        if mes.strip() != '':
            if self.settings['text_min'] <= len(mes) <= self.settings['text_max']:
                yield self._request_message_confirmation(message)
                report_botan(message, 'slave_message')
            else:
                report_botan(message, 'slave_message_invalid')
                yield self.bot.send_message(pgettext('Incorrect text message received', 'Sorry, but we can proceed '
                                                                                        'only messages with length '
                                                                                        'between {min_msg_length} and '
                                                                                        '{max_msg_length} symbols.')
                                            .format(min_msg_length=format_number(self.settings['text_min'], self.language),
                                                    max_msg_length=format_number(self.settings['text_max'], self.language)),
                                            reply_to_message=message)
        else:
            report_botan(message, 'slave_message_empty')
            yield self.bot.send_message(pgettext('User sent empty message', 'Seriously??? 8===3'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    def multimedia_post_handler(self, message, pgettext):
        if message['chat']['type'] != 'private':
            return False  # Allow only in private

        if self.stages.get_id(message):
            return False

        if 'sticker' in message and self.settings['content_status']['sticker'] is False:
            yield self.bot.send_message(pgettext('User sent a sticker for verification while stickers are disabled',
                                                 'Accepting stickers is disabled'), reply_to_message=message)
            return
        elif 'audio' in message and self.settings['content_status']['audio'] is False:
            yield self.bot.send_message(pgettext('User sent an audio for verification while audios are disabled',
                                                 'Accepting audios is disabled'), reply_to_message=message)
            return
        elif 'voice' in message and self.settings['content_status']['voice'] is False:
            yield self.bot.send_message(pgettext('User sent a voice for verification while voices are disabled',
                                                 'Accepting voice is disabled'), reply_to_message=message)
            return
        elif 'video' in message and self.settings['content_status']['video'] is False:
            yield self.bot.send_message(pgettext('User sent a video for verification while videos are disabled',
                                                 'Accepting videos is disabled'), reply_to_message=message)
            return
        elif 'photo' in message and self.settings['content_status']['photo'] is False:
            yield self.bot.send_message(pgettext('User sent a photo for verification while photos are disabled',
                                                 'Accepting photos is disabled'), reply_to_message=message)
            return
        elif 'document' in message and self.settings['content_status']['document'] is False:
            yield self.bot.send_message(pgettext('User sent a document for verification while documents are disabled',
                                                 'Accepting documents is disabled'), reply_to_message=message)
            return

        report_botan(message, 'slave_message_multimedia')
        yield self._request_message_confirmation(message)

    @coroutine
    @append_pgettext
    def post_new_moderation_request(self, message, pgettext):
        yield self.bot.forward_message(self.moderator_chat_id, message['chat']['id'], message['message_id'])
        msg = pgettext('Verification message', 'Say {thumb_up_sign} ({vote_yes_cmd}) or {thumb_down} ({vote_no_cmd}) '
                                               'to this amazing message. Also you can just send a message to the user '
                                               '({reply_cmd}). Or even can BAN him ({ban_cmd}).') \
            .format(thumb_up_sign=Emoji.THUMBS_UP_SIGN, thumb_down=Emoji.THUMBS_DOWN_SIGN,
                    vote_yes_cmd='/vote_%s_%s_yes' % (message['chat']['id'], message['message_id']),
                    vote_no_cmd='/vote_%s_%s_no' % (message['chat']['id'], message['message_id']),
                    reply_cmd='/reply_%s_%s' % (message['chat']['id'], message['message_id']),
                    ban_cmd='/ban_%s' % (message['chat']['id'],))
        yield self.bot.send_message(msg, chat_id=self.moderator_chat_id)

        bot_info = yield self.bot.get_me()
        yield get_db().execute('UPDATE registered_bots SET last_moderation_message_at = NOW() WHERE id = %s',
                               (bot_info['id'],))

    @coroutine
    def __is_user_voted(self, user_id, original_chat_id, message_id):
        cur = yield get_db().execute('SELECT 1 FROM votes_history WHERE user_id = %s AND message_id = %s AND '
                                     'original_chat_id = %s',
                                     (user_id, message_id, original_chat_id))

        if cur.fetchone():
            return True

        return False

    @coroutine
    def __is_voting_opened(self, original_chat_id, message_id):
        cur = yield get_db().execute('SELECT is_voting_fail, is_published FROM incoming_messages WHERE id = %s AND '
                                     'original_chat_id = %s',
                                     (message_id, original_chat_id))
        row = cur.fetchone()
        if not row or (row[0] != row[1]):
            return False

        return True

    @coroutine
    @append_pgettext
    def __vote(self, user_id, message_id, original_chat_id, yes: bool, pgettext):
        voted = yield self.__is_user_voted(user_id, original_chat_id, message_id)
        opened = yield self.__is_voting_opened(original_chat_id, message_id)

        cur = yield get_db().execute('SELECT SUM(vote_yes::INT), COUNT(*) FROM votes_history WHERE message_id = %s AND '
                                     'original_chat_id = %s',
                                     (message_id, original_chat_id))
        current_yes, current_total = cur.fetchone()
        if not current_yes:
            current_yes = 0

        if not voted and opened:
            current_yes += int(yes)
            current_total += 1

            yield get_db().execute("""
                                   INSERT INTO votes_history (user_id, message_id, original_chat_id, vote_yes,
                                                              created_at)
                                   VALUES (%s, %s, %s, %s, NOW())
                                   """, (user_id, message_id, original_chat_id, yes))

            if current_yes >= self.settings.get('votes', 5):
                cur = yield get_db().execute('SELECT is_voting_success, message FROM incoming_messages WHERE id = %s '
                                             'AND original_chat_id = %s',
                                             (message_id, original_chat_id))
                row = cur.fetchone()
                if not row[0]:
                    yield get_db().execute('UPDATE incoming_messages SET is_voting_success = TRUE WHERE id = %s AND '
                                           'original_chat_id = %s',
                                           (message_id, original_chat_id))
                    try:
                        yield self.bot.send_message(pgettext('Message verified and queued for publishing',
                                                             'Your message was verified and queued for publishing.'),
                                                    chat_id=original_chat_id, reply_to_message_id=message_id)
                    except:
                        pass
                    report_botan(row[1], 'slave_verification_success')
            elif current_total - current_yes >= self.settings.get('votes', 5):
                cur = yield get_db().execute('SELECT is_voting_fail, is_voting_success, message FROM incoming_messages '
                                             'WHERE id = %s AND original_chat_id = %s', (message_id, original_chat_id))
                row = cur.fetchone()

                if row and not row[0] and not row[1]:
                    yield self.decline_message(row[2], current_yes)

    @coroutine
    def vote_yes(self, message):
        if message['chat']['id'] != self.moderator_chat_id:
            return False

        report_botan(message, 'slave_vote_yes')
        match = self.RE_VOTE_YES.match(message['text'])
        original_chat_id = match.group('chat_id')
        message_id = match.group('message_id')
        yield self.__vote(message['from']['id'], message_id, original_chat_id, True)

    @coroutine
    def vote_no(self, message):
        if message['chat']['id'] != self.moderator_chat_id:
            return False

        report_botan(message, 'slave_vote_no')
        match = self.RE_VOTE_NO.match(message['text'])
        original_chat_id = match.group('chat_id')
        message_id = match.group('message_id')
        yield self.__vote(message['from']['id'], message_id, original_chat_id, False)

    @coroutine
    @append_pgettext
    @append_npgettext
    def help_command(self, message, pgettext, npgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or chat_id == self.moderator_chat_id:
            report_botan(message, 'slave_help')
            delay_str = npgettext('Delay between channel messages', '%s minute', '%s minutes', self.settings['delay']) % \
                        self.settings['delay']
            timeout_str = npgettext('Voting timeout', '%s hour', '%s hours', self.settings['vote_timeout']) % \
                          self.settings['vote_timeout']
            power_state = 'yes' if self.settings.get('power') else 'no'
            power_state_str = pgettext('Moderator\'s ability to alter settings', power_state)
            msg = pgettext('/help command response', 'bot.help.response') \
                .format(current_delay_with_minutes=delay_str, current_votes_required=self.settings['votes'],
                        current_timeout_with_hours=timeout_str, thumb_up_sign=Emoji.THUMBS_UP_SIGN,
                        thumb_down_sign=Emoji.THUMBS_DOWN_SIGN, current_start_message=self.settings['start'],
                        power_state=power_state_str,
                        current_text_limit={'min': self.settings['text_min'], 'max': self.settings['text_max']})

            try:
                yield self.bot.send_message(msg, reply_to_message=message, parse_mode=Api.PARSE_MODE_MD)
            except:
                yield self.bot.send_message(msg, reply_to_message=message)
        else:
            return False

    @coroutine
    @append_pgettext
    def setdelay_command(self, message, pgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_setdelay_cmd')
            yield self.bot.send_message(pgettext('New delay request', 'Set new delay value for messages posting (in '
                                                                      'minutes)'),
                                        reply_to_message=message, reply_markup=ForceReply(True))
            self.stages.set(message, self.STAGE_WAIT_DELAY_VALUE)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    def plaintext_delay_handler(self, message, pgettext):
        if self.stages.get_id(message) == self.STAGE_WAIT_DELAY_VALUE:
            if message['text'].isdigit() and int(message['text']) >= 0:
                report_botan(message, 'slave_setdelay')
                yield self.__update_settings(delay=int(message['text']))
                yield self.bot.send_message(pgettext('Messages delay successfully changed', 'Delay value updated'),
                                            reply_to_message=message)
                self.stages.drop(message)
            else:
                report_botan(message, 'slave_setdelay_invalid')
                yield self.bot.send_message(pgettext('Invalid delay value. Try again or type /cancel'),
                                            reply_to_message=message,
                                            reply_markup=ForceReply(True))
        else:
            return False

    @coroutine
    @append_pgettext
    def setvotes_command(self, message, pgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_setvotes_cmd')
            yield self.bot.send_message(
                pgettext('New required votes count request', 'Set new amount of required votes'),
                reply_to_message=message, reply_markup=ForceReply(True))
            self.stages.set(message, self.STAGE_WAIT_VOTES_VALUE)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    def plaintext_votes_handler(self, message, pgettext):
        if self.stages.get_id(message) == self.STAGE_WAIT_VOTES_VALUE:
            if message['text'].isdigit() and int(message['text']) > 0:
                report_botan(message, 'slave_setvotes')
                yield self.__update_settings(votes=int(message['text']))
                yield self.bot.send_message(pgettext('Required votes count successfully changed', 'Required votes '
                                                                                                  'amount updated'),
                                            reply_to_message=message)
                self.stages.drop(message)
            else:
                report_botan(message, 'slave_setvotes_invalid')
                yield self.bot.send_message(pgettext('Invalid votes amount value. Try again or type /cancel'),
                                            reply_to_message=message, reply_markup=ForceReply(True))
        else:
            return False

    @coroutine
    @append_pgettext
    def settimeout_command(self, message, pgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_settimeout_cmd')
            yield self.bot.send_message(pgettext('New voting duration request', 'Set new voting duration value (in '
                                                                                'hours, only a digits)'),
                                        reply_to_message=message, reply_markup=ForceReply(True))
            self.stages.set(message, self.STAGE_WAIT_VOTE_TIMEOUT_VALUE)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    @append_npgettext
    def plaintext_timeout_handler(self, message, pgettext, npgettext):
        if self.stages.get_id(message) == self.STAGE_WAIT_VOTE_TIMEOUT_VALUE:
            if message['text'].isdigit() and int(message['text']) > 0:
                report_botan(message, 'slave_settimeout')
                yield self.__update_settings(vote_timeout=int(message['text']))
                yield self.bot.send_message(pgettext('Voting duration successfully changed', 'Voting duration updated'),
                                            reply_to_message=message)
                self.stages.drop(message)
            else:
                report_botan(message, 'slave_settimeout_invalid')
                yield self.bot.send_message(pgettext('Invalid voting duration value. Try again or type /cancel'),
                                            reply_to_message=message, reply_markup=ForceReply(True))
        else:
            return False

    @coroutine
    @append_pgettext
    def setstartmessage_command(self, message, pgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_setstartmessage_cmd')
            yield self.bot.send_message(pgettext('New start message request', 'Set new start message'),
                                        reply_to_message=message,
                                        reply_markup=ForceReply(True))
            self.stages.set(message, self.STAGE_WAIT_START_MESSAGE_VALUE)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    def plaintext_startmessage_handler(self, message, pgettext):
        if self.stages.get_id(message) == self.STAGE_WAIT_START_MESSAGE_VALUE:
            if message['text'] and len(message['text'].strip()) > 10:
                report_botan(message, 'slave_setstartmessage')
                yield self.__update_settings(start=message['text'].strip())
                yield self.bot.send_message(pgettext('Start message successfully changed', 'Start message updated'),
                                            reply_to_message=message)
                self.stages.drop(message)
            else:
                report_botan(message, 'slave_setstartmessage_invalid')
                yield self.bot.send_message(pgettext('Too short start message entered', 'Invalid start message, you '
                                                                                        'should write at least 10 '
                                                                                        'symbols. Try again or type '
                                                                                        '/cancel'),
                                            reply_to_message=message, reply_markup=ForceReply(True))
        else:
            return False

    @coroutine
    def __update_settings(self, **kwargs):
        if 'locale' in kwargs:
            self.locale = locale.get(kwargs['locale'])

        self.settings.update(kwargs)
        yield get_db().execute('UPDATE registered_bots SET settings = %s WHERE id = %s', (dumps(self.settings),
                                                                                          self.bot_id))

    @coroutine
    @append_pgettext
    def togglepower_command(self, message, pgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_togglepower_cmd')
            yield self.bot.send_chat_action(chat_id, Api.CHAT_ACTION_TYPING)
            if self.settings.get('power'):
                yield self.__update_settings(power=False)
                yield self.bot.send_message(pgettext('Power mode disabled', 'From now other chat users can not modify '
                                                                            'bot settings'),
                                            reply_to_message=message)
            else:
                yield self.__update_settings(power=True)
                yield self.bot.send_message(pgettext('Power mode enabled', 'From now other chat users can modify bot '
                                                                           'settings (only inside moderators chat)'),
                                            reply_to_message=message)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    @append_npgettext
    def stats_command(self, message, pgettext, npgettext):
        def format_top(rows, f: callable):
            ret = ''
            for row_id, row in enumerate(rows):
                user_id, first_name, last_name = row[:3]
                row = row[3:]
                if first_name and last_name:
                    user = first_name + ' ' + last_name
                elif first_name:
                    user = first_name
                else:
                    user = 'userid %s' % user_id

                ret += pgettext('Stats user item', '{row_id}. {user} - {rating_details}') \
                           .format(row_id=row_id + 1, user=user, rating_details=f(row)) + "\n"

            if not ret:
                ret = pgettext('No data for stats report', '{cross_mark} no data').format(
                    cross_mark=Emoji.CROSS_MARK) + "\n"

            return ret

        if message['from']['id'] == self.owner_id or message['chat']['id'] == self.moderator_chat_id:
            report_botan(message, 'slave_stats')

            period = message['text'][6:].strip()
            if period:
                if period.isdigit():
                    period_end = datetime.now()
                    period_begin = period_end - timedelta(days=int(period) - 1)
                elif ' ' in period and '-' in period:
                    period = period.split(' ')
                    try:
                        period_begin = datetime.strptime(period[0], '%Y-%m-%d')
                        period_end = datetime.strptime(period[1], '%Y-%m-%d')
                    except:
                        yield self.bot.send_message(pgettext('Invalid stats request', 'Invalid period provided, '
                                                                                      'correct value: `/stats '
                                                                                      '2016-01-01 2016-01-13`'),
                                                    reply_to_message=message, parse_mode=Api.PARSE_MODE_MD)
                        return
                elif '-' in period:
                    try:
                        period_begin = datetime.strptime(period, '%Y-%m-%d')
                        period_end = datetime.strptime(period, '%Y-%m-%d')
                    except:
                        yield self.bot.send_message(pgettext('Invalid stats request', 'Invalid period provided, '
                                                                                      'correct value: `/stats '
                                                                                      '2016-01-01`'),
                                                    reply_to_message=message, parse_mode=Api.PARSE_MODE_MD)
                        return
                else:
                    yield self.bot.send_message(pgettext('Invalid stats request', 'Invalid period provided, correct '
                                                                                  'values: `/stats 2016-01-01 '
                                                                                  '2016-01-13`, `/stats 5` for last 5 '
                                                                                  'days or `/stats 2016-01-01`'),
                                                reply_to_message=message, parse_mode=Api.PARSE_MODE_MD)
                    return
            else:
                period_end = datetime.now()
                period_begin = period_end - timedelta(days=6)

            period_begin = period_begin.replace(hour=0, minute=0, second=0)
            period_end = period_end.replace(hour=23, minute=59, second=59)

            yield self.bot.send_chat_action(message['chat']['id'], Api.CHAT_ACTION_TYPING)

            period_str = format_date(period_begin.date(), locale=self.language) \
                if period_begin.strftime('%Y-%m-%d') == period_end.strftime('%Y-%m-%d') \
                else '%s - %s' % (format_date(period_begin.date(), locale=self.language),
                                  format_date(period_end.date(), locale=self.language))

            msg = pgettext('Stats header', 'Stats for {period}').format(period=period_str) + "\n\n"
            msg += pgettext('TOP type', 'TOP5 voters:') + "\n"

            query = """
            SELECT vh.user_id, u.first_name, u.last_name, count(*), SUM(vote_yes::INT) FROM votes_history vh
            JOIN incoming_messages im ON im.id = vh.message_id AND im.original_chat_id = vh.original_chat_id
            LEFT JOIN users u ON u.user_id = vh.user_id AND u.bot_id = im.bot_id
            WHERE im.bot_id = %s AND vh.created_at BETWEEN %s AND %s
            GROUP BY vh.user_id, u.first_name, u.last_name
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """

            cur = yield get_db().execute(query, (self.bot_id, period_begin.strftime('%Y-%m-%d'),
                                                 period_end.strftime('%Y-%m-%d %H:%M:%S')))

            def format_top_votes(row):
                return npgettext('Votes count', '{votes_cnt} vote (with {votes_yes_cnt} {thumb_up_sign})',
                                 '{votes_cnt} votes (with {votes_yes_cnt} {thumb_up_sign})',
                                 row[0]).format(votes_cnt=format_number(row[0], self.language),
                                                votes_yes_cnt=format_number(row[1], self.language),
                                                thumb_up_sign=Emoji.THUMBS_UP_SIGN)

            msg += format_top(cur.fetchall(), format_top_votes) + "\n"

            msg += pgettext('TOP type', 'TOP5 users by messages count:') + "\n"

            query = """
            SELECT im.owner_id, u.first_name, u.last_name, count(*) FROM incoming_messages im
            LEFT JOIN users u ON u.user_id = im.owner_id AND u.bot_id = im.bot_id
            WHERE im.bot_id = %s AND im.created_at BETWEEN %s AND %s
            GROUP BY im.owner_id, u.first_name, u.last_name
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """

            cur = yield get_db().execute(query, (self.bot_id, period_begin.strftime('%Y-%m-%d'),
                                                 period_end.strftime('%Y-%m-%d %H:%M:%S')))

            def format_top_messages(row):
                return npgettext('Messages count', '{messages_cnt} message', '{messages_cnt} messages', row[0]) \
                    .format(messages_cnt=format_number(row[0], self.language))

            msg += format_top(cur.fetchall(), format_top_messages) + "\n"
            msg += pgettext('TOP type', 'TOP5 users by published messages count:') + "\n"

            query = """
            SELECT im.owner_id, u.first_name, u.last_name, count(*) FROM incoming_messages im
            LEFT JOIN users u ON u.user_id = im.owner_id AND u.bot_id = im.bot_id
            WHERE im.bot_id = %s AND im.created_at BETWEEN %s AND %s AND im.is_published = TRUE
            GROUP BY im.owner_id, u.first_name, u.last_name
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """

            cur = yield get_db().execute(query, (self.bot_id, period_begin.strftime('%Y-%m-%d'),
                                                 period_end.strftime('%Y-%m-%d %H:%M:%S')))

            msg += format_top(cur.fetchall(), format_top_messages) + "\n"
            msg += pgettext('TOP type', 'TOP5 users by declined messages count:') + "\n"

            query = """
            SELECT im.owner_id, u.first_name, u.last_name, count(*) FROM incoming_messages im
            LEFT JOIN users u ON u.user_id = im.owner_id AND u.bot_id = im.bot_id
            WHERE im.bot_id = %s AND im.created_at BETWEEN %s AND %s AND is_voting_fail = TRUE
            GROUP BY im.owner_id, u.first_name, u.last_name
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """

            cur = yield get_db().execute(query, (self.bot_id, period_begin.strftime('%Y-%m-%d'),
                                                 period_end.strftime('%Y-%m-%d %H:%M:%S')))

            msg += format_top(cur.fetchall(), format_top_messages)

            yield self.bot.send_message(msg, reply_to_message=message)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    def ban_command(self, message, pgettext):
        if message['chat']['id'] != self.moderator_chat_id:
            return False

        match = self.RE_BAN.match(message['text'])
        user_id = match.group('user_id')
        report_botan(message, 'slave_ban_cmd')
        yield self.bot.send_message(pgettext('Ban reason request', 'Please enter a ban reason for the user'),
                                    reply_to_message=message, reply_markup=ForceReply(True))
        self.stages.set(message, self.STAGE_WAIT_BAN_MESSAGE, ban_user_id=user_id)

    @coroutine
    @append_pgettext
    def plaintext_ban_handler(self, message, pgettext):
        chat_id = message['chat']['id']

        stage = self.stages.get(message)

        if stage[0] != self.STAGE_WAIT_BAN_MESSAGE:
            return False

        msg = message['text'].strip()
        if len(msg) < 5:
            report_botan(message, 'slave_ban_short_msg')
            yield self.bot.send_message(pgettext('Ban reason too short', 'Reason is too short (5 symbols required), '
                                                                         'try again or send /cancel'),
                                        reply_to_message=message, reply_markup=ForceReply(True))
        else:
            report_botan(message, 'slave_ban_success')
            yield self.bot.send_chat_action(chat_id, Api.CHAT_ACTION_TYPING)
            try:
                yield self.bot.send_message(pgettext('Message to user in case of ban',
                                                     "You've been banned from further communication with this bot. "
                                                     "Reason:\n> {ban_reason}").format(ban_reason=msg),
                                            chat_id=stage[1]['ban_user_id'])
            except:
                pass
            yield get_db().execute('UPDATE incoming_messages SET is_voting_fail = TRUE WHERE bot_id = %s AND '
                                   'owner_id = %s AND is_voting_success = FALSE',
                                   (self.bot_id, stage[1]['ban_user_id'],))
            yield get_db().execute('UPDATE users SET banned_at = NOW(), ban_reason = %s WHERE user_id = %s AND '
                                   'bot_id = %s', (msg, stage[1]['ban_user_id'], self.bot_id))
            yield self.bot.send_message(pgettext('Ban confirmation', 'User banned'), reply_to_message=message)

    @coroutine
    @append_pgettext
    def ban_list_command(self, message, pgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or chat_id == self.moderator_chat_id:
            report_botan(message, 'slave_ban_list_cmd')
            yield self.bot.send_chat_action(chat_id, Api.CHAT_ACTION_TYPING)
            cur = yield get_db().execute('SELECT user_id, first_name, last_name, username, banned_at, ban_reason '
                                         'FROM users WHERE bot_id = %s AND '
                                         'banned_at IS NOT NULL ORDER BY banned_at DESC', (self.bot_id,))

            msg = ''

            for row_id, (user_id, first_name, last_name, username, banned_at, ban_reason) in enumerate(cur.fetchall()):
                if first_name and last_name:
                    user = first_name + ' ' + last_name
                elif first_name:
                    user = first_name
                else:
                    user = 'userid %s' % user_id

                msg += pgettext('Ban user item', '{row_id}. {user} - {ban_reason} (banned {ban_date}) {unban_cmd}') \
                    .format(row_id=row_id + 1, user=user, ban_reason=ban_reason,
                            ban_date=banned_at.strftime('%Y-%m-%d'), unban_cmd='/unban_%s' % (user_id,))

            if msg:
                yield self.bot.send_message(msg, reply_to_message=message)
                if chat_id == self.owner_id:
                    yield self.bot.send_message(pgettext('Bot owner notification', 'You can use /unban command only '
                                                                                   'in moderators group'),
                                                reply_to_message=message)
            else:
                yield self.bot.send_message(pgettext('Ban list is empty', 'No banned users yet'),
                                            reply_to_message=message)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    def unban_command(self, message, pgettext):
        if message['chat']['id'] != self.moderator_chat_id:
            return False

        chat_id = message['chat']['id']
        report_botan(message, 'slave_unban_cmd')
        yield self.bot.send_chat_action(chat_id, Api.CHAT_ACTION_TYPING)
        match = self.RE_UNBAN.match(message['text'])
        user_id = match.group('user_id')
        yield get_db().execute('UPDATE users SET banned_at = NULL, ban_reason = NULL WHERE user_id = %s AND '
                               'bot_id = %s', (user_id, self.bot_id))
        yield self.bot.send_message(pgettext('Unban confirmation', 'User unbanned'), reply_to_message=message)
        try:
            yield self.bot.send_message(pgettext('User notification in case of unban', 'Access restored'),
                                        chat_id=user_id)
        except:
            pass

    @coroutine
    @append_pgettext
    def reply_command(self, message, pgettext):
        if message['chat']['id'] != self.moderator_chat_id:
            return False

        report_botan(message, 'slave_reply_cmd')
        match = self.RE_REPLY.match(message['text'])
        yield self.bot.send_message(pgettext('Reply message request', 'What message should I send to user?'),
                                    reply_to_message=message, reply_markup=ForceReply(True))
        self.stages.set(message, self.STAGE_WAIT_REPLY_MESSAGE, msg_id=match.group('message_id'),
                        msg_chat_id=match.group('chat_id'))

    @coroutine
    @append_pgettext
    def plaintext_reply_handler(self, message, pgettext):
        stage = self.stages.get(message)

        if stage[0] == self.STAGE_WAIT_REPLY_MESSAGE:
            msg = message['text'].strip()
            if len(msg) < 10:
                report_botan(message, 'slave_reply_short_msg')
                yield self.bot.send_message(pgettext('Reply message is too short', 'Message is too short (10 symbols '
                                                                                   'required), try again or send '
                                                                                   '/cancel'),
                                            reply_to_message=message, reply_markup=ForceReply(True))
            else:
                try:
                    yield self.bot.send_message(msg, chat_id=stage[1]['msg_chat_id'],
                                                reply_to_message_id=stage[1]['msg_id'])
                    yield self.bot.send_message(pgettext('Reply delivery confirmation', 'Message sent'),
                                                reply_to_message=message)
                except Exception as e:
                    yield self.bot.send_message(pgettext('Reply failed', 'Failed: {reason}').format(reason=str(e)),
                                                reply_to_message=message)

                self.stages.drop(message)
        else:
            return False

    @append_pgettext
    def build_contenttype_keyboard(self, pgettext):
        content_status = self.settings['content_status']
        text_enabled = content_status['text']
        photo_enabled = content_status['photo']
        video_enabled = content_status['video']
        voice_enabled = content_status['voice']
        audio_enabled = content_status['audio']
        doc_enabled = content_status['document']
        sticker_enabled = content_status['sticker']
        marks = {
            True: Emoji.CIRCLED_BULLET,
            False: Emoji.MEDIUM_SMALL_WHITE_CIRCLE,
        }
        return ReplyKeyboardMarkup([[
            KeyboardButton('%s %s' % (marks[text_enabled], pgettext('Content type', 'Text'))),
            KeyboardButton('%s %s' % (marks[photo_enabled], pgettext('Content type', 'Photo'))),
            KeyboardButton('%s %s' % (marks[video_enabled], pgettext('Content type', 'Video'))),
        ], [KeyboardButton('%s %s' % (marks[audio_enabled], pgettext('Content type', 'Audio'))),
            KeyboardButton('%s %s' % (marks[doc_enabled], pgettext('Content type', 'Document'))),
            KeyboardButton('%s %s' % (marks[sticker_enabled], pgettext('Content type', 'Sticker'))),
            ], [
            KeyboardButton('%s %s' % (marks[voice_enabled], pgettext('Content type', 'Voice'))),
        ], [KeyboardButton(Emoji.END_WITH_LEFTWARDS_ARROW_ABOVE)]], resize_keyboard=True, selective=True)

    @coroutine
    @append_pgettext
    def change_allowed_command(self, message, pgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_change_allowed_cmd')
            yield self.bot.send_message(pgettext('/changeallowed response', "You can see current status on keyboard, "
                                                                            "just click on content type to change it's "
                                                                            "status"), reply_to_message=message,
                                        reply_markup=self.build_contenttype_keyboard())
            self.stages.set(message, self.STAGE_WAIT_CONTENT_TYPE)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    def plaintext_cancel_emoji_handler(self, message):
        if message['text'] in (Emoji.END_WITH_LEFTWARDS_ARROW_ABOVE,):
            yield self.cancel_command(message)
            return

        return False

    @coroutine
    @append_pgettext
    def plaintext_contenttype_handler(self, message, pgettext):
        if self.stages.get_id(message) == self.STAGE_WAIT_CONTENT_TYPE:
            try:
                split = message['text'].split(' ')
                action_type, content_type = split[0], ' '.join(split[1:])

                if action_type == Emoji.MEDIUM_SMALL_WHITE_CIRCLE:
                    action_type = True
                elif action_type == Emoji.CIRCLED_BULLET:
                    action_type = False
                else:
                    raise ValueError()

                content_type = content_type[0].upper() + content_type[1:].lower()

                content_status = self.settings['content_status']

                content_types_list = {
                    pgettext('Content type', 'Text'): 'text',
                    pgettext('Content type', 'Photo'): 'photo',
                    pgettext('Content type', 'Video'): 'video',
                    pgettext('Content type', 'Audio'): 'audio',
                    pgettext('Content type', 'Voice'): 'voice',
                    pgettext('Content type', 'Sticker'): 'sticker',
                    pgettext('Content type', 'Document'): 'document',
                }

                if content_type in content_types_list:
                    content_type_raw = content_types_list[content_type]
                    content_status[content_type_raw] = action_type
                    yield self.__update_settings(content_status=content_status)
                else:
                    raise ValueError

                action_text = 'enable' if action_type else 'disable'

                report_botan(message, 'slave_content_' + content_type_raw + '_' + action_text)

                msg = content_type_raw[0].upper() + content_type_raw[1:] + 's ' + action_text + 'd'

                yield self.bot.send_message(pgettext('Content type enabled/disabled', msg), reply_to_message=message,
                                            reply_markup=self.build_contenttype_keyboard())
            except:
                yield self.bot.send_message(pgettext('Invalid user response', 'Wrong input'), reply_to_message=message)
                return
        else:
            return False

    @coroutine
    @append_pgettext
    def switchlang_command(self, message, pgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            keyboard_rows = []

            for row_id, languages in groupby(enumerate(self.LANGUAGE_LIST), lambda l: floor(l[0] / 4)):
                keyboard_rows.append([
                                         KeyboardButton(lang_name)
                                         for lang_idx, (lang_code, lang_name) in languages
                                         ])

            keyboard = ReplyKeyboardMarkup(keyboard_rows + [[KeyboardButton(Emoji.END_WITH_LEFTWARDS_ARROW_ABOVE)]],
                                           resize_keyboard=True, selective=True)
            yield self.bot.send_message(pgettext('Change language prompt', 'Select your language'),
                                        reply_to_message=message, reply_markup=keyboard)
            self.stages.set(message, self.STAGE_WAIT_LANGUAGE, do_not_validate=True)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    def plaintext_switchlang_handler(self, message, pgettext):
        if self.stages.get_id(message) == self.STAGE_WAIT_LANGUAGE:
            languages = {
                lang_name: lang_code
                for lang_code, lang_name in self.LANGUAGE_LIST
                }

            if message['text'] in languages:
                yield self.__update_settings(locale=languages[message['text']])
                pgettext = self.locale.pgettext
                yield self.bot.send_message(pgettext('Language changed', 'Language changed'),
                                            reply_to_message=message, reply_markup=ReplyKeyboardHide())
                self.stages.drop(message)
            else:
                yield self.bot.send_message(pgettext('Invalid user response', 'Wrong input'), reply_to_message=message)
        else:
            return False

    @property
    def language(self):
        return self.settings.get('locale', 'en_US')

    @coroutine
    @append_pgettext
    def settextlimits_command(self, message, pgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            yield self.bot.send_message(pgettext('New length limits request', 'Please enter new value for length '
                                                                              'limits formatted like '
                                                                              '`{min_length}..{max_length}` (e.g. '
                                                                              '`1..10`)'), reply_to_message=message,
                                        parse_mode=Api.PARSE_MODE_MD)
            self.stages.set(message, self.STAGE_WAIT_TEXT_LIMITS)
        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

    @coroutine
    @append_pgettext
    def plaintext_textlimits_handler(self, message, pgettext):
        if self.stages.get_id(message) == self.STAGE_WAIT_TEXT_LIMITS:
            limits = message['text'].strip().split('..')

            if len(limits) == 2 and limits[0].isdigit() and limits[1].isdigit():
                limits[0] = int(limits[0])
                limits[1] = int(limits[1])

                if limits[0] < 1:
                    yield self.bot.send_message(pgettext('Bottom limit is too low', 'Bottom limit must be greater than '
                                                                                    '0'),
                                                reply_to_message=message)
                elif limits[1] <= limits[0]:
                    yield self.bot.send_message(pgettext('Top limit is too low', 'Top limit must be greater than '
                                                                                 'bottom one'),
                                                reply_to_message=message)
                else:
                    yield self.__update_settings(text_min=limits[0], text_max=limits[1])
                    yield self.bot.send_message(pgettext('Text limits changed successfully', 'Limits updated'),
                                                reply_to_message=message)
                    self.stages.drop(message)
            else:
                yield self.bot.send_message(pgettext('Non-well formated text limits provided',
                                                     'Please use following format: `{min_length}..{max_length}` (e.g. '
                                                     '`1..10`), or send /cancel'), reply_to_message=message,
                                            parse_mode=Api.PARSE_MODE_MD)
        else:
            return False

    @coroutine
    @append_npgettext
    @append_pgettext
    def polls_list_command(self, message, pgettext, npgettext):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or chat_id == self.moderator_chat_id:
            cur = yield get_db().execute('SELECT message FROM incoming_messages WHERE is_voting_success = False AND '
                                         'is_voting_fail = False AND is_published = False AND bot_id = %s',
                                         (self.bot_id, ))

            pending = cur.fetchall()

            if len(pending):
                polls_cnt_msg = npgettext('Polls count', '%d poll', '%d polls', len(pending)) % len(pending)
                reply_part_one = pgettext('/pollslist reply message', 'There is {polls_msg} in progress:')\
                    .format(polls_msg=polls_cnt_msg)
                yield self.bot.send_message(reply_part_one, reply_to_message=message)

                for (message_to_moderate, ) in pending:
                    yield self.post_new_moderation_request(message_to_moderate)
            else:
                yield self.bot.send_message(pgettext('/pollslist reply on empty pending-polls list',
                                                     'There is no polls in progress.'),
                                            reply_to_message=message)

        else:
            yield self.bot.send_message(pgettext('User not allowed to perform this action', 'Access denied'),
                                        reply_to_message=message)

def __messages():
    pgettext('Moderator\'s ability to alter settings', 'yes')
    pgettext('Moderator\'s ability to alter settings', 'no')

    pgettext('Content type enabled/disabled', 'Texts enabled')
    pgettext('Content type enabled/disabled', 'Texts disabled')
    pgettext('Content type enabled/disabled', 'Photos enabled')
    pgettext('Content type enabled/disabled', 'Photos disabled')
    pgettext('Content type enabled/disabled', 'Videos enabled')
    pgettext('Content type enabled/disabled', 'Videos disabled')
    pgettext('Content type enabled/disabled', 'Audios enabled')
    pgettext('Content type enabled/disabled', 'Audios disabled')
    pgettext('Content type enabled/disabled', 'Voices enabled')
    pgettext('Content type enabled/disabled', 'Voices disabled')
    pgettext('Content type enabled/disabled', 'Stickers enabled')
    pgettext('Content type enabled/disabled', 'Stickers disabled')
