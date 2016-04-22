import logging
from time import time

from tornado.gen import coroutine, sleep

from globals import get_db
from telegram import Api


class Moderator:
    STAGE_MODERATION_GROUP = 1
    STAGE_PUBLIC_CHANNEL = 2
    STAGE_REGISTERED = 3

    def __init__(self, token):
        bot = Api(token)
        bot.add_handler(self.start_command, '/start')
        bot.add_handler(self.reg_command, '/reg')
        bot.add_handler(self.cancel_command, '/cancel')
        bot.add_handler(self.attach_command, '/attach')
        bot.add_handler(self.plaintext_channel_name)
        bot.add_handler(self.new_chat, msg_type=bot.MSG_NEW_CHAT_MEMBER)
        bot.add_handler(self.left_chat, msg_type=bot.MSG_LEFT_CHAT_MEMBER)
        self.bot = bot
        self.stages = {}

    def set_stage(self, user_id, stage_id, **kwargs):
        if user_id not in self.stages:
            self.stages[user_id] = {'meta': {}, 'code': 0}

        assert self.stages[user_id]['code'] == 0 or stage_id == self.stages[user_id]['code'] + 1

        self.stages[user_id]['code'] = stage_id
        self.stages[user_id]['meta'].update(kwargs)
        self.stages[user_id]['timestamp'] = time()

    def get_stage_info(self, user_id):
        if user_id in self.stages:
            return self.stages[user_id]['code'], self.stages[user_id]['meta'], self.stages[user_id]['timestamp']

        return None, {}, 0

    def get_stage_id(self, user_id):
        return self.get_stage_info(user_id)[0]

    def drop_stage(self, user_id):
        ret = self.get_stage_info(user_id)
        if ret[0] is not None:
            del self.stages[user_id]

    @coroutine
    def start_command(self, message):
        yield self.bot.send_message(message['from']['id'], 'Hello, this is Boterator. Start -> go @BotFather and create new bot')

    @coroutine
    def reg_command(self, message):
        if self.get_stage_info(message['from']['id'])[0]:
            yield self.bot.send_message(message['from']['id'], 'Another action is in progress, continue or /cancel')
            return

        token = message['text'][5:].strip()
        if token == '':
            yield self.bot.send_message(message['from']['id'], 'Start -> go @BotFather and create new bot')
        else:
            yield self.bot.send_chat_action(message['from']['id'], self.bot.CHAT_ACTION_TYPING)
            if len(token.split(':')) != 2:
                yield self.bot.send_message(message['from']['id'], 'Incorrect token value')
                return

            try:
                new_bot = Api(token)
                new_bot_me = yield new_bot.get_me()
                me = yield self.bot.get_me()
                yield self.bot.send_message(message['from']['id'], 'Ok, I`ve stored basic info for %s' % new_bot_me['username'])
                yield self.bot.send_message(message['from']['id'],
                                            'Now add me to a group (or paste `@%s /attach` in the group), where I should send articles for moderation, or type /cancel' % me['username'],
                                            parse_mode=Api.PARSE_MODE_MD)
                self.set_stage(message['chat']['id'], self.STAGE_MODERATION_GROUP, token=token, bot_info=new_bot_me)
                self.__wait_for_registration_complete(message['from']['id'])
            except Exception as e:
                logging.exception(e)
                yield self.bot.send_message(message['from']['id'], 'Unable to get bot info: %s' % str(e))

    @coroutine
    def cancel_command(self, message):
        if message['from']['id'] in self.stages:
            del self.stages[message['from']['id']]
        yield self.bot.send_message(message['from']['id'], 'Action cancelled')

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
                if self.get_stage_id(message['from']['id']) == self.STAGE_MODERATION_GROUP:
                    yield self.attach_command(message)
                else:
                    yield self.bot.send_message(message['from']['id'], 'This bot wasn`t registered for %s %s, type /start for more info' % (message['chat']['type'], message['chat']['title']))
        else:
            return False

    @coroutine
    def attach_command(self, message):
        user_id = message['from']['id']
        stage = self.get_stage_info(user_id)
        if stage[0] == self.STAGE_MODERATION_GROUP:
            yield self.bot.send_chat_action(user_id, self.bot.CHAT_ACTION_TYPING)
            yield self.bot.send_message(user_id, 'Ok, I`ll be sending moderation requests to %s %s' % (message['chat']['type'], message['chat']['title']))
            yield self.bot.send_message(user_id, 'Now you need to add your bot (@%s) to a channel as admin and tell me the channel name (e.g. @mobilenewsru)' % (stage[1]['bot_info']['username'], ))
            self.set_stage(user_id, self.STAGE_PUBLIC_CHANNEL, moderation=message['chat']['id'])
        else:
            yield self.bot.send_message(message['from']['id'], 'Incorrect command')

    @coroutine
    def plaintext_channel_name(self, message):
        user_id = message['from']['id']
        if self.get_stage_id(user_id) == self.STAGE_PUBLIC_CHANNEL:
            channel_name = message['text'].strip()
            if message['text'][0] != '@' or ' ' in channel_name:
                yield self.bot.send_message(user_id, 'Invalid channel name. Try again on type /cancel')
            else:
                self.set_stage(user_id, self.STAGE_REGISTERED, channel=channel_name)
        else:
            return False

    @coroutine
    def left_chat(self, message):
        me = yield self.bot.get_me()
        if message['left_chat_member']['id'] == me['id']:
            yield self.bot.send_message(message['from']['id'], 'Whyyyy?! Remove bot ' + message['left_chat_member']['username'] + ' of ' + message['chat']['title'] + '  :\'(')
        else:
            return False

    @coroutine
    def listen(self):
        yield self.bot.wait_commands()

    @coroutine
    def __wait_for_registration_complete(self, user_id, timeout=3600):
        while True:
            stage_id, stage_meta, stage_begin = self.get_stage_info(user_id)

            if stage_id == self.STAGE_REGISTERED:
                yield self.bot.send_chat_action(user_id, self.bot.CHAT_ACTION_TYPING)
                yield get_db().execute("""
                                      INSERT INTO registered_bots (id, owner_id, moderator_chat_id, target_channel, active)
                                      VALUES (%s, %s, %s, %s, True)
                                      """, (stage_meta['bot_info']['id'], user_id, stage_meta['moderation'], stage_meta['channel']))
                yield self.bot.send_message(user_id, 'And we`re ready for some magic!')
                break
            elif time() - stage_begin >= timeout:
                try:
                    yield self.bot.send_message(user_id, '@%s registration aborted due to timeout' % stage_meta['bot_info']['username'])
                except:
                    pass
                break
            elif stage_id is None:
                # Action cancelled
                break

            yield sleep(0.05)

        self.drop_stage(user_id)

    @coroutine
    def complete_registration(self, user_id, chat: dict):
        self.set_stage(user_id, self.STAGE_REGISTERED, chat_info=chat)


class Terminator:
    def __init__(self, token, m: Moderator):
        bot = Api(token)
        self.bot = bot
        self.moderator = m

    @coroutine
    def listen(self):
        yield self.bot.wait_commands()
        logging.info('Termination')

    @coroutine
    def stop(self):
        yield self.bot.stop()
