from contextlib import closing
from functools import partial

from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado.options import define, options, parse_command_line, print_help

from globals import get_db, init_db


@coroutine
def main():
    @coroutine
    def forward_message(message):
        yield bot.forward_message(message['chat']['id'], message['chat']['id'], message['message_id'])

    def send_post():
        return False;

    @coroutine
    def post_message(message):
        mes = message['text']
        if mes.strip() != '':
            yield bot.send_message(message['chat']['id'], 'You send me post: ' + message['text'])
            if len(mes) > 120 and len(mes) < 1000:
                if send_post():
                    yield bot.send_message(message['chat']['id'], 'So, good! Yout post publish.')
                else:
                    yield bot.send_message(message['chat']['id'], 'Sorry. You post is bad')
            else:
                yield bot.send_message(message['chat']['id'], 'Stop! Your post more 1000 or less 150')
        else:
            yield bot.send_message(message['chat']['id'], 'Seriously??? 8===3')

    bot.add_handler(post_message)
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
