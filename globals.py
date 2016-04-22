from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado.options import options
from momoko import Pool

from telegram import Api

PG_DB = None
TELEGRAM_API = None

@coroutine
def get_db():
    if not PG_DB:
        global PG_DB
        PG_DB = yield Pool(dsn=options.db, size=1, max_size=10, auto_shrink=True, ioloop=IOLoop.current())

    return PG_DB


def get_telegram():
    if not TELEGRAM_API:
        global TELEGRAM_API
        TELEGRAM_API = Api(options.token)

    return TELEGRAM_API
