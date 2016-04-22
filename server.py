import logging

from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado.options import define, options, parse_command_line, print_help

from globals import init_db
from boterator import Moderator


@coroutine
def main():
    moderator = Moderator(options.token)
    yield moderator.listen()


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
