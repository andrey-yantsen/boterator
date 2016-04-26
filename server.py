import signal
from tornado.ioloop import IOLoop
from tornado.options import define, options, parse_command_line, print_help

from globals import init_db
from boterator import BotMother


if __name__ == '__main__':
    define('token', type=str, help='TelegramBot\'s token')
    define('botan_token', type=str, help='Bot\'s botan.io token')
    define('db', type=str, help='DB connection DSN, e.g. "dbname=boterator user=boterator host=localhost port=5432"')

    parse_command_line()

    if not options.token or not options.db:
        print_help()
        exit(1)

    ioloop = IOLoop.instance()

    ioloop.run_sync(init_db)

    bm = BotMother(options.token)
    ioloop.run_sync(bm.listen)

    signal.signal(signal.SIGTERM, bm.stop)
    signal.signal(signal.SIGINT, bm.stop)
