from contextlib import closing
from functools import partial

from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado.options import define, options, parse_command_line, print_help

from globals import get_db, get_telegram, init_db


@coroutine
def main():
    @coroutine
    def forward_message(message):
        yield bot.forward_message(message['chat']['id'], message['chat']['id'], message['message_id'])

    @coroutine
    def start_command(message):
        if message['text'] is not None:
            yield bot.send_message(message['chat']['id'], 'Hello,this is Boterator. Start -> go @BotFather and create new bot')

    @coroutine
    def reg_command(message):
        if message['text'] is not None:
            mes = message['text'][5:]
            if mes == '':
                yield bot.send_message(message['chat']['id'], 'Start -> go @BotFather and create new bot')
            else:
                yield bot.send_message(message['chat']['id'], 'Good! Your token ' + mes)

    @coroutine
    def get_chat_type(chat_id):
        ret = yield get_db().execute("""
                    SELECT id, 'moderator' FROM registered_bots WHERE moderator_chat_id = %s
                    UNION SELECT id, 'public' FROM registered_bots WHERE public_chat_id = %s
                    """, (chat_id, chat_id))

        return ret.fetchone()

    @coroutine
    def new_chat(message):
        if message['new_chat_member']['id'] == bot.me['id']:
            chat_type = yield get_chat_type(message['chat']['id'])
            if not chat_type:
                yield bot.send_message(message['from']['id'], 'This bot wasn`t registered for %s %s, type /start for more info' % (message['chat']['type'], message['chat']['title']))
            elif chat_type[1] == 'public':
                yield bot.send_message(message['from']['id'], 'Hey man, you`ve added wrong bot to public chat, it should be @%s' % chat_type[0])
            elif chat_type[1] == 'moderator':
                yield bot.send_message(message['chat']['id'], 'Hi there, @%s!' % message['from']['username'])
        else:
            return False

    @coroutine
    def left_chat(message):
        if message['left_chat_member']['id'] == bot.me['id']:
            yield bot.send_message(message['from']['id'], 'Whyyyy?! :\'(')
        else:
            return False

    bot = get_telegram()
    bot.add_handler(start_command,'/start')
    bot.add_handler(reg_command,'/reg')
    bot.add_handler(forward_message)
    bot.add_handler(partial(print, 'Non-command message'))
    bot.add_handler(new_chat, msg_type=bot.MSG_NEW_CHAT_MEMBER)
    bot.add_handler(left_chat, msg_type=bot.MSG_LEFT_CHAT_MEMBER)
    yield bot.wait_commands()


if __name__ == '__main__':
    define('token', type=str, help='TelegramBot\'s token')
    define('db', type=str, help='DB connection DSN, e.g. "dbname=boterator user=boterator host=localhost port=5432"')

    parse_command_line()

    if not options.token or not options.db:
        print_help()
        exit(1)

    ioloop = IOLoop.instance()

    ioloop.run_sync(init_db)
    ioloop.run_sync(main)
