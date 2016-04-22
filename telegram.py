import logging

from tornado.concurrent import Future
from tornado.gen import coroutine, Task, Return, sleep
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
            yield sleep(0.05)

        yield self.processing_queue.join()

        [pt.set_exception(Return(None)) for pt in self.processing_threads]
        self.processing_threads = []

        return True

    @coroutine
    def __request_api(self, method, body=None, request_timeout=10):
        url = 'https://api.telegram.org/bot{token}/{method}'.format(token=self.token, method=method)
        try:
            response = yield AsyncHTTPClient().fetch(url,
                                                     method='POST' if body is not None else 'GET',
                                                     headers={'Content-type': 'application/json'} if body is not None else None,
                                                     body=ujson.dumps(body) if body is not None else None,
                                                     request_timeout=request_timeout)

            if response and response.body:
                response = ujson.loads(response.body.decode('utf-8'))
                if response['ok']:
                    return response['result']
                else:
                    raise ApiError(response['error_code'], response['description'])
        except HTTPError as e:
            # raise any
            if 400 <= e.code <= 499:
                response = ujson.loads(e.response.body.decode('utf-8'))
                raise ApiError(response['error_code'], response['description'])
            if 500 <= e.code < 599:  # Ignore internal HTTPClient errors - 599
                logging.exception('Telegram api error')

        return None

    @coroutine
    def get_updates(self, offset: int=None, limit: int=100, timeout: int=5):
        assert 1 <= limit <= 100
        assert 0 <= timeout
        assert offset is None or offset > 0

        request = {
            'limit': limit,
            'timeout': timeout
        }

        if offset is not None:
            request['offset'] = offset

        data = yield self.__request_api('getUpdates', request, timeout * 1.5)

        if data is None:
            return []

        return data

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

                yield sleep(0.05)

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
    def send_chat_action(self, chat_id, action: str):
        return (yield self.__request_api('sendChatAction', {'chat_id': chat_id, 'action': action}))

    @coroutine
    def send_message(self, chat_id, text: str, parse_mode: str=None, disable_web_page_preview: bool=False,
                     disable_notification: bool=False, reply_to_message_id: int=None, reply_markup=None):
        request = {
            'chat_id': chat_id,
            'text': text,
            'disable_web_page_preview': disable_web_page_preview,
            'disable_notification': disable_notification,
        }

        if parse_mode is not None:
            request['parse_mode'] = parse_mode

        if reply_to_message_id is not None:
            request['reply_to_message_id'] = reply_to_message_id

        if reply_markup is not None:
            request['reply_markup'] = reply_markup

        return (yield self.__request_api('sendMessage', request))

    @coroutine
    def forward_message(self, chat_id, from_chat_id, message_id: int, disable_notification: bool=False):
        return (yield self.__request_api('forwardMessage', {
            'chat_id': chat_id,
            'from_chat_id': from_chat_id,
            'disable_notification': disable_notification,
            'message_id': message_id,
        }))

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

                        handled = False
                        for required_cmd, handler in self.callbacks:
                            if required_cmd == cmd:
                                ret = handler(update['message'])
                                if isinstance(ret, Future):
                                    ret = yield ret

                                if ret is None or ret is True:
                                    handled = True
                                    break

                        if not handled:
                            logging.error('Handler not found: %s', update)
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
