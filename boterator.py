import logging
import re
from datetime import datetime, timedelta
from time import time
from ujson import dumps, loads
from urllib.parse import urlencode

from tornado.gen import coroutine, sleep
from tornado.httpclient import AsyncHTTPClient
from tornado.ioloop import PeriodicCallback, IOLoop
from tornado.options import options

from globals import get_db
from telegram import Api


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


class BotMother:
    STAGE_WAITING_TOKEN = 1
    STAGE_MODERATION_GROUP = 2
    STAGE_WAITING_PUBLIC_CHANNEL = 3
    STAGE_REGISTERED = 4
    STAGE_WAITING_HELLO = 6

    def __init__(self, token):
        bot = Api(token)
        bot.add_handler(self.start_command, '/start')
        bot.add_handler(self.reg_command, '/reg')
        bot.add_handler(self.plaintext_token)
        bot.add_handler(self.cancel_command, '/cancel')
        bot.add_handler(self.change_hello_command, '/change_hello')
        bot.add_handler(self.plaintext_set_hello)
        bot.add_handler(self.plaintext_channel_name)
        self.bot = bot
        self.stages = StagesStorage()
        self.slaves = {}

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
                    yield self.bot.send_message(user_id, 'It seems like this bot is already registered. Try to crete another one')
                    return
                yield self.bot.send_message(user_id, 'Ok, I\'ve got basic information for @%s' % new_bot_me['username'])
                yield self.bot.send_message(user_id,
                                            'Now add him to a group of moderators (or copy and paste `@%s /attach` to the group, in '
                                            'case you’ve already added him), where I should send messages for verification, or type '
                                            '/cancel' % new_bot_me['username'],
                                            parse_mode=Api.PARSE_MODE_MD)

                hello_message = 'Hi there, guys! Now it is possible to publish messages in this channel by any of ' \
                                'you. All you need to do — is to write a message to me (bot named @%s), and it will ' \
                                'be published after verification by our team.' % new_bot_me['username']

                self.stages.set(user_id, self.STAGE_MODERATION_GROUP, token=token, bot_info=new_bot_me, hello=hello_message)
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
        yield self.bot.send_message(message['from']['id'], 'Oka-a-a-a-a-ay.')

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
                    yield new_bot.send_message(channel_name, stage[1]['hello'])
                    self.stages.set(user_id, self.STAGE_REGISTERED, channel=channel_name)
                    report_botan(message, 'boterator_channel')
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
                default_settings = {"delay": 15, "votes": 5, "vote_timeout": 24}
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
                                                     'settings send /help in PM to @%s. You’re the only user who can '
                                                     'change these settings and use /help command'
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
        yield self.bot.send_message(user_id, "Ok, I'll be sending moderation requests to %s %s\n"
                                             "Now you need to add your bot (@%s) to a channel as administrator and "
                                             "tell me the channel name (e.g. @mobilenewsru)\n"
                                             "As soon as I will receive the channel name I'll send a message with "
                                             "following text:\n> %s\n"
                                             "You can change the message, if you mind, just send me /change_hello"
                                    % (chat['type'], chat['title'], stage[1]['bot_info']['username'], stage[1]['hello']))
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
                self.stages.set(user_id, self.STAGE_WAITING_PUBLIC_CHANNEL, do_not_validate=True, hello=message['text'])
            else:
                report_botan(message, 'boterator_change_hello_short')
                yield self.bot.send_message(user_id, 'Hey, you should write at least 10 symbols')


class Slave:
    STAGE_ADDING_MESSAGE = 1

    STAGE_WAIT_DELAY_VALUE = 3

    STAGE_WAIT_VOTES_VALUE = 5

    STAGE_WAIT_VOTE_TIMEOUT_VALUE = 7

    RE_MATCH_YES = re.compile(r'/vote_(?P<chat_id>\d+)_(?P<message_id>\d+)_yes')
    RE_MATCH_NO = re.compile(r'/vote_(?P<chat_id>\d+)_(?P<message_id>\d+)_no')

    def __init__(self, token, m: BotMother, moderator_chat_id, channel_name, settings, owner_id, bot_id):
        bot = Api(token)
        bot.add_handler(self.confirm_command, '/confirm')
        bot.add_handler(self.start_command, '/start')
        bot.add_handler(self.cancel_command, '/cancel')
        bot.add_handler(self.help_command, '/help')
        bot.add_handler(self.setdelay_command, '/setdelay')
        bot.add_handler(self.setvotes_command, '/setvotes')
        bot.add_handler(self.settimeout_command, '/settimeout')
        bot.add_handler(self.attach_command, '/attach')
        bot.add_handler(self.plaintext_post_handler)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_AUDIO)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_VIDEO)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_PHOTO)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_VOICE)
        bot.add_handler(self.multimedia_post_handler, msg_type=Api.UPDATE_TYPE_MSG_DOC)
        bot.add_handler(self.plaintext_delay_handler)
        bot.add_handler(self.plaintext_votes_handler)
        bot.add_handler(self.plaintext_timeout_handler)
        bot.add_handler(self.vote_yes, self.RE_MATCH_YES)
        bot.add_handler(self.vote_no, self.RE_MATCH_NO)
        bot.add_handler(self.new_chat, msg_type=bot.UPDATE_TYPE_MSG_NEW_CHAT_MEMBER)
        bot.add_handler(self.left_chat, msg_type=bot.UPDATE_TYPE_MSG_LEFT_CHAT_MEMBER)
        self.bot = bot
        self.mother = m
        self.moderator_chat_id = moderator_chat_id
        self.channel_name = channel_name
        self.stages = StagesStorage()
        self.settings = settings
        self.owner_id = owner_id
        self.bot_id = bot_id

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
            report_botan(message, 'slave_validation_failed')
            yield self.bot.send_message(owner_id,
                                        'Unfortunately your message got only %s votes out of required %s and won’t be published to the channel.' % (votes, self.settings['votes']))

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
        yield self.bot.send_message(message['from']['id'], 'Just enter your message, and we\'re ready. '
                                                           'At this moment we do support only text messages.')

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
            yield self.post_new_moderation_request(stage[1]['message_id'], stage[1]['chat_id'], self.moderator_chat_id)
            self.stages.drop(user_id)
        else:
            yield self.bot.send_message(user_id, 'Invalid command')

    @coroutine
    def cancel_command(self, message):
        if message['from']['id'] != message['chat']['id']:
            return False  # Allow only in private

        report_botan(message, 'slave_cancel')
        self.stages.drop(message['from']['id'])
        yield self.bot.send_message(message['from']['id'], 'Oka-a-a-a-a-ay.')

    @coroutine
    def plaintext_post_handler(self, message):
        if message['from']['id'] != message['chat']['id']:
            return False  # Allow only in private

        user_id = message['from']['id']
        if self.stages.get_id(user_id):
            return False

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
        if message['from']['id'] != message['chat']['id']:
            return False  # Allow only in private

        user_id = message['from']['id']
        if self.stages.get_id(user_id):
            return False

        report_botan(message, 'slave_message_multimedia')

        yield self.bot.send_message(message['from']['id'], 'Looks good for me. Please, take a look on your message one more time.')
        yield self.bot.forward_message(message['from']['id'], message['chat']['id'], message['message_id'])
        yield self.bot.send_message(message['from']['id'], 'If everything is correct, type /confirm, otherwise — /cancel')
        self.stages.set(message['from']['id'], self.STAGE_ADDING_MESSAGE, chat_id=message['chat']['id'],
                        message_id=message['message_id'], message=message)

    @coroutine
    def post_new_moderation_request(self, message_id, original_chat_id, target_chat_id):
        yield self.bot.forward_message(target_chat_id, original_chat_id, message_id)
        yield self.bot.send_message(target_chat_id, 'Say YES (/vote_%s_%s_yes) or NO (/vote_%s_%s_no) to this amazing message.' % (original_chat_id, message_id, original_chat_id, message_id))
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
        voted = yield self.__is_user_voted(user_id, message_id, original_chat_id)
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
                    yield self.bot.send_message(row[1]['from']['id'], 'Your message was verified and queued for publishing.')
                    yield self.bot.forward_message(row[1]['from']['id'], original_chat_id, message_id)
                    report_botan(row[1], 'slave_validation_success')

    @coroutine
    def vote_yes(self, message):
        report_botan(message, 'slave_vote_yes')
        match = self.RE_MATCH_YES.match(message['text'])
        original_chat_id = match.group('chat_id')
        message_id = match.group('message_id')
        yield self.__vote(message['from']['id'], message_id, original_chat_id, True)

    @coroutine
    def vote_no(self, message):
        report_botan(message, 'slave_vote_no')
        match = self.RE_MATCH_NO.match(message['text'])
        original_chat_id = match.group('chat_id')
        message_id = match.group('message_id')
        yield self.__vote(message['from']['id'], message_id, original_chat_id, False)

    @coroutine
    def help_command(self, message):
        if message['chat']['id'] == self.owner_id:
            report_botan(message, 'slave_help')
            msg = """Bot owner's help:
/setdelay — change the delay between messages (current: %s minutes)
/setvotes — change required amount of yes-votes to publish a message (current: %s)
/settimeout — change voting duration (current: %s hours)
"""
            yield self.bot.send_message(message['chat']['id'], msg % (self.settings['delay'], self.settings['votes'],
                                                                      self.settings['vote_timeout']))
        else:
            return False

    @coroutine
    def setdelay_command(self, message):
        if message['chat']['id'] == self.owner_id:
            report_botan(message, 'slave_setdelay_cmd')
            yield self.bot.send_message(message['chat']['id'], 'Set new delay value for messages posting (in minutes)')
            self.stages.set(message['chat']['id'], self.STAGE_WAIT_DELAY_VALUE)
        else:
            return False

    @coroutine
    def plaintext_delay_handler(self, message):
        user_id = message['chat']['id']
        if self.stages.get_id(user_id) == self.STAGE_WAIT_DELAY_VALUE:
            if message['text'].isdigit():
                report_botan(message, 'slave_setdelay')
                self.settings['delay'] = int(message['text'])
                yield get_db().execute('UPDATE registered_bots SET settings = %s WHERE id = %s', (dumps(self.settings), self.bot_id))
                yield self.bot.send_message(user_id, 'Delay value updated to %s minutes' % self.settings['delay'])
                self.stages.drop(user_id)
            else:
                report_botan(message, 'slave_setdelay_invalid')
                yield self.bot.send_message(user_id, 'Invalid delay value. Try again or type /cancel')
        else:
            return False

    @coroutine
    def setvotes_command(self, message):
        if message['chat']['id'] == self.owner_id:
            report_botan(message, 'slave_setvotes_cmd')
            yield self.bot.send_message(message['chat']['id'], 'Set new amount of required votes.')
            self.stages.set(message['chat']['id'], self.STAGE_WAIT_VOTES_VALUE)
        else:
            return False

    @coroutine
    def plaintext_votes_handler(self, message):
        user_id = message['chat']['id']
        if self.stages.get_id(user_id) == self.STAGE_WAIT_VOTES_VALUE:
            if message['text'].isdigit():
                report_botan(message, 'slave_setvotes')
                self.settings['votes'] = int(message['text'])
                yield get_db().execute('UPDATE registered_bots SET settings = %s WHERE id = %s', (dumps(self.settings), self.bot_id))
                yield self.bot.send_message(user_id, 'Required votes amount updated to %s' % self.settings['votes'])
                self.stages.drop(user_id)
            else:
                report_botan(message, 'slave_setvotes_invalid')
                yield self.bot.send_message(user_id, 'Invalid votes amount value. Try again or type /cancel')
        else:
            return False

    @coroutine
    def settimeout_command(self, message):
        if message['chat']['id'] == self.owner_id:
            report_botan(message, 'slave_settimeout_cmd')
            yield self.bot.send_message(message['chat']['id'], 'Set new voting duration value (in hours, only a digits)')
            self.stages.set(message['chat']['id'], self.STAGE_WAIT_VOTE_TIMEOUT_VALUE)
        else:
            return False

    @coroutine
    def plaintext_timeout_handler(self, message):
        user_id = message['chat']['id']
        if self.stages.get_id(user_id) == self.STAGE_WAIT_VOTE_TIMEOUT_VALUE:
            if message['text'].isdigit():
                report_botan(message, 'slave_settimeout')
                self.settings['vote_timeout'] = int(message['text'])
                yield get_db().execute('UPDATE registered_bots SET settings = %s WHERE id = %s', (dumps(self.settings), self.bot_id))
                yield self.bot.send_message(user_id, 'Voting duration setting updated to %s hours' % self.settings['vote_timeout'])
                self.stages.drop(user_id)
            else:
                report_botan(message, 'slave_settimeout_invalid')
                yield self.bot.send_message(user_id, 'Invalid voting duration value. Try again or type /cancel')
        else:
            return False


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
