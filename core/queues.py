from datetime import timedelta
from tornado.concurrent import Future
from tornado.gen import coroutine, with_timeout
from ujson import dumps, loads

QUEUE_BOTERATOR_BOT_REVOKE = 'boterator_bot_revoke'
QUEUE_SLAVEHOLDER_NEW_BOT = 'subordinateholder_new_bot'
QUEUE_SLAVEHOLDER_GET_BOT_INFO = 'subordinateholder_get_bot_info'
QUEUE_SLAVEHOLDER_GET_MODERATION_GROUP = 'subordinateholder_get_moderation_group'
QUEUE_SLAVEHOLDER_STOP_BOT = 'subordinateholder_stop_bot'


def boterator_queues():
    return [queue_name for queue_variable, queue_name in globals().items()
            if queue_variable.startswith('QUEUE_BOTERATOR_')]


def subordinateholder_queues():
    return [queue_name for queue_variable, queue_name in globals().items()
            if queue_variable.startswith('QUEUE_SLAVEHOLDER_')]


@coroutine
def queue_request(queue, queue_name, **kwargs):
    def queue_listener(queue_name, body):
        f.set_result(loads(body.decode('utf-8')))

    if 'timeout' not in kwargs:
        kwargs['timeout'] = 600

    kwargs['reply_to'] = '%s-reply-%s' % (queue_name, id(kwargs))
    yield queue.send(queue_name, dumps(kwargs))
    f = Future()
    queue.listen([kwargs['reply_to']], queue_listener, workers_count=1)

    f.add_done_callback(lambda f: queue.stop([kwargs['reply_to']]))

    return (yield with_timeout(timedelta(seconds=kwargs['timeout']), f))
