from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado.options import options
from momoko import Pool

from telegram import Api

PG_DB = None
TELEGRAM_API = None


@coroutine
def get_db():
    global PG_DB
    if not PG_DB:
        PG_DB = Pool(dsn=options.db, size=1, max_size=10, auto_shrink=True, ioloop=IOLoop.current())
        yield PG_DB.connect()

    return PG_DB


def get_telegram():
    global TELEGRAM_API
    if not TELEGRAM_API:
        TELEGRAM_API = Api(options.token)

    return TELEGRAM_API
