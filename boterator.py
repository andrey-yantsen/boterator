import logging
from time import time

from tornado.gen import coroutine

from globals import get_db
from telegram import Api


class Moderator:
    STAGE_MODERATION_GROUP = 1
    STAGE_PUBLIC_CHANNEL = 2

    def __init__(self, token):
        bot = Api(token)
        bot.add_handler(self.start_command, '/start')
        bot.add_handler(self.reg_command, '/reg')
        bot.add_handler(self.cancel_command, '/cancel')
        bot.add_handler(self.attach_command, '/attach')
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

    def get_stage(self, user_id):
        if user_id in self.stages:
            return self.stages[user_id]['code'], self.stages[user_id]['meta']

        return None, {}

    @coroutine
    def start_command(self, message):
        yield self.bot.send_message(message['from']['id'], 'Hello, this is Boterator. Start -> go @BotFather and create new bot')

    @coroutine
    def reg_command(self, message):
        if self.get_stage(message['from']['id'])[0]:
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
                self.set_stage(message['chat']['id'], self.STAGE_MODERATION_GROUP, token=token)
            except Exception as e:
                logging.exception(e)
                yield self.bot.send_message(message['from']['id'], 'Unable to get bot info: %s' % str(e))

    @coroutine
    def cancel_command(self, message):
        if message['from']['id'] in self.stages:
            del self.stages[message['from']['id']]
        yield self.bot.send_message(message['from']['id'], 'Action cancelled')

    @coroutine
    def get_chat_type(self, chat_id):
        ret = yield get_db().execute("""
                    SELECT id, 'moderator' FROM registered_bots WHERE moderator_chat_id = %s
                    UNION SELECT id, 'public' FROM registered_bots WHERE public_chat_id = %s
                    """, (chat_id, chat_id))

        return ret.fetchone()

    @coroutine
    def new_chat(self, message):
        me = yield self.bot.get_me()

        if message['new_chat_member']['id'] == me['id']:
            chat_type = yield self.get_chat_type(message['chat']['id'])
            if not chat_type:
                if self.get_stage(message['from']['id']) == self.STAGE_MODERATION_GROUP:
                    yield self.attach_command(message)
                else:
                    yield self.bot.send_message(message['from']['id'], 'This bot wasn`t registered for %s %s, type /start for more info' % (message['chat']['type'], message['chat']['title']))
            elif chat_type[1] == 'public':
                yield self.bot.send_message(message['from']['id'], 'Hey man, you`ve added wrong bot to the group, it should be @%s' % chat_type[0])
            elif chat_type[1] == 'moderator':
                yield self.bot.send_message(message['chat']['id'], 'Hi there, @%s!' % message['from']['username'])
        else:
            return False

    @coroutine
    def attach_command(self, message):
        if self.get_stage(message['from']['id']) == self.STAGE_MODERATION_GROUP:
            yield self.bot.send_chat_action(message['from']['id'], self.bot.CHAT_ACTION_TYPING)
            new_bot = Api(self.stages[message['from']['id']]['meta']['token'])
            me = yield new_bot.get_me()
            yield self.bot.send_message(message['from']['id'], 'Ok, I`ll be sending moderation requests to %s %s' % (message['chat']['type'], message['chat']['title']))
            yield self.bot.send_message(message['from']['id'], 'Now you need to add your bot (@%s) to a channel as admin' % (me['username'], ))
            self.stages[message['from']['id']]['code'] = self.STAGE_PUBLIC_CHANNEL
            self.stages[message['from']['id']]['meta']['moderator'] = message['chat']['id']
        else:
            yield self.bot.send_message(message['from']['id'], 'Incorrect command')

    @coroutine
    def left_chat(self, message):
        me = yield self.bot.get_me()
        if message['left_chat_member']['id'] == me['id']:
            yield self.bot.send_message(message['from']['id'], 'Whyyyy?! :\'(')
        else:
            return False

    @coroutine
    def listen(self):
        yield self.bot.wait_commands()
