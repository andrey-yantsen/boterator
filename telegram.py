import logging

from tornado.concurrent import Future
from tornado.gen import coroutine, Task, Return
from tornado.httpclient import AsyncHTTPClient, HTTPError
from tornado.ioloop import IOLoop
import ujson

from tornado.queues import Queue


class Api:
    STATE_WORKING = 0
    STATE_STOP_PENDING = 1
    STATE_STOPPED = 2

    def __init__(self, token, processing_threads_cnt=30):
        self.token = token
        self.callbacks = []
        self.consumption_state = self.STATE_STOPPED
        self.processing_threads = []
        self.processing_threads_cnt = processing_threads_cnt
        self.processing_queue = Queue(processing_threads_cnt * 10)

    def add_handler(self, handler, cmd: str=None):
        self.callbacks.append((cmd, handler))

    @coroutine
    def stop(self):
        self.consumption_state = self.STATE_STOP_PENDING

        while self.consumption_state != self.STATE_STOPPED:
            yield Task(IOLoop.current().add_callback)

        yield self.processing_queue.join()

        [pt.set_exception(Return(None)) for pt in self.processing_threads]
        self.processing_threads = []

        return True

    @coroutine
    def get_updates(self, offset: int=None, limit: int=100, timeout: int=5):
        assert 1 <= limit <= 100
        assert 0 <= timeout
        assert offset is None or offset > 0

        url = 'https://api.telegram.org/bot{token}/getUpdates'.format(token=self.token)

        request = {
            'limit': limit,
            'timeout': timeout
        }

        if offset is not None:
            request['offset'] = offset

        try:
            response = yield AsyncHTTPClient().fetch(url, method='POST', headers={'Content-type': 'application/json'},
                                                     body=ujson.dumps(request), request_timeout=timeout * 1.5)

            if response and response.body:
                response = ujson.loads(response.body.decode('utf-8'))
                return response['result']
        except HTTPError as e:
            # raise any
            if 400 <= e.code <= 499:
                response = ujson.loads(e.response.body.decode('utf-8'))
                raise ApiError(response['error_code'], response['description'])
            if 500 <= e.code < 599:  # Ignore internal HTTPClient errors - 599
                logging.exception('Telegram api error')

        return []

    @coroutine
    def wait_commands(self, last_update_id=None):
        if self.consumption_state != self.STATE_STOPPED:
            logging.warning('Another handler still active')
            return False

        if len(self.callbacks) == 0:
            logging.warning('Starting updates consumption without any message handler set')

        self.processing_threads = [self._process_update() for _ in range(self.processing_threads_cnt)]

        self.consumption_state = self.STATE_WORKING

        if last_update_id is None:
            last_update_id = 0

        while True and self.consumption_state == self.STATE_WORKING:
            get_updates_f = self.get_updates(last_update_id + 1)
            # Actually default tornado's futures doesn't support cancellation, so let's make some magic
            cancelled = False

            while get_updates_f.running() and not cancelled:
                if self.consumption_state == self.STATE_STOP_PENDING:
                    cancelled = True
                    break

                yield Task(IOLoop.current().add_callback)

            if cancelled:
                self.consumption_state = self.STATE_STOPPED
                break

            if get_updates_f.exception():
                # Actually it's better to stop right now because of some strange shit happened
                self.stop()
                self.consumption_state = self.STATE_STOPPED
                get_updates_f.result()  # This one will raise the exception and cancel future execution
                raise ApiInternalError('Downloading future failure')

            updates = yield get_updates_f

            for update in updates:
                yield self.processing_queue.put(update)
                self._process_update(update)
                last_update_id = update['update_id']

    @coroutine
    def _process_update(self):
        while True:
            update = yield self.processing_queue.get()

            try:
                if 'message' in update:
                    if 'text' in update['message']:
                        # Got bot command
                        if update['message']['text'][0] == '/':
                            if update['message']['text'].find(' ') > -1:
                                cmd = update['message']['text'][:update['message']['text'].find(' ')]
                            else:
                                cmd = update['message']['text']
                        else:
                            cmd = None

                        for required_cmd, handler in self.callbacks:
                            if required_cmd == cmd:
                                ret = handler(update)
                                if isinstance(ret, Future):
                                    ret = yield ret

                                if ret is None or ret == True:
                                    break
                    else:
                        logging.error('Unsupported message received')

                elif 'inline_query' in update:
                    logging.error('Unsupported message received')
                else:
                    logging.error('Unsupported message received')
            except:
                logging.exception('Error while processing message')

            self.processing_queue.task_done()


class ApiError(Exception):
    def __init__(self, code, description, *args, **kwargs):
        self.code = code
        self.description = description
        super().__init__('Api error: %s, %s' % (code, description), *args, **kwargs)


class ApiInternalError(Exception):
    pass
