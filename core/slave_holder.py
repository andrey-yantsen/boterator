import logging
from ujson import loads

from datetime import timedelta
from tornado.concurrent import Future
from tornado.gen import coroutine, Return, sleep, with_timeout
from tornado.ioloop import IOLoop
from tornado.locks import Event

from core.bot import CommandFilterTextCmd
from core.queues import slaveholder_queues, QUEUE_SLAVEHOLDER_NEW_BOT, QUEUE_SLAVEHOLDER_GET_BOT_INFO, queue_reply, \
    QUEUE_SLAVEHOLDER_GET_MODERATION_GROUP
from telegram import Api
from .slave import Slave


class SlaveHolder:
    def __init__(self, db, queue):
        self.db = db
        self.slaves = {}
        self._finished = Event()
        self._finished.set()
        self.queue = queue

    @coroutine
    def start(self):
        self._finished.clear()
        logging.debug('Starting slave-holder')

        cur = yield self.db.execute('SELECT * FROM registered_bots WHERE active = TRUE')
        columns = [i[0] for i in cur.description]

        while True:
            row = cur.fetchone()
            if not row:
                break

            row = dict(zip(columns, row))
            # self._start_bot(**row)

        listen_future = self.queue.listen(slaveholder_queues(), self.queue_handler)

        try:
            yield self._finished.wait()
        finally:
            self.queue.stop(slaveholder_queues())
            yield listen_future

    def _start_bot(self, **kwargs):
        slave = Slave(**kwargs)
        self.slaves[kwargs['id']] = {
            'future': slave.listen(),
            'instance': slave
        }

    @coroutine
    def stop(self):
        logging.info('Stopping slave-holder')
        for slave in self.slaves.values():
            yield slave.stop()

        self._finished.set()

    @coroutine
    def queue_handler(self, queue_name, body):
        body = loads(body.decode('utf-8'))

        if queue_name == QUEUE_SLAVEHOLDER_NEW_BOT:
            self.register_new_bot(**body)
        elif queue_name == QUEUE_SLAVEHOLDER_GET_BOT_INFO:
            bot = Api(body['token'], lambda x: None)

            if bot.bot_id in self.slaves:
                yield queue_reply(self.queue, error='duplicate', **body)

            try:
                ret = yield bot.get_me()
            except Exception as e:
                yield queue_reply(self.queue, error=str(e), **body)
                return

            yield queue_reply(self.queue, body['reply_to'], **ret)
        elif queue_name == QUEUE_SLAVEHOLDER_GET_MODERATION_GROUP:
            update_with_command_f = Future()
            timeout_f = with_timeout(timedelta(seconds=body['timeout']), update_with_command_f)

            @coroutine
            def slave_update_handler(update):
                logging.debug('[bot#%s] Received update', bot.bot_id)
                if cmd_filter(update):
                    update_with_command_f.set_result(update)

            bot = Api(body['token'], slave_update_handler)

            @coroutine
            def handle_finish(f):
                if not f.exception():
                    update = f.result()
                    yield queue_reply(self.queue, body['reply_to'], sender=update['message']['from'],
                                      **update['message']['chat'])
                logging.debug('[bot#%s] Done', bot.bot_id)
                bot.stop()

            timeout_f.add_done_callback(handle_finish)

            cmd_filter = CommandFilterTextCmd('/attach')

            logging.debug('[bot#%s] Waiting for commands', bot.bot_id)
            bot.wait_commands()

    @coroutine
    def register_new_bot(self, token, settings):
        pass
