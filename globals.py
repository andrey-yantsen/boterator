from tornado.gen import coroutine
from tornado.ioloop import IOLoop
from tornado.options import options
from momoko import Pool


PG_DB = None


@coroutine
def init_db():
    global PG_DB
    PG_DB = yield Pool(dsn=options.db, size=1, max_size=10, auto_shrink=True, ioloop=IOLoop.current())


@coroutine
def get_db():
    if not PG_DB:
        yield init_db()

    return PG_DB
