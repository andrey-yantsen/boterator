import logging
import re
from datetime import datetime, timedelta
from time import time
from ujson import dumps

from tornado.gen import coroutine, sleep
from tornado.ioloop import IOLoop

from emoji import Emoji
from globals import get_db
from telegram import Api, ForceReply, ReplyKeyboardHide, ReplyKeyboardMarkup, KeyboardButton

from helpers import report_botan, is_allowed_user, StagesStorage


class BotMother:
    STAGE_WAITING_TOKEN = 1
    STAGE_MODERATION_GROUP = 2
    STAGE_WAITING_PUBLIC_CHANNEL = 3
    STAGE_REGISTERED = 4
    STAGE_WAITING_HELLO = 6
    STAGE_WAITING_START_MESSAGE = 8

    def __init__(self, token):
        bot = Api(token)
        bot.add_handler(self.validate_user, False, Api.UPDATE_TYPE_MSG_ANY)
        bot.add_handler(self.start_command, '/start')
        bot.add_handler(self.reg_command, '/reg')
        bot.add_handler(self.plaintext_token)
        bot.add_handler(self.cancel_command, '/cancel')
        bot.add_handler(self.change_hello_command, '/change_hello')
        bot.add_handler(self.plaintext_set_hello)
        bot.add_handler(self.change_start_command, '/change_start')
        bot.add_handler(self.plaintext_set_start_message)
        bot.add_handler(self.plaintext_channel_name)
        self.bot = bot
        self.stages = StagesStorage()
        self.slaves = {}

    @coroutine
    def validate_user(self, message):
        bot_info = yield self.bot.get_me()
        allowed = is_allowed_user(message['from'], bot_info['id'])
        if allowed:
            return False

        yield self.bot.send_message(message['from']['id'], 'Access denied')

    @coroutine
    def start_command(self, message):
        report_botan(message, 'boterator_start')
        yield self.bot.send_message(message['from']['id'],
                                    'Hello, this is Boterator. In order to start ask @BotFather to create a new bot. '
                                    'Then feel free to use /reg command to register new bot using token.')

    @coroutine
    def reg_command(self, message):
        user_id = message['from']['id']
        if self.stages.get_id(user_id):
            yield self.bot.send_message(user_id, 'Another action is in progress, continue or /cancel')
            return

        report_botan(message, 'boterator_reg')

        yield self.bot.send_message(user_id, 'Ok, please tell me the token, which you\'ve received from @BotFather')
        self.stages.set(user_id, self.STAGE_WAITING_TOKEN)

    @coroutine
    def plaintext_token(self, message):
        user_id = message['from']['id']

        if self.stages.get_id(user_id) != self.STAGE_WAITING_TOKEN:
            return False

        token = message['text'].strip()
        if token == '':
            report_botan(message, 'boterator_token_empty')
            yield self.bot.send_message(user_id, 'I guess you forgot to enter the token :)')
        else:
            yield self.bot.send_chat_action(user_id, self.bot.CHAT_ACTION_TYPING)
            if len(token.split(':')) != 2:
                report_botan(message, 'boterator_token_invalid')
                yield self.bot.send_message(user_id, 'Token is incorrect. And I can do nothing with that.')
                return

            try:
                new_bot = Api(token)
                new_bot_me = yield new_bot.get_me()
                if new_bot_me['id'] in self.slaves:
                    report_botan(message, 'boterator_token_duplicate')
                    yield self.bot.send_message(user_id, 'It seems like this bot is already registered. Try to crete '
                                                         'another one')
                    return
                yield self.bot.send_message(user_id, 'Ok, I\'ve got basic information for @%s' % new_bot_me['username'])
                yield self.bot.send_message(user_id,
                                            'Now add him to a group of moderators (or copy and paste `@%s /attach` to '
                                            'the group, in case you’ve already added him), where I should send '
                                            'messages for verification, or type /cancel' % new_bot_me['username'],
                                            parse_mode=Api.PARSE_MODE_MD)

                hello_message = 'Hi there, guys! Now it is possible to publish messages in this channel by any of ' \
                                'you. All you need to do — is to write a message to me (bot named @%s), and it will ' \
                                'be published after verification by our team.' % new_bot_me['username']

                start_message = "Just enter your message, and we're ready."

                self.stages.set(user_id, self.STAGE_MODERATION_GROUP, token=token, bot_info=new_bot_me,
                                hello=hello_message, start_message=start_message)

                self.__wait_for_registration_complete(user_id)
                report_botan(message, 'boterator_token')
            except Exception as e:
                report_botan(message, 'boterator_token_failure')
                logging.exception(e)
                yield self.bot.send_message(user_id, 'Unable to get bot info: %s' % str(e))

    @coroutine
    def cancel_command(self, message):
        report_botan(message, 'boterator_cancel')
        self.stages.drop(message['from']['id'])
        self.stages.drop(message['chat']['id'])
        yield self.bot.send_message(message['chat']['id'], 'Oka-a-a-a-a-ay.')

    @coroutine
    def plaintext_channel_name(self, message):
        user_id = message['from']['id']
        stage = self.stages.get(user_id)
        if stage[0] == self.STAGE_WAITING_PUBLIC_CHANNEL:
            channel_name = message['text'].strip()
            if message['text'][0] != '@' or ' ' in channel_name:
                report_botan(message, 'boterator_channel_invalid')
                yield self.bot.send_message(user_id, 'Invalid channel name. Try again or type /cancel')
            else:
                try:
                    new_bot = Api(stage[1]['token'])
                    try:
                        yield new_bot.send_message(channel_name, stage[1]['hello'], parse_mode=Api.PARSE_MODE_MD)
                    except:
                        yield new_bot.send_message(channel_name, stage[1]['hello'])
                    self.stages.set(user_id, self.STAGE_REGISTERED, channel=channel_name)
                    report_botan(message, 'boterator_registered')
                except Exception as e:
                    report_botan(message, 'boterator_channel_failure')
                    yield self.bot.send_message(user_id, 'Hey, I\'m unable to send hello message, is everything ready '
                                                         'for me? Here is an error from Telegram api: %s' % str(e))
        else:
            return False

    @coroutine
    def listen(self):
        logging.info('Initializing slaves')
        self.slaves = dict()

        cur = yield get_db().execute('SELECT id, token, owner_id, moderator_chat_id, target_channel, settings FROM '
                                     'registered_bots WHERE active = True')

        for bot_id, token, owner_id, moderator_chat_id, target_channel, settings in cur.fetchall():
            slave = Slave(token, self, moderator_chat_id, target_channel, settings, owner_id, bot_id)
            try:
                yield slave.bot.get_me()
                slave.listen()
                self.slaves[bot_id] = slave
            except:
                logging.exception('Bot #%s failed', bot_id)
                yield get_db().execute('UPDATE registered_bots SET active = False WHERE id = %s', (bot_id, ))
                try:
                    yield self.bot.send_message(owner_id, 'I\'m failed to establish connection to your bot with token %s' % token)
                except:
                    pass

        logging.info('Waiting for commands')
        yield self.bot.wait_commands()
        logging.info('Mother termination')

    @coroutine
    def __wait_for_registration_complete(self, user_id, timeout=3600):
        stage = self.stages.get(user_id)
        slave = Slave(stage[1]['token'], self, None, None, {}, None, None)
        slave.listen()
        while True:
            stage_id, stage_meta, stage_begin = self.stages.get(user_id)

            if stage_id == self.STAGE_REGISTERED:
                default_settings = {"delay": 15, "votes": 5, "vote_timeout": 24, "start": stage_meta['start_message']}
                yield slave.stop()

                yield self.bot.send_chat_action(user_id, self.bot.CHAT_ACTION_TYPING)
                yield get_db().execute("""
                                      INSERT INTO registered_bots (id, token, owner_id, moderator_chat_id, target_channel, active, settings)
                                      VALUES (%s, %s, %s, %s, %s, True, %s)
                                      """, (stage_meta['bot_info']['id'], stage_meta['token'], user_id,
                                            stage_meta['moderation'], stage_meta['channel'], dumps(default_settings)))
                slave = Slave(stage_meta['token'], self, stage_meta['moderation'], stage_meta['channel'],
                              default_settings, user_id, stage_meta['bot_info']['id'])
                slave.listen()
                self.slaves[stage_meta['bot_info']['id']] = slave
                yield self.bot.send_message(user_id, "And we're ready for some magic!\n"
                                                     'By default the bot will wait for 5 votes to approve the message, '
                                                     'perform 15 minutes delay between channel messages and wait 24 '
                                                     'hours before closing a voting for each message. To modify this '
                                                     '(and few other) settings send /help in PM to @%s. By default '
                                                     'you’re the only user who can change these settings and use /help '
                                                     'command'
                                            % (stage_meta['bot_info']['username'], ))
                break
            elif time() - stage_begin >= timeout:
                yield slave.stop()
                try:
                    yield self.bot.send_message(user_id, '@%s registration aborted due to timeout' % stage_meta['bot_info']['username'])
                except:
                    pass
                break
            elif stage_id is None:
                # Action cancelled
                yield slave.stop()
                break

            yield sleep(0.05)

        self.stages.drop(user_id)

    @coroutine
    def complete_registration(self, user_id, chat: dict):
        self.stages.set(user_id, self.STAGE_REGISTERED, chat_info=chat)

    @coroutine
    def stop(self):
        for slave in self.slaves.values():
            yield slave.stop()
        yield self.bot.stop()

    @coroutine
    def set_slave_attached(self, user_id, chat):
        stage = self.stages.get(user_id)
        yield self.bot.send_chat_action(user_id, self.bot.CHAT_ACTION_TYPING)
        message = "Ok, I'll be sending moderation requests to %s %s\n" \
                  "Now you need to add your bot (@%s) to a channel as administrator and " \
                  "tell me the channel name (e.g. @mobilenewsru)\n" \
                  "As soon as I will receive the channel name I'll send a message with " \
                  "following text:\n> %s\n" \
                  "You can change the message, if you mind, just send me /change_hello.\n" \
                  "Also there is 'start' message for your new bot:\n> %s\n" \
                  "You can change it with /change_start" \
                  % (chat['type'], chat['title'], stage[1]['bot_info']['username'], stage[1]['hello'],
                     stage[1]['start_message'])

        try:
            yield self.bot.send_message(user_id, message, parse_mode=Api.PARSE_MODE_MD)
        except:
            yield self.bot.send_message(user_id, message)

        self.stages.set(user_id, self.STAGE_WAITING_PUBLIC_CHANNEL, moderation=chat['id'])

    @coroutine
    def change_hello_command(self, message):
        user_id = message['from']['id']
        if self.stages.get_id(user_id) != self.STAGE_WAITING_PUBLIC_CHANNEL:
            yield self.bot.send_message(user_id, 'It\'s not possible to change hello message on current step, sorry')
        else:
            report_botan(message, 'boterator_change_hello_cmd')
            yield self.bot.send_message(user_id, 'Ok, I\'m listening to you. How I should say hello to your subscribers?')
            self.stages.set(user_id, self.STAGE_WAITING_HELLO, do_not_validate=True)

    @coroutine
    def plaintext_set_hello(self, message):
        user_id = message['from']['id']
        if self.stages.get_id(user_id) != self.STAGE_WAITING_HELLO:
            return False
        else:
            text = message['text'].strip()
            if len(text) >= 10:
                report_botan(message, 'boterator_change_hello_success')
                yield self.bot.send_message(user_id, 'Ok, noted, now tell me the channel name')
                self.stages.set(user_id, self.STAGE_WAITING_PUBLIC_CHANNEL, do_not_validate=True, hello=text)
            else:
                report_botan(message, 'boterator_change_hello_short')
                yield self.bot.send_message(user_id, 'Hey, you should write at least 10 symbols')

    @coroutine
    def change_start_command(self, message):
        user_id = message['from']['id']
        if self.stages.get_id(user_id) != self.STAGE_WAITING_PUBLIC_CHANNEL:
            yield self.bot.send_message(user_id, 'It\'s not possible to change start message on current step, sorry')
        else:
            report_botan(message, 'boterator_change_start_cmd')
            yield self.bot.send_message(user_id, 'Ok, I\'m listening to you. How I should say hello to your authors?')
            self.stages.set(user_id, self.STAGE_WAITING_START_MESSAGE, do_not_validate=True)

    @coroutine
    def plaintext_set_start_message(self, message):
        user_id = message['from']['id']
        if self.stages.get_id(user_id) != self.STAGE_WAITING_START_MESSAGE:
            return False
        else:
            text = message['text'].strip()
            if len(text) >= 10:
                report_botan(message, 'boterator_change_start_success')
                yield self.bot.send_message(user_id, 'Ok, noted, now tell me the channel name')
                self.stages.set(user_id, self.STAGE_WAITING_PUBLIC_CHANNEL, do_not_validate=True, start_message=text)
            else:
                report_botan(message, 'boterator_change_start_short')
                yield self.bot.send_message(user_id, 'Hey, you should write at least 10 symbols')


class Slave:
    STAGE_ADDING_MESSAGE = 1

    STAGE_WAIT_DELAY_VALUE = 3

    STAGE_WAIT_VOTES_VALUE = 5

    STAGE_WAIT_VOTE_TIMEOUT_VALUE = 7

    STAGE_WAIT_START_MESSAGE_VALUE = 9

    STAGE_WAIT_BAN_MESSAGE = 11

    STAGE_WAIT_REPLY_MESSAGE = 13

    STAGE_WAIT_CONTENT_TYPE = 15

    RE_VOTE_YES = re.compile(r'/vote_(?P<chat_id>\d+)_(?P<message_id>\d+)_yes')
    RE_VOTE_NO = re.compile(r'/vote_(?P<chat_id>\d+)_(?P<message_id>\d+)_no')
    RE_BAN = re.compile(r'/ban_(?P<user_id>\d+)')
    RE_UNBAN = re.compile(r'/unban_(?P<user_id>\d+)')
    RE_REPLY = re.compile(r'/reply_(?P<chat_id>\d+)_(?P<message_id>\d+)')

    def __init__(self, token, m: BotMother, moderator_chat_id, channel_name, settings, owner_id, bot_id):
        bot = Api(token)
        bot.add_handler(self.validate_user, False, Api.UPDATE_TYPE_MSG_ANY)
        bot.add_handler(self.confirm_command, '/confirm')
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
        bot.add_handler(self.ban_list_command, '/ban_list')
        bot.add_handler(self.change_allowed_command, '/change_allowed')
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
        bot.add_handler(self.plaintext_startmessage_handler)
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

    @coroutine
    def validate_user(self, message):
        bot_info = yield self.bot.get_me()
        allowed = yield is_allowed_user(message['from'], bot_info['id'])
        if allowed:
            return False

        yield self.bot.send_message(message['from']['id'], 'Access denied')

    @coroutine
    def listen(self):
        IOLoop.current().add_callback(self.check_votes_success)
        IOLoop.current().add_callback(self.check_votes_failures)
        yield self.bot.wait_commands()
        logging.info('Slave termination')

    @coroutine
    def check_votes_success(self):
        cur = yield get_db().execute('SELECT last_channel_message_at FROM registered_bots WHERE id = %s', (self.bot_id, ))
        row = cur.fetchone()
        if row and row[0]:
            allowed_time = row[0] + timedelta(minutes=self.settings.get('delay', 15))
        else:
            allowed_time = datetime.now()

        if datetime.now() >= allowed_time:
            cur = yield get_db().execute('SELECT message FROM incoming_messages WHERE bot_id = %s '
                                         'AND is_voting_success = True and is_published = False '
                                         'ORDER BY created_at LIMIT 1', (self.bot_id, ))

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
            yield get_db().execute('UPDATE incoming_messages SET is_published = True WHERE id = %s AND original_chat_id = %s',
                                   (message['message_id'], message['chat']['id']))
            yield get_db().execute('UPDATE registered_bots SET last_channel_message_at = NOW() WHERE id = %s',
                                   (self.bot_id, ))
        except:
            logging.exception('Message forwarding failed (#%s from %s)', message['message_id'], message['chat']['id'])

    @coroutine
    def check_votes_failures(self):
        vote_timeout = datetime.now() - timedelta(hours=self.settings.get('vote_timeout', 24))
        cur = yield get_db().execute('SELECT owner_id, id, original_chat_id, message,'
                                     '(SELECT SUM(vote_yes::int) FROM votes_history vh WHERE vh.message_id = im.id AND vh.original_chat_id = im.original_chat_id)'
                               'FROM incoming_messages im WHERE bot_id = %s AND '
                               'is_voting_success = False AND is_voting_fail = False AND created_at <= %s', (self.bot_id, vote_timeout))

        for owner_id, message_id, chat_id, message, votes in cur.fetchall():
            report_botan(message, 'slave_verification_failed')
            try:
                yield self.bot.send_message(owner_id, 'Unfortunately your message got only %s votes out of required %s '
                                                      'and won’t be published to the channel.'
                                            % (votes, self.settings['votes']), reply_to_message_id=message_id)
            except:
                pass

        yield get_db().execute('UPDATE incoming_messages SET is_voting_fail = True WHERE bot_id = %s AND '
                               'is_voting_success = False AND is_voting_fail = False AND created_at <= %s', (self.bot_id, vote_timeout))
        if self.bot.consumption_state == Api.STATE_WORKING:
            IOLoop.current().add_timeout(timedelta(minutes=10), self.check_votes_failures)

    @coroutine
    def stop(self):
        yield self.bot.stop()

    @coroutine
    def start_command(self, message):
        report_botan(message, 'slave_start')
        try:
            yield self.bot.send_message(message['from']['id'], self.settings['start'], parse_mode=Api.PARSE_MODE_MD)
        except:
            yield self.bot.send_message(message['from']['id'], self.settings['start'])

    @coroutine
    def is_moderators_chat(self, chat_id, bot_id):
        ret = yield get_db().execute('SELECT 1 FROM registered_bots WHERE moderator_chat_id = %s', (chat_id, bot_id, ))
        return ret.fetchone() is not None

    @coroutine
    def new_chat(self, message):
        me = yield self.bot.get_me()

        if message['new_chat_member']['id'] == me['id']:
            known_chat = yield self.is_moderators_chat(message['chat']['id'], me['id'])
            if known_chat:
                yield self.bot.send_message(message['chat']['id'], 'Hi there, @%s!' % message['from']['username'])
            else:
                if self.mother.stages.get_id(message['from']['id']) == BotMother.STAGE_MODERATION_GROUP:
                    yield self.attach_command(message)
                else:
                    yield self.bot.send_message(message['from']['id'], 'This bot wasn\'t registered for %s %s, type /start for more info' % (message['chat']['type'], message['chat']['title']))
        else:
            return False

    @coroutine
    def group_created(self, message):
        if self.mother.stages.get_id(message['from']['id']) == BotMother.STAGE_MODERATION_GROUP:
            yield self.attach_command(message)
        else:
            yield self.bot.send_message(message['from']['id'], 'This bot wasn\'t registered for %s %s, type /start for more info' % (message['chat']['type'], message['chat']['title']))

    @coroutine
    def attach_command(self, message):
        user_id = message['from']['id']
        stage = self.mother.stages.get(user_id)
        report_botan(message, 'slave_attach')
        if stage[0] == BotMother.STAGE_MODERATION_GROUP:
            yield self.mother.set_slave_attached(user_id, message['chat'])
        else:
            yield self.bot.send_message(message['chat']['id'], 'Incorrect command')

    @coroutine
    def left_chat(self, message):
        me = yield self.bot.get_me()
        if message['left_chat_member']['id'] == me['id']:
            report_botan(message, 'slave_left_chat')
            yield self.bot.send_message(message['from']['id'], 'Whyyyy?! Remove bot ' + message['left_chat_member']['username'] + ' of ' + message['chat']['title'] + '  :\'(')
        else:
            return False

    @coroutine
    def confirm_command(self, message):
        if message['from']['id'] != message['chat']['id']:
            return False  # Allow only in private

        user_id = message['from']['id']
        stage = self.stages.get(user_id)
        if stage[0] == self.STAGE_ADDING_MESSAGE:
            report_botan(message, 'slave_confirm')
            yield self.bot.send_chat_action(user_id, Api.CHAT_ACTION_TYPING)
            bot_info = yield self.bot.get_me()
            yield get_db().execute("""
            INSERT INTO incoming_messages (id, original_chat_id, owner_id, bot_id, created_at, message)
            VALUES (%s, %s, %s, %s, NOW(), %s)
            """, (stage[1]['message_id'], stage[1]['chat_id'], user_id, bot_info['id'], dumps(stage[1]['message'])))
            yield self.bot.send_message(user_id, 'Okay, I\'ve sent your message for verification. Fingers crossed!')
            yield self.post_new_moderation_request(stage[1]['message'])
            self.stages.drop(user_id)
        else:
            yield self.bot.send_message(user_id, 'Invalid command')

    @coroutine
    def cancel_command(self, message):
        report_botan(message, 'slave_cancel')
        self.stages.drop(message['from']['id'])
        self.stages.drop(message['chat']['id'])
        yield self.bot.send_message(message['chat']['id'], 'Oka-a-a-a-a-ay.', reply_markup=ReplyKeyboardHide())

    @coroutine
    def plaintext_post_handler(self, message):
        if message['chat']['type'] != 'private':
            return False  # Allow only in private

        user_id = message['from']['id']
        if self.stages.get_id(user_id) or self.stages.get_id(message['chat']['id']):
            return False

        if self.settings.get('content_status', {}).get('text', True) is False:
            yield self.bot.send_message(message['chat']['id'], 'Accepting text messages is disabled')
            return

        mes = message['text']
        if mes.strip() != '':
            if 50 < len(mes) < 1000:
                yield self.bot.send_message(message['from']['id'], 'Looks good for me. Please, take a look on your message one more time.')
                yield self.bot.forward_message(message['from']['id'], message['chat']['id'], message['message_id'])
                yield self.bot.send_message(message['from']['id'], 'If everything is correct, type /confirm, otherwise — /cancel')
                self.stages.set(message['from']['id'], self.STAGE_ADDING_MESSAGE, chat_id=message['chat']['id'],
                                message_id=message['message_id'], message=message)
                report_botan(message, 'slave_message')
            else:
                report_botan(message, 'slave_message_invalid')
                yield self.bot.send_message(message['chat']['id'], 'Sorry, but we can proceed only messages with length between 50 and 1 000 symbols.')
        else:
            report_botan(message, 'slave_message_empty')
            yield self.bot.send_message(message['chat']['id'], 'Seriously??? 8===3')

    @coroutine
    def multimedia_post_handler(self, message):
        if message['chat']['type'] != 'private':
            return False  # Allow only in private

        user_id = message['from']['id']
        if self.stages.get_id(user_id) or self.stages.get_id(message['chat']['id']):
            return False

        report_botan(message, 'slave_message_multimedia')

        if 'sticker' in message and self.settings.get('content_status', {}).get('sticker', False) is False:
            yield self.bot.send_message(message['chat']['id'], 'Accepting stickers is disabled')
            return
        elif 'audio' in message and self.settings.get('content_status', {}).get('audio', True) is False:
            yield self.bot.send_message(message['chat']['id'], 'Accepting audios is disabled')
            return
        elif 'voice' in message and self.settings.get('content_status', {}).get('voice', True) is False:
            yield self.bot.send_message(message['chat']['id'], 'Accepting voice is disabled')
            return
        elif 'video' in message and self.settings.get('content_status', {}).get('video', True) is False:
            yield self.bot.send_message(message['chat']['id'], 'Accepting videos is disabled')
            return
        elif 'photo' in message and self.settings.get('content_status', {}).get('photo', True) is False:
            yield self.bot.send_message(message['chat']['id'], 'Accepting photos is disabled')
            return
        elif 'document' in message and self.settings.get('content_status', {}).get('document', True) is False:
            yield self.bot.send_message(message['chat']['id'], 'Accepting documents is disabled')
            return

        yield self.bot.send_message(message['from']['id'], 'Looks good for me. Please, take a look on your message one more time.')
        yield self.bot.forward_message(message['from']['id'], message['chat']['id'], message['message_id'])
        yield self.bot.send_message(message['from']['id'], 'If everything is correct, type /confirm, otherwise — /cancel')
        self.stages.set(message['from']['id'], self.STAGE_ADDING_MESSAGE, chat_id=message['chat']['id'],
                        message_id=message['message_id'], message=message)

    @coroutine
    def post_new_moderation_request(self, message):
        yield self.bot.forward_message(self.moderator_chat_id, message['chat']['id'], message['message_id'])
        yield self.bot.send_message(self.moderator_chat_id, 'Say %s (/vote_%s_%s_yes) or %s (/vote_%s_%s_no) to this '
                                                            'amazing message. Also you can just send a message to the '
                                                            'user (/reply_%s_%s). Or even can BAN him (/ban_%s).'
                                    % (Emoji.THUMBS_UP_SIGN, message['chat']['id'], message['message_id'],
                                       Emoji.THUMBS_DOWN_SIGN, message['chat']['id'], message['message_id'],
                                       message['chat']['id'], message['message_id'], message['from']['id']))

        bot_info = yield self.bot.get_me()
        yield get_db().execute('UPDATE registered_bots SET last_moderation_message_at = NOW() WHERE id = %s', (bot_info['id'], ))

    @coroutine
    def __is_user_voted(self, user_id, original_chat_id, message_id):
        cur = yield get_db().execute('SELECT 1 FROM votes_history WHERE user_id = %s AND message_id = %s AND original_chat_id = %s',
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
    def __vote(self, user_id, message_id, original_chat_id, yes: bool):
        voted = yield self.__is_user_voted(user_id, original_chat_id, message_id)
        opened = yield self.__is_voting_opened(original_chat_id, message_id)

        cur = yield get_db().execute('SELECT SUM(vote_yes::int) FROM votes_history WHERE message_id = %s AND original_chat_id = %s',
                                     (message_id, original_chat_id))
        current_yes = cur.fetchone()[0]
        if not current_yes:
            current_yes = 0

        if not voted and opened:
            current_yes += int(yes)

            yield get_db().execute("""
                                   INSERT INTO votes_history (user_id, message_id, original_chat_id, vote_yes, created_at)
                                   VALUES (%s, %s, %s, %s, NOW())
                                   """, (user_id, message_id, original_chat_id, yes))

            if current_yes >= self.settings.get('votes', 5):
                cur = yield get_db().execute('SELECT is_voting_success, message FROM incoming_messages WHERE id = %s AND original_chat_id = %s',
                                       (message_id, original_chat_id))
                row = cur.fetchone()
                if not row[0]:
                    yield get_db().execute('UPDATE incoming_messages SET is_voting_success = True WHERE id = %s AND original_chat_id = %s',
                                           (message_id, original_chat_id))
                    try:
                        yield self.bot.send_message(row[1]['from']['id'], 'Your message was verified and queued for '
                                                                          'publishing.', reply_to_message_id=message_id)
                    except:
                        pass
                    report_botan(row[1], 'slave_verification_success')

    @coroutine
    def vote_yes(self, message):
        report_botan(message, 'slave_vote_yes')
        match = self.RE_VOTE_YES.match(message['text'])
        original_chat_id = match.group('chat_id')
        message_id = match.group('message_id')
        yield self.__vote(message['from']['id'], message_id, original_chat_id, True)

    @coroutine
    def vote_no(self, message):
        report_botan(message, 'slave_vote_no')
        match = self.RE_VOTE_NO.match(message['text'])
        original_chat_id = match.group('chat_id')
        message_id = match.group('message_id')
        yield self.__vote(message['from']['id'], message_id, original_chat_id, False)

    @coroutine
    def help_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or chat_id == self.moderator_chat_id:
            report_botan(message, 'slave_help')
            msg = """Bot owner's help:
/setdelay — change the delay between messages (current: %s minutes)
/setvotes — change required amount of %s to publish a message (current: %s)
/settimeout — change voting duration (current: %s hours)
/setstartmessage — change start message (current: %s)
/togglepower — toggle moderators ability to modify settings (current: %s)
/stats — display some stats for last 7 days. You can customize period by calling:
   - `/stats 5` for last 5 days,
   - `/stats 2016-01-13` for one day (13th january in example)
   - `/stats 2016-01-01 2016-01-31` for custom interval (entire january in example)
/ban_list — list currently banned users
/change_allowed — change list of allowed content
"""
            yield self.bot.send_message(message['chat']['id'], msg % (self.settings['delay'], Emoji.THUMBS_UP_SIGN,
                                                                      self.settings['votes'],
                                                                      self.settings['vote_timeout'],
                                                                      self.settings['start'],
                                                                      'yes' if self.settings.get('power') else 'no'))
        else:
            return False

    @coroutine
    def setdelay_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_setdelay_cmd')
            yield self.bot.send_message(message['chat']['id'], 'Set new delay value for messages posting (in minutes)',
                                        reply_to_message_id=message['message_id'], reply_markup=ForceReply(True))
            self.stages.set(message['chat']['id'], self.STAGE_WAIT_DELAY_VALUE)
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def plaintext_delay_handler(self, message):
        chat_id = message['chat']['id']
        if self.stages.get_id(chat_id) == self.STAGE_WAIT_DELAY_VALUE and (message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id)):
            if message['text'].isdigit():
                report_botan(message, 'slave_setdelay')
                yield self.__update_settings(delay=int(message['text']))
                yield self.bot.send_message(chat_id, 'Delay value updated to %s minutes' % self.settings['delay'])
                self.stages.drop(chat_id)
            else:
                report_botan(message, 'slave_setdelay_invalid')
                yield self.bot.send_message(chat_id, 'Invalid delay value. Try again or type /cancel')
        else:
            return False

    @coroutine
    def setvotes_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_setvotes_cmd')
            yield self.bot.send_message(message['chat']['id'], 'Set new amount of required votes',
                                        reply_to_message_id=message['message_id'], reply_markup=ForceReply(True))
            self.stages.set(message['chat']['id'], self.STAGE_WAIT_VOTES_VALUE)
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def plaintext_votes_handler(self, message):
        chat_id = message['chat']['id']
        if self.stages.get_id(chat_id) == self.STAGE_WAIT_VOTES_VALUE and (message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id)):
            if message['text'].isdigit():
                report_botan(message, 'slave_setvotes')
                yield self.__update_settings(votes=int(message['text']))
                yield self.bot.send_message(chat_id, 'Required votes amount updated to %s' % self.settings['votes'])
                self.stages.drop(chat_id)
            else:
                report_botan(message, 'slave_setvotes_invalid')
                yield self.bot.send_message(chat_id, 'Invalid votes amount value. Try again or type /cancel')
        else:
            return False

    @coroutine
    def settimeout_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_settimeout_cmd')
            yield self.bot.send_message(message['chat']['id'], 'Set new voting duration value (in hours, only a digits)',
                                        reply_to_message_id=message['message_id'], reply_markup=ForceReply(True))
            self.stages.set(message['chat']['id'], self.STAGE_WAIT_VOTE_TIMEOUT_VALUE)
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def plaintext_timeout_handler(self, message):
        chat_id = message['chat']['id']
        if self.stages.get_id(chat_id) == self.STAGE_WAIT_VOTE_TIMEOUT_VALUE and (message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id)):
            if message['text'].isdigit():
                report_botan(message, 'slave_settimeout')
                yield self.__update_settings(vote_timeout=int(message['text']))
                yield self.bot.send_message(chat_id, 'Voting duration setting updated to %s hours' % self.settings['vote_timeout'])
                self.stages.drop(chat_id)
            else:
                report_botan(message, 'slave_settimeout_invalid')
                yield self.bot.send_message(chat_id, 'Invalid voting duration value. Try again or type /cancel')
        else:
            return False

    @coroutine
    def setstartmessage_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_setstartmessage_cmd')
            yield self.bot.send_message(chat_id, 'Set new start message', reply_to_message_id=message['message_id'],
                                        reply_markup=ForceReply(True))
            self.stages.set(chat_id, self.STAGE_WAIT_START_MESSAGE_VALUE)
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def plaintext_startmessage_handler(self, message):
        chat_id = message['chat']['id']
        if self.stages.get_id(chat_id) == self.STAGE_WAIT_START_MESSAGE_VALUE and (message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id)):
            if message['text'] and len(message['text'].strip()) > 10:
                report_botan(message, 'slave_setstartmessage')
                yield self.__update_settings(start=message['text'].strip())
                yield self.bot.send_message(chat_id, 'Start message changed to "%s"' % self.settings['start'])
                self.stages.drop(chat_id)
            else:
                report_botan(message, 'slave_setstartmessage_invalid')
                yield self.bot.send_message(chat_id, 'Invalid start message, you should write at least 10 symbols. Try '
                                                     'again or type /cancel')
        else:
            return False

    @coroutine
    def __update_settings(self, **kwargs):
        self.settings.update(kwargs)
        yield get_db().execute('UPDATE registered_bots SET settings = %s WHERE id = %s', (dumps(self.settings), self.bot_id))

    @coroutine
    def togglepower_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_togglepower_cmd')
            yield self.bot.send_chat_action(chat_id, Api.CHAT_ACTION_TYPING)
            if self.settings.get('power'):
                yield self.__update_settings(power=False)
                yield self.bot.send_message(chat_id, 'From now other chat users can not modify bot settings')
            else:
                yield self.__update_settings(power=True)
                yield self.bot.send_message(chat_id, 'From now other chat users can modify bot settings (only inside '
                                                     'moderators chat)')
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def stats_command(self, message):
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

                ret += "%d. %s — %s\n" % (row_id + 1, user, f(row))

            if not ret:
                ret = "%s no data\n" % Emoji.CROSS_MARK

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
                        yield self.bot.send_message(message['chat']['id'], 'Invalid period provided, correct value: '
                                                                           '`/stats 2016-01-01 2016-01-13`',
                                                    parse_mode=Api.PARSE_MODE_MD)
                        return
                elif '-' in period:
                    try:
                        period_begin = datetime.strptime(period, '%Y-%m-%d')
                        period_end = datetime.strptime(period, '%Y-%m-%d')
                    except:
                        yield self.bot.send_message(message['chat']['id'], 'Invalid period provided, correct value: '
                                                                           '`/stats 2016-01-01`',
                                                    parse_mode=Api.PARSE_MODE_MD)
                        return
                else:
                    yield self.bot.send_message(message['chat']['id'], 'Invalid period provided, correct values: '
                                                                       '`/stats 2016-01-01 2016-01-13`, `/stats 5` for '
                                                                       'last 5 days or `/stats 2016-01-01`',
                                                parse_mode=Api.PARSE_MODE_MD)
                    return
            else:
                period_end = datetime.now()
                period_begin = period_end - timedelta(days=6)

            period_begin = period_begin.replace(hour=0, minute=0, second=0)
            period_end = period_end.replace(hour=23, minute=59, second=59)

            yield self.bot.send_chat_action(message['chat']['id'], Api.CHAT_ACTION_TYPING)

            period_str = period_begin.strftime('%Y-%m-%d') \
                if period_begin.strftime('%Y-%m-%d') == period_end.strftime('%Y-%m-%d') \
                else '%s - %s' % (period_begin.strftime('%Y-%m-%d'), period_end.strftime('%Y-%m-%d'))

            msg = "Stats for %s\n\nTop5 voters:\n" % (period_str, )

            query = """
            SELECT vh.user_id, u.first_name, u.last_name, count(*), SUM(vote_yes::int) FROM votes_history vh
            JOIN incoming_messages im ON im.id = vh.message_id AND im.original_chat_id = vh.original_chat_id
            LEFT JOIN users u ON u.user_id = vh.user_id AND u.bot_id = im.bot_id
            WHERE im.bot_id = %s AND vh.created_at BETWEEN %s AND %s
            GROUP BY vh.user_id, u.first_name, u.last_name
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """

            cur = yield get_db().execute(query, (self.bot_id, period_begin.strftime('%Y-%m-%d'),
                                                 period_end.strftime('%Y-%m-%d %H:%M:%S')))

            msg += format_top(cur.fetchall(), lambda row: '%d votes (with %d %s)' % (row[0], row[1], Emoji.THUMBS_UP_SIGN))

            msg += "\nTop5 users by messages count:\n"

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

            msg += format_top(cur.fetchall(), lambda row: '%d messages' % (row[0], ))

            msg += "\nTop5 users by published messages count:\n"

            query = """
            SELECT im.owner_id, u.first_name, u.last_name, count(*) FROM incoming_messages im
            LEFT JOIN users u ON u.user_id = im.owner_id AND u.bot_id = im.bot_id
            WHERE im.bot_id = %s AND im.created_at BETWEEN %s AND %s AND im.is_published = True
            GROUP BY im.owner_id, u.first_name, u.last_name
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """

            cur = yield get_db().execute(query, (self.bot_id, period_begin.strftime('%Y-%m-%d'),
                                                 period_end.strftime('%Y-%m-%d %H:%M:%S')))

            msg += format_top(cur.fetchall(), lambda row: '%d messages' % (row[0]))

            msg += "\nTop5 users by declined messages count:\n"

            query = """
            SELECT im.owner_id, u.first_name, u.last_name, count(*) FROM incoming_messages im
            LEFT JOIN users u ON u.user_id = im.owner_id AND u.bot_id = im.bot_id
            WHERE im.bot_id = %s AND im.created_at BETWEEN %s AND %s AND is_voting_fail = True
            GROUP BY im.owner_id, u.first_name, u.last_name
            ORDER BY COUNT(*) DESC
            LIMIT 5
            """

            cur = yield get_db().execute(query, (self.bot_id, period_begin.strftime('%Y-%m-%d'),
                                                 period_end.strftime('%Y-%m-%d %H:%M:%S')))

            msg += format_top(cur.fetchall(), lambda row: '%d messages' % (row[0], ))

            yield self.bot.send_message(message['chat']['id'], msg)
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def ban_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            match = self.RE_BAN.match(message['text'])
            user_id = match.group('user_id')
            report_botan(message, 'slave_ban_cmd')
            yield self.bot.send_message(chat_id, 'Please enter a ban reason for the user',
                                        reply_to_message_id=message['message_id'], reply_markup=ForceReply(True))
            self.stages.set(chat_id, self.STAGE_WAIT_BAN_MESSAGE, ban_user_id=user_id)
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def plaintext_ban_handler(self, message):
        chat_id = message['chat']['id']

        stage = self.stages.get(chat_id)

        if stage[0] != self.STAGE_WAIT_BAN_MESSAGE:
            return False

        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            msg = message['text'].strip()
            if len(msg) < 5:
                report_botan(message, 'slave_ban_short_msg')
                yield self.bot.send_message(chat_id, 'Reason is too short (5 symbols required), try again or send '
                                                     '/cancel', reply_to_message_id=message['message_id'],
                                            reply_markup=ForceReply(True))
            else:
                report_botan(message, 'slave_ban_success')
                yield self.bot.send_chat_action(chat_id, Api.CHAT_ACTION_TYPING)
                try:
                    yield self.bot.send_message(stage[1]['ban_user_id'], "You've been banned from further "
                                                                         "communication with this bot. Reason:\n> %s" % msg)
                except:
                    pass
                yield get_db().execute('UPDATE incoming_messages SET is_voting_fail = True WHERE bot_id = %s AND '
                                       'owner_id = %s AND is_voting_success = False', (self.bot_id, stage[1]['ban_user_id'], ))
                yield get_db().execute('UPDATE users SET banned_at = NOW(), ban_reason = %s WHERE user_id = %s AND '
                                       'bot_id = %s', (msg, stage[1]['ban_user_id'], self.bot_id))
                yield self.bot.send_message(chat_id, 'User banned', reply_to_message_id=message['message_id'])
        else:
            return False

    @coroutine
    def ban_list_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_ban_list_cmd')
            yield self.bot.send_chat_action(chat_id, Api.CHAT_ACTION_TYPING)
            cur = yield get_db().execute('SELECT user_id, first_name, last_name, username, banned_at, ban_reason '
                                         'FROM users WHERE bot_id = %s AND '
                                         'banned_at IS NOT NULL ORDER BY banned_at DESC', (self.bot_id, ))

            msg = ''

            for row_id, (user_id, first_name, last_name, username, banned_at, ban_reason) in enumerate(cur.fetchall()):
                if first_name and last_name:
                    user = first_name + ' ' + last_name
                elif first_name:
                    user = first_name
                else:
                    user = 'userid %s' % user_id

                msg += "%d. %s — %s (banned %s) /unban_%d\n" % (row_id + 1, user, ban_reason,
                                                                banned_at.strftime('%Y-%m-%d'), user_id)

            if msg:
                yield self.bot.send_message(chat_id, msg)
            else:
                yield self.bot.send_message(chat_id, 'No banned users yet')
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def unban_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_unban_cmd')
            yield self.bot.send_chat_action(chat_id, Api.CHAT_ACTION_TYPING)
            match = self.RE_UNBAN.match(message['text'])
            user_id = match.group('user_id')
            yield get_db().execute('UPDATE users SET banned_at = NULL, ban_reason = NULL WHERE user_id = %s AND '
                                   'bot_id = %s', (user_id, self.bot_id))
            yield self.bot.send_message(chat_id, 'User unbanned', reply_to_message_id=message['message_id'])
            try:
                yield self.bot.send_message(user_id, 'Access restored')
            except:
                pass
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def reply_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_reply_cmd')
            match = self.RE_REPLY.match(message['text'])
            yield self.bot.send_message(chat_id, 'What message should I send to user?',
                                        reply_to_message_id=message['message_id'], reply_markup=ForceReply(True))
            self.stages.set(message['from']['id'], self.STAGE_WAIT_REPLY_MESSAGE, msg_id=match.group('message_id'),
                            msg_chat_id=match.group('chat_id'))
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def plaintext_reply_handler(self, message):
        chat_id = message['chat']['id']
        user_id = message['from']['id']

        stage = self.stages.get(user_id)

        if stage[0] == self.STAGE_WAIT_REPLY_MESSAGE:
            msg = message['text'].strip()
            if len(msg) < 10:
                report_botan(message, 'slave_reply_short_msg')
                yield self.bot.send_message(chat_id, 'Message is too short (10 symbols required), try again or send '
                                                     '/cancel', reply_to_message_id=message['message_id'],
                                            reply_markup=ForceReply(True))
            else:
                try:
                    yield self.bot.send_message(stage[1]['msg_chat_id'], msg, reply_to_message_id=stage[1]['msg_id'])
                    yield self.bot.send_message(chat_id, 'Message sent', reply_to_message_id=message['message_id'])
                except Exception as e:
                    yield self.bot.send_message(chat_id, 'Failed: %s' % e, reply_to_message_id=message['message_id'])
        else:
            return False

    def build_contenttype_keyboard(self):
        content_status = self.settings.get('content_status', {})
        text_enabled = content_status.get('text', True)
        photo_enabled = content_status.get('photo', True)
        video_enabled = content_status.get('video', True)
        voice_enabled = content_status.get('voice', True)
        audio_enabled = content_status.get('audio', True)
        doc_enabled = content_status.get('document', True)
        sticker_enabled = content_status.get('sticker', False)
        marks = {
            True: Emoji.CIRCLED_BULLET,
            False: Emoji.MEDIUM_SMALL_WHITE_CIRCLE,
        }
        return ReplyKeyboardMarkup([[
            KeyboardButton('%s Text' % marks[text_enabled]),
            KeyboardButton('%s Photo' % marks[photo_enabled]),
            KeyboardButton('%s Video' % marks[video_enabled]),
            KeyboardButton('%s Voice' % marks[voice_enabled]),
        ], [KeyboardButton('%s Audio' % marks[audio_enabled]),
            KeyboardButton('%s Document' % marks[doc_enabled]),
            KeyboardButton('%s Sticker' % marks[sticker_enabled]),
        ], [KeyboardButton(Emoji.BACK_WITH_LEFTWARDS_ARROW_ABOVE)]], resize_keyboard=True, selective=True)

    @coroutine
    def change_allowed_command(self, message):
        chat_id = message['chat']['id']
        if message['from']['id'] == self.owner_id or (self.settings.get('power') and chat_id == self.moderator_chat_id):
            report_botan(message, 'slave_change_allowed_cmd')
            yield self.bot.send_message(chat_id, "You can see current status on keyboard, just click on content type "
                                                 "to change it's status", reply_to_message_id=message['message_id'],
                                        reply_markup=self.build_contenttype_keyboard())
            self.stages.set(message['from']['id'], self.STAGE_WAIT_CONTENT_TYPE)
        else:
            yield self.bot.send_message(message['chat']['id'], 'Access denied')

    @coroutine
    def plaintext_cancel_emoji_handler(self, message):
        if message['text'] == Emoji.BACK_WITH_LEFTWARDS_ARROW_ABOVE:
            yield self.cancel_command(message)
            return

        return False

    @coroutine
    def plaintext_contenttype_handler(self, message):
        if self.stages.get_id(message['from']['id']) == self.STAGE_WAIT_CONTENT_TYPE:
            try:
                action_type, content_type = message['text'].split(' ')
                if action_type == Emoji.MEDIUM_SMALL_WHITE_CIRCLE:
                    action_type = True
                elif action_type == Emoji.CIRCLED_BULLET:
                    action_type = False
                else:
                    raise ValueError()

                content_type = content_type.lower()

                content_status = self.settings.get('content_status', {})

                if content_type in ('text', 'photo', 'video', 'audio', 'voice', 'sticker', 'document'):
                    content_status[content_type] = action_type
                    yield self.__update_settings(content_status=content_status)
                else:
                    raise ValueError

                action_text = 'enable' if action_type else 'disable'

                report_botan(message, 'slave_content_' + content_type + '_' + action_text)

                msg = content_type[0].upper() + content_type[1:] + 's ' + action_text + 'd'

                yield self.bot.send_message(message['chat']['id'], msg, reply_to_message_id=message['message_id'],
                                            reply_markup=self.build_contenttype_keyboard())
            except:
                yield self.bot.send_message(message['chat']['id'], 'Wrong input')
                return
        else:
            return False
