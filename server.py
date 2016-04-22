import logging

from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado.options import define, options, parse_command_line, print_help

from globals import init_db


@coroutine
def main():
    logging.info('Do something')


if __name__ == '__main__':
    define('token', type=str, help='TelegramBot\'s token')
    define('db', type=str, help='DB connection DSN, e.g. "dbname=bot user=bot host=localhost port=5432"')

    parse_command_line()

    if not options.token:
        print_help()
        exit(1)

    ioloop = IOLoop.instance()

    ioloop.run_sync(main)
