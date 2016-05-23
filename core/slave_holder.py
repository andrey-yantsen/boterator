import logging
from ujson import loads, dumps

from datetime import timedelta
from tornado.concurrent import Future
from tornado.gen import coroutine, with_timeout
from tornado.ioloop import IOLoop
from tornado.locks import Event

from core.bot import CommandFilterTextCmd
from core.queues import slaveholder_queues, QUEUE_SLAVEHOLDER_NEW_BOT, QUEUE_SLAVEHOLDER_GET_BOT_INFO, \
    QUEUE_SLAVEHOLDER_GET_MODERATION_GROUP, QUEUE_BOTERATOR_BOT_REVOKE
from telegram import Api, ApiError
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
            self._start_bot(**row)

        listen_future = self.queue.listen(slaveholder_queues(), self.queue_handler)

        try:
            yield self._finished.wait()
        finally:
            self.queue.stop(slaveholder_queues())
            yield listen_future

    def _start_bot(self, **kwargs):
        @coroutine
        def listen_done(f: Future):
            logging.debug('Bot #%s terminated', kwargs['id'])
            e = f.exception()
            if e:
                logging.debug('Got exception with bot #%d: %s', kwargs['id'], f.exception())
                if isinstance(e, ApiError) and e.code == 401:
                    logging.warning('Disabling bot #%d due to connection error', kwargs['id'])
                    yield self.queue.send(QUEUE_BOTERATOR_BOT_REVOKE, dumps(dict(error=str(e), **kwargs)))
                else:
                    IOLoop.current().add_timeout(timedelta(seconds=5), self._start_bot, **kwargs)

            del self.slaves[kwargs['id']]

        slave = Slave(db=self.db, **kwargs)
        slave_listen_f = slave.start()
        self.slaves[kwargs['id']] = {
            'future': slave_listen_f,
            'instance': slave,
        }
        IOLoop.current().add_future(slave_listen_f, listen_done)

    def stop(self):
        logging.info('Stopping slave-holder')
        for slave in self.slaves.values():
            slave.stop()

        self._finished.set()

    @coroutine
    def queue_handler(self, queue_name, body):
        body = loads(body.decode('utf-8'))

        if queue_name == QUEUE_SLAVEHOLDER_NEW_BOT:
            self._start_bot(**body)
        elif queue_name == QUEUE_SLAVEHOLDER_GET_BOT_INFO:
            bot = Api(body['token'], lambda x: None)

            if bot.bot_id in self.slaves:
                yield self.queue.send(body['reply_to'], dumps(dict(error='duplicate')))

            try:
                ret = yield bot.get_me()
            except Exception as e:
                yield self.queue.send(body['reply_to'], dumps(dict(error=str(e))))
                return

            yield self.queue.send(body['reply_to'], dumps(ret))
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
                    yield self.queue.send(body['reply_to'], dumps(dict(sender=update['message']['from'],
                                                                       **update['message']['chat'])))
                logging.debug('[bot#%s] Done', bot.bot_id)
                bot.stop()

            timeout_f.add_done_callback(handle_finish)

            cmd_filter = CommandFilterTextCmd('/attach')

            logging.debug('[bot#%s] Waiting for commands', bot.bot_id)
            bot.wait_commands()
        else:
            raise Exception('Unknown queue: %s', queue_name)
