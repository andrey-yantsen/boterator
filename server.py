from functools import partial

from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado.options import define, options, parse_command_line, print_help

from globals import get_db, get_telegram


@coroutine
def main():
    @coroutine
    def forward_message(message):
        yield bot.forward_message(message['chat']['id'], message['chat']['id'], message['message_id'])

    bot = get_telegram()
    bot.add_handler(print, '/start')
    bot.add_handler(forward_message)
    bot.add_handler(partial(print, 'Non-command message'))
    yield bot.wait_commands()


if __name__ == '__main__':
    define('token', type=str, help='TelegramBot\'s token')
    define('db', type=str, help='DB connection DSN, e.g. "dbname=bot user=bot host=localhost port=5432"')

    parse_command_line()

    if not options.token:
        print_help()
        exit(1)

    ioloop = IOLoop.instance()

    ioloop.run_sync(main)
