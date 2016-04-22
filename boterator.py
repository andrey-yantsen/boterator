import logging
import re
from datetime import datetime, timedelta
from time import time
from ujson import dumps

from tornado.gen import coroutine, sleep
from tornado.ioloop import PeriodicCallback, IOLoop

from globals import get_db
from telegram import Api


class BotMother:
    STAGE_MODERATION_GROUP = 1
    STAGE_PUBLIC_CHANNEL = 2
    STAGE_REGISTERED = 3

    STAGE_WAITING_VOTES = 4

    STAGE_WAITING_DELAY = 5

    def __init__(self, token):
        bot = Api(token)
        bot.add_handler(self.start_command, '/start')
        bot.add_handler(self.reg_command, '/reg')
        bot.add_handler(self.cancel_command, '/cancel')
        bot.add_handler(self.plaintext_channel_name)
        self.bot = bot
        self.stages = StagesStorage()
        self.slaves = {}

    @coroutine
    def start_command(self, message):
        yield self.bot.send_message(message['from']['id'],
                                    'Hello, this is Boterator. In order to start ask @BotFather to create a new bot. '
                                    'Then feel free to use /reg command to register new bot using token.')

    @coroutine
    def reg_command(self, message):
        user_id = message['from']['id']
        if self.stages.get_id(user_id):
            yield self.bot.send_message(user_id, 'Another action is in progress, continue or /cancel')
            return

        token = message['text'][5:].strip()
        if token == '':
            yield self.bot.send_message(user_id, 'I guess you forgot to enter the token :)')
        else:
            yield self.bot.send_chat_action(user_id, self.bot.CHAT_ACTION_TYPING)
            if len(token.split(':')) != 2:
                yield self.bot.send_message(user_id, 'Token is incorrect. And I can do nothing with that.')
                return

            try:
                new_bot = Api(token)
                new_bot_me = yield new_bot.get_me()
                if new_bot_me['id'] in self.slaves:
                    yield self.bot.send_message(user_id, 'It seems like this bot is already registered. Try to crete another one')
                    return
                yield self.bot.send_message(user_id, 'Ok, I\'ve got basic information for %s' % new_bot_me['username'])
                yield self.bot.send_message(user_id,
                                            'Now add him to a group of moderators (or copy and paste `@%s /attach` to the group, in '
                                            'case you’ve already added him), where I should send messages for verification, or type '
                                            '/cancel' % new_bot_me['username'],
                                            parse_mode=Api.PARSE_MODE_MD)
                self.stages.set(user_id, self.STAGE_MODERATION_GROUP, token=token, bot_info=new_bot_me)
                self.__wait_for_registration_complete(user_id)
            except Exception as e:
                logging.exception(e)
                yield self.bot.send_message(user_id, 'Unable to get bot info: %s' % str(e))

    @coroutine
    def cancel_command(self, message):
        self.stages.drop(message['from']['id'])
        yield self.bot.send_message(message['from']['id'], 'Oka-a-a-a-a-ay.')

    @coroutine
    def plaintext_channel_name(self, message):
        user_id = message['from']['id']
        if self.stages.get_id(user_id) == self.STAGE_PUBLIC_CHANNEL:
            channel_name = message['text'].strip()
            if message['text'][0] != '@' or ' ' in channel_name:
                yield self.bot.send_message(user_id, 'Invalid channel name. Try again or type /cancel')
            else:
                self.stages.set(user_id, self.STAGE_REGISTERED, channel=channel_name)
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
                yield self.bot.send_message(user_id, 'And we\'re ready for some magic!')
                yield self.bot.send_message(user_id, 'By default the bot will wait for 5 votes to approve the message, perform 15 minutes delay '
                                                     'between channel messages and wait 24 hours before closing a voting for each message. To '
                                                     'modify this settings send /help in PM to @%s. You’re '
                                                     'the only user who can change these settings and use /help command' % (stage_meta['bot_info']['username'], ))
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
        bot.add_handler(self.plaintext_post_handler)
        bot.add_handler(self.plaintext_delay_handler)
        bot.add_handler(self.plaintext_votes_handler)
        bot.add_handler(self.plaintext_timeout_handler)
        bot.add_handler(self.vote_yes, self.RE_MATCH_YES)
        bot.add_handler(self.vote_no, self.RE_MATCH_NO)
        bot.add_handler(self.new_chat, msg_type=bot.MSG_NEW_CHAT_MEMBER)
        bot.add_handler(self.left_chat, msg_type=bot.MSG_LEFT_CHAT_MEMBER)
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
        allowed_time = datetime.now() - timedelta(minutes=self.settings.get('delay', 15))
        if not row[0] or row[0] >= allowed_time:
            cur = yield get_db().execute('SELECT id, original_chat_id FROM incoming_messages WHERE bot_id = %s '
                                         'AND is_voting_success = True and is_published = False '
                                         'ORDER BY created_at LIMIT 1', (self.bot_id, ))

            row = cur.fetchone()

            if row:
                try:
                    yield self.bot.forward_message(self.channel_name, row[1], row[0])
                    yield get_db().execute('UPDATE incoming_messages SET is_published = True WHERE id = %s AND original_chat_id = %s',
                                           (row[0], row[1]))
                except:
                    logging.exception('Message forwarding failed (#%s from %s)', row[0], row[1])

        if self.bot.consumption_state == Api.STATE_WORKING:
            IOLoop.current().add_timeout(timedelta(minutes=1), self.check_votes_success)

    @coroutine
    def check_votes_failures(self):
        vote_timeout = datetime.now() - timedelta(hours=self.settings.get('vote_timeout', 24))
        cur = yield get_db().execute('SELECT owner_id, id, original_chat_id, (SELECT SUM(vote_yes::int) FROM votes_history vh WHERE vh.message_id = im.id AND vh.original_chat_id = im.original_chat_id)'
                               'FROM incoming_messages im WHERE bot_id = %s AND '
                               'is_voting_success = False AND is_voting_fail = False AND created_at <= %s', (self.bot_id, vote_timeout))

        for owner_id, message_id, chat_id, votes in cur.fetchall():
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
        yield self.bot.send_message(message['from']['id'], 'Just enter your message, and we\'re ready. '
                                                           'At this moment we do support only text messages.')

    @coroutine
    def is_moderators_chat(self, chat_id):
        ret = yield get_db().execute('SELECT 1 FROM registered_bots WHERE moderator_chat_id = %s', (chat_id, ))
        return ret.fetchone() is not None

    @coroutine
    def new_chat(self, message):
        me = yield self.bot.get_me()

        if message['new_chat_member']['id'] == me['id']:
            known_chat = yield self.is_moderators_chat(message['chat']['id'])
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
        if stage[0] == BotMother.STAGE_MODERATION_GROUP:
            yield self.mother.bot.send_chat_action(user_id, self.bot.CHAT_ACTION_TYPING)
            yield self.mother.bot.send_message(user_id, 'Ok, I\'ll be sending moderation requests to %s %s' % (message['chat']['type'], message['chat']['title']))
            yield self.mother.bot.send_message(user_id, 'Now you need to add your bot (@%s) to a channel as administrator and tell me the channel name (e.g. @mobilenewsru)' % (stage[1]['bot_info']['username'], ))
            self.mother.stages.set(user_id, BotMother.STAGE_PUBLIC_CHANNEL, moderation=message['chat']['id'])
        else:
            yield self.bot.send_message(message['chat']['id'], 'Incorrect command')

    @coroutine
    def left_chat(self, message):
        me = yield self.bot.get_me()
        if message['left_chat_member']['id'] == me['id']:
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
            self.bot.send_chat_action(user_id, Api.CHAT_ACTION_TYPING)
            bot_info = yield self.bot.get_me()
            yield get_db().execute("""
            INSERT INTO incoming_messages (id, original_chat_id, owner_id, bot_id, created_at, is_voting_fail, is_published)
            VALUES (%s, %s, %s, %s, NOW(), False, False)
            """, (stage[1]['message_id'], stage[1]['chat_id'], user_id, bot_info['id']))
            yield self.bot.send_message(user_id, 'Okay, I\'ve sent your message for verification. Fingers crossed!')
            yield self.post_new_moderation_request(stage[1]['message_id'], stage[1]['chat_id'], self.moderator_chat_id)
            self.stages.drop(user_id)
        else:
            yield self.bot.send_message(user_id, 'Invalid command')

    @coroutine
    def cancel_command(self, message):
        if message['from']['id'] != message['chat']['id']:
            return False  # Allow only in private

        self.stages.drop(message['from']['id'])
        yield self.bot.send_message(message['from']['id'], 'Action cancelled')

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
                yield self.bot.send_message(message['from']['id'], 'If everything is correct, type /confirm, otherwise - /cancel')
                self.stages.set(message['from']['id'], self.STAGE_ADDING_MESSAGE, chat_id=message['chat']['id'],
                                message_id=message['message_id'])
            else:
                yield self.bot.send_message(message['chat']['id'], 'Sorry, but we can proceed only messages with length between 50 and 1 000 symbols.')
        else:
            yield self.bot.send_message(message['chat']['id'], 'Seriously??? 8===3')

    @coroutine
    def post_new_moderation_request(self, message_id, original_chat_id, target_chat_id):
        yield self.bot.forward_message(target_chat_id, original_chat_id, message_id)
        yield self.bot.send_message(target_chat_id, 'Type /vote_%s_%s_yes or /vote_%s_%s_no to vote for or against this message' % (original_chat_id, message_id, original_chat_id, message_id))
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
                cur = yield get_db().execute('SELECT is_voting_success, owner_id FROM incoming_messages WHERE id = %s AND original_chat_id = %s',
                                       (message_id, original_chat_id))
                row = cur.fetchone()
                if not row[0]:
                    yield get_db().execute('UPDATE incoming_messages SET is_voting_success = True WHERE id = %s AND original_chat_id = %s',
                                           (message_id, original_chat_id))
                    yield self.bot.send_message(row[1], 'Your message was verified and queued for publishing.')
                    yield self.bot.forward_message(row[1], original_chat_id, message_id)

    @coroutine
    def vote_yes(self, message):
        match = self.RE_MATCH_YES.match(message['text'])
        original_chat_id = match.group('chat_id')
        message_id = match.group('message_id')
        yield self.__vote(message['from']['id'], message_id, original_chat_id, True)

    @coroutine
    def vote_no(self, message):
        match = self.RE_MATCH_NO.match(message['text'])
        original_chat_id = match.group('chat_id')
        message_id = match.group('message_id')
        yield self.__vote(message['from']['id'], message_id, original_chat_id, False)

    @coroutine
    def help_command(self, message):
        if message['chat']['id'] == self.owner_id:
            msg = """Bot owner's help:
/setdelay — change the delay between messages (current: %s minutes)
/setvotes — change required amount of :+1:-votes to publish a message (current: %s)
/settimeout — change voting duration (current: %s hours)
"""
            yield self.bot.send_message(message['chat']['id'], msg % (self.settings['delay'], self.settings['votes'],
                                                                      self.settings['vote_timeout']), Api.PARSE_MODE_MD)
        else:
            return False

    @coroutine
    def setdelay_command(self, message):
        if message['chat']['id'] == self.owner_id:
            yield self.bot.send_message(message['chat']['id'], 'Set new delay value for messages posting (in minutes)')
            self.stages.set(message['chat']['id'], self.STAGE_WAIT_DELAY_VALUE)
        else:
            return False

    @coroutine
    def plaintext_delay_handler(self, message):
        user_id = message['chat']['id']
        if self.stages.get_id(user_id) == self.STAGE_WAIT_DELAY_VALUE:
            if message['text'].isdigit():
                self.settings['delay'] = int(message['text'])
                yield get_db().execute('UPDATE registered_bots SET settings = %s WHERE id = %s', (dumps(self.settings), self.bot_id))
                yield self.bot.send_message(user_id, 'Delay value updated to %s minutes' % self.settings['delay'])
                self.stages.drop(user_id)
            else:
                yield self.bot.send_message(user_id, 'Invalid delay value. Try again or type /cancel')
        else:
            return False

    @coroutine
    def setvotes_command(self, message):
        if message['chat']['id'] == self.owner_id:
            yield self.bot.send_message(message['chat']['id'], 'Set new amount of required votes.')
            self.stages.set(message['chat']['id'], self.STAGE_WAIT_VOTES_VALUE)
        else:
            return False

    @coroutine
    def plaintext_votes_handler(self, message):
        user_id = message['chat']['id']
        if self.stages.get_id(user_id) == self.STAGE_WAIT_VOTES_VALUE:
            if message['text'].isdigit():
                self.settings['votes'] = int(message['text'])
                yield get_db().execute('UPDATE registered_bots SET settings = %s WHERE id = %s', (dumps(self.settings), self.bot_id))
                yield self.bot.send_message(user_id, 'Required votes amount updated to %s' % self.settings['votes'])
                self.stages.drop(user_id)
            else:
                yield self.bot.send_message(user_id, 'Invalid votes amount value. Try again or type /cancel')
        else:
            return False

    @coroutine
    def settimeout_command(self, message):
        if message['chat']['id'] == self.owner_id:
            yield self.bot.send_message(message['chat']['id'], 'Set new voting duration value (in hours, only a digits)')
            self.stages.set(message['chat']['id'], self.STAGE_WAIT_VOTE_TIMEOUT_VALUE)
        else:
            return False

    @coroutine
    def plaintext_timeout_handler(self, message):
        user_id = message['chat']['id']
        if self.stages.get_id(user_id) == self.STAGE_WAIT_VOTE_TIMEOUT_VALUE:
            if message['text'].isdigit():
                self.settings['vote_timeout'] = int(message['text'])
                yield get_db().execute('UPDATE registered_bots SET settings = %s WHERE id = %s', (dumps(self.settings), self.bot_id))
                yield self.bot.send_message(user_id, 'Voting duration setting updated to %s hours' % self.settings['vote_timeout'])
                self.stages.drop(user_id)
            else:
                yield self.bot.send_message(user_id, 'Invalid voting duration value. Try again or type /cancel')
        else:
            return False


class StagesStorage:
    def __init__(self, ttl=7200):
        self.stages = {}
        self.ttl = ttl
        self.cleaner = PeriodicCallback(self.drop_expired, 600)
        self.cleaner.start()

    def set(self, user_id, stage_id, **kwargs):
        if user_id not in self.stages:
            self.stages[user_id] = {'meta': {}, 'code': 0}

        assert self.stages[user_id]['code'] == 0 or stage_id == self.stages[user_id]['code'] + 1

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
