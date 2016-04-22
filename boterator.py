import logging
from time import time

from tornado.gen import coroutine, sleep
from tornado.ioloop import PeriodicCallback

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
        yield self.bot.send_message(message['from']['id'], 'Hello, this is Boterator. Start -> go @BotFather and create new bot')

    @coroutine
    def reg_command(self, message):
        user_id = message['from']['id']
        if self.stages.get_id(user_id):
            yield self.bot.send_message(user_id, 'Another action is in progress, continue or /cancel')
            return

        token = message['text'][5:].strip()
        if token == '':
            yield self.bot.send_message(user_id, 'Start -> go @BotFather and create new bot')
        else:
            yield self.bot.send_chat_action(user_id, self.bot.CHAT_ACTION_TYPING)
            if len(token.split(':')) != 2:
                yield self.bot.send_message(user_id, 'Incorrect token value')
                return

            try:
                new_bot = Api(token)
                new_bot_me = yield new_bot.get_me()
                if new_bot_me['id'] in self.slaves:
                    yield self.bot.send_message(user_id, 'Bot is already registered, make another one')
                    return
                yield self.bot.send_message(user_id, 'Ok, I\'ve stored basic info for %s' % new_bot_me['username'])
                yield self.bot.send_message(user_id,
                                            'Now add him to a group (or paste `@%s /attach` in the group, in case of '
                                            'it\'s already there), where I should send articles for moderation, or type '
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
        yield self.bot.send_message(message['from']['id'], 'Action cancelled')

    @coroutine
    def plaintext_channel_name(self, message):
        user_id = message['from']['id']
        if self.stages.get_id(user_id) == self.STAGE_PUBLIC_CHANNEL:
            channel_name = message['text'].strip()
            if message['text'][0] != '@' or ' ' in channel_name:
                yield self.bot.send_message(user_id, 'Invalid channel name. Try again on type /cancel')
            else:
                self.stages.set(user_id, self.STAGE_REGISTERED, channel=channel_name)
        else:
            return False

    @coroutine
    def listen(self):
        logging.info('Initializing slaves')
        self.slaves = dict()

        cur = yield get_db().execute('SELECT id, token, owner_id, moderator_chat_id, target_channel FROM registered_bots WHERE active = True')

        for bot_id, token, owner_id, moderator_chat_id, target_channel in cur.fetchall():
            slave = Slave(token, self, moderator_chat_id, target_channel)
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

    @coroutine
    def __wait_for_registration_complete(self, user_id, timeout=3600):
        stage = self.stages.get(user_id)
        slave = Slave(stage[1]['token'], self, None, None)
        slave.listen()
        while True:
            stage_id, stage_meta, stage_begin = self.stages.get(user_id)

            if stage_id == self.STAGE_REGISTERED:
                yield slave.stop()

                yield self.bot.send_chat_action(user_id, self.bot.CHAT_ACTION_TYPING)
                yield get_db().execute("""
                                      INSERT INTO registered_bots (id, token, owner_id, moderator_chat_id, target_channel, active, settings)
                                      VALUES (%s, %s, %s, %s, %s, True, '{"delay": 15, "votes": 1}')
                                      """, (stage_meta['bot_info']['id'], stage_meta['token'], user_id, stage_meta['moderation'], stage_meta['channel']))
                slave = Slave(stage_meta['token'], self, stage_meta['moderation'], stage_meta['channel'])
                slave.listen()
                self.slaves[stage_meta['bot_info']['id']] = slave
                yield self.bot.send_message(user_id, 'And we\'re ready for some magic!')
                yield self.bot.send_message(user_id, 'By default the bot will wait for 5 votes for the article and '
                                                     'perform 15 minutes delay between channel posts. We\'re unable to '
                                                     'change it right now, sorry')
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

    def __init__(self, token, m: BotMother, moderator_chat_id, channel_name):
        bot = Api(token)
        bot.add_handler(self.confirm_command, '/confirm')
        bot.add_handler(self.start_command, '/start')
        bot.add_handler(self.cancel_command, '/cancel')
        bot.add_handler(self.plaintext_handler)
        bot.add_handler(self.new_chat, msg_type=bot.MSG_NEW_CHAT_MEMBER)
        bot.add_handler(self.left_chat, msg_type=bot.MSG_LEFT_CHAT_MEMBER)
        self.bot = bot
        self.mother = m
        self.moderator_chat_id = moderator_chat_id
        self.channel_name = channel_name
        self.stages = StagesStorage()

    @coroutine
    def listen(self):
        yield self.bot.wait_commands()
        logging.info('Termination')

    @coroutine
    def stop(self):
        yield self.bot.stop()

    @coroutine
    def start_command(self, message):
        yield self.bot.send_message(message['from']['id'], 'Just enter your post, and we\'re ready')

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
            yield self.mother.bot.send_message(user_id, 'Now you need to add your bot (@%s) to a channel as admin and tell me the channel name (e.g. @mobilenewsru)' % (stage[1]['bot_info']['username'], ))
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
            yield self.bot.send_message(user_id, 'Okay, I\'ve saved your message and soon it will be sent for moderation')
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
    def plaintext_handler(self, message):
        if message['from']['id'] != message['chat']['id']:
            return False  # Allow only in private

        user_id = message['from']['id']
        if self.stages.get_id(user_id):
            yield self.bot.send_message(user_id, 'You already doing some shit, maybe you would like to /cancel it?')
            return

        mes = message['text']
        if mes.strip() != '':
            if 120 < len(mes) < 1000:
                yield self.bot.send_message(message['from']['id'], 'Looks good for me. Please, take a look on your post one more time.')
                yield self.bot.forward_message(message['from']['id'], message['chat']['id'], message['message_id'])
                yield self.bot.send_message(message['from']['id'], 'If everything looks ok for you - type /confirm, otherwise - /cancel')
                self.stages.set(message['from']['id'], self.STAGE_ADDING_MESSAGE, chat_id=message['chat']['id'],
                                message_id=message['message_id'])
            else:
                yield self.bot.send_message(message['chat']['id'], 'Stop! Your post more 1000 or less 150')
        else:
            yield self.bot.send_message(message['chat']['id'], 'Seriously??? 8===3')

    @coroutine
    def post_new_moderation_request(self, message_id, original_chat_id, target_chat_id):
        yield self.bot.forward_message(target_chat_id, original_chat_id, message_id)
        yield self.bot.send_message(target_chat_id, 'Type /vote_%s_yes or /vote_%s_no to vote for or against this message' % (message_id, message_id))


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
