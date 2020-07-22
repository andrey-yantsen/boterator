import logging
from traceback import format_exception
from ujson import loads, dumps

from datetime import timedelta
from tornado.concurrent import Future
from tornado.gen import coroutine, with_timeout
from tornado.ioloop import IOLoop
from tornado.locks import Event

from tobot import CommandFilterTextCmd, CommandFilterNewChatMember, CommandFilterGroupChatCreated, \
    CommandFilterSupergroupChatCreated
from .queues import subordinateholder_queues, QUEUE_SLAVEHOLDER_NEW_BOT, QUEUE_SLAVEHOLDER_GET_BOT_INFO, \
    QUEUE_SLAVEHOLDER_GET_MODERATION_GROUP, QUEUE_BOTERATOR_BOT_REVOKE
from tobot.telegram import Api, ApiError
from .subordinate import Subordinate


class SubordinateHolder:
    def __init__(self, db, queue):
        self.db = db
        self.subordinates = {}
        self._finished = Event()
        self._finished.set()
        self.queue = queue

    @coroutine
    def start(self):
        self._finished.clear()
        logging.debug('Starting subordinate-holder')

        cur = yield self.db.execute('SELECT * FROM registered_bots WHERE active = TRUE')
        columns = [i[0] for i in cur.description]

        while True:
            row = cur.fetchone()
            if not row:
                break

            row = dict(zip(columns, row))
            self._start_bot(**row)

        listen_future = self.queue.listen(subordinateholder_queues(), self.queue_handler)

        try:
            yield self._finished.wait()
        finally:
            self.queue.stop(subordinateholder_queues())
            yield listen_future

    def _start_bot(self, **kwargs):
        @coroutine
        def listen_done(f: Future):
            logging.debug('[bot#%s] Terminated', kwargs['id'])
            e = f.exception()
            if e:
                logging.debug('[bot#%s] Got exception: %s %s', kwargs['id'], format_exception(*f.exc_info()))
                if isinstance(e, ApiError) and e.code == 401:
                    logging.warning('[bot#%d] Disabling due to connection error', kwargs['id'])
                    yield self.queue.send(QUEUE_BOTERATOR_BOT_REVOKE, dumps(dict(error=str(e), **kwargs)))
                elif isinstance(e, ApiError) and e.code == 400 and 'chat not found' in e.description and \
                    str(kwargs['moderator_chat_id']) in e.request_body:
                    logging.warning('[bot#%d] Disabling due to unavailable moderator chat', kwargs['id'])
                    yield self.queue.send(QUEUE_BOTERATOR_BOT_REVOKE, dumps(dict(error=str(e), **kwargs)))
                elif isinstance(e, ApiError) and e.code == 409 and 'webhook is active' in e.description:
                    logging.warning('[bot#%d] Disabling due to misconfigured webhook', kwargs['id'])
                    yield self.queue.send(QUEUE_BOTERATOR_BOT_REVOKE, dumps(dict(error=str(e), **kwargs)))
                else:
                    IOLoop.current().add_timeout(timedelta(seconds=5), self._start_bot, **kwargs)

            del self.subordinates[kwargs['id']]

        subordinate = Subordinate(db=self.db, **kwargs)
        subordinate_listen_f = subordinate.start()
        self.subordinates[kwargs['id']] = {
            'future': subordinate_listen_f,
            'instance': subordinate,
        }
        IOLoop.current().add_future(subordinate_listen_f, listen_done)

    def stop(self):
        logging.info('Stopping subordinate-holder')
        for subordinate in self.subordinates.values():
            subordinate['instance'].stop()

        self._finished.set()

    @coroutine
    def queue_handler(self, queue_name, body):
        body = loads(body.decode('utf-8'))

        if queue_name == QUEUE_SLAVEHOLDER_NEW_BOT:
            self._start_bot(**body)
        elif queue_name == QUEUE_SLAVEHOLDER_GET_BOT_INFO:
            bot = Api(body['token'], lambda x: None)

            if bot.bot_id in self.subordinates:
                logging.debug('[bot#%s] Already registered', bot.bot_id)
                yield self.queue.send(body['reply_to'], dumps(dict(error='duplicate')))

            try:
                ret = yield bot.get_me()
                logging.debug('[bot#%s] Ok', bot.bot_id)
            except Exception as e:
                logging.debug('[bot#%s] Failed', bot.bot_id)
                yield self.queue.send(body['reply_to'], dumps(dict(error=str(e))))
                return

            yield self.queue.send(body['reply_to'], dumps(ret))
        elif queue_name == QUEUE_SLAVEHOLDER_GET_MODERATION_GROUP:
            update_with_command_f = Future()
            timeout_f = with_timeout(timedelta(seconds=body['timeout']), update_with_command_f)

            @coroutine
            def subordinate_update_handler(update):
                logging.debug('[bot#%s] Received update', bot.bot_id)
                if attach_cmd_filter.test(**update):
                    logging.debug('[bot#%s] /attach', bot.bot_id)
                    update_with_command_f.set_result(update)
                elif bot_added.test(**update):
                    logging.debug('[bot#%s] bot added to a group', bot.bot_id)
                    update_with_command_f.set_result(update)
                elif CommandFilterGroupChatCreated.test(**update) or CommandFilterSupergroupChatCreated.test(**update):
                    logging.debug('[bot#%s] group created', bot.bot_id)
                    update_with_command_f.set_result(update)
                else:
                    logging.debug('[bot#%s] unsupported update: %s', dumps(update, indent=2))

            bot = Api(body['token'], subordinate_update_handler)

            @coroutine
            def handle_finish(f):
                bot.stop()
                if not f.exception():
                    logging.debug('[bot#%s] Done', bot.bot_id)
                    update = f.result()
                    yield self.queue.send(body['reply_to'], dumps(dict(sender=update['message']['from'],
                                                                       **update['message']['chat'])))

                    # Mark last update as read
                    f2 = bot.get_updates(update['update_id'] + 1, timeout=0, retry_on_nonuser_error=True)
                    f2.add_done_callback(lambda x: x.exception())  # Ignore any exceptions
                else:
                    logging.debug('[bot#%s] Failed: %s', bot.bot_id, f.exception())

            timeout_f.add_done_callback(handle_finish)

            attach_cmd_filter = CommandFilterTextCmd('/attach')
            bot_added = CommandFilterNewChatMember(bot.bot_id)

            logging.debug('[bot#%s] Waiting for moderation group', bot.bot_id)
            bot.wait_commands()
        else:
            raise Exception('Unknown queue: %s', queue_name)
