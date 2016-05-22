import logging
from time import time

from os.path import basename

from functools import partial
from tornado.concurrent import Future
from tornado.gen import coroutine, Return, sleep, maybe_future, Task
from tornado.httpclient import AsyncHTTPClient, HTTPError
import ujson

from tornado.ioloop import IOLoop
from tornado.locks import Event
from tornado.queues import Queue
from hashlib import md5


class Api:
    STATE_WORKING = 0
    STATE_STOP_PENDING = 1
    STATE_STOPPED = 2

    CHAT_ACTION_TYPING = 'typing'
    CHAT_ACTION_UPLOAD_PHOTO = 'upload_photo'
    CHAT_ACTION_RECORD_VIDEO = 'record_video'
    CHAT_ACTION_UPLOAD_VIDEO = 'upload_video'
    CHAT_ACTION_RECORD_AUDIO = 'record_audio'
    CHAT_ACTION_UPLOAD_AUDIO = 'upload_audio'
    CHAT_ACTION_UPLOAD_DOC = 'upload_document'
    CHAT_ACTION_FIND_LOCATION = 'find_location'

    PARSE_MODE_NONE = None
    PARSE_MODE_MD = 'Markdown'
    PARSE_MODE_HTML = 'HTML'

    def __init__(self, token, processor):
        if ':' in token:
            self.bot_id, _ = token.split(':')
            if self.bot_id.isdigit():
                self.bot_id = int(self.bot_id)
            else:
                raise ValueError('Non well-formatted token given')
        else:
            raise ValueError('Non well-formatted token given')

        self.token = token
        self.consumption_state = self.STATE_STOPPED
        self.processor = processor
        self.__me = None
        self._finished = Event()
        self._finished.set()

    @coroutine
    def get_me(self):
        if not self.__me:
            self.__me = yield self.__request_api('getMe')

        return self.__me

    def stop(self):
        assert not self._finished.is_set()
        self._finished.set()

    @coroutine
    def __request_api(self, method, body=None, request_timeout=10, retry_on_nonuser_error=False):
        def guess_filename(obj):
            """Tries to guess the filename of the given object."""
            name = getattr(obj, 'name', None)
            if name and isinstance(name, str) and name[0] != '<' and name[-1] != '>':
                return basename(name)

        url = 'https://api.telegram.org/bot{token}/{method}'.format(token=self.token, method=method)
        try:
            request = {
                'request_timeout': request_timeout,
                'headers': {},
            }

            if body:
                request['method'] = 'POST'
                request_content = {}
                has_files = False
                file_names = {}
                for key, value in body.items():
                    if hasattr(value, 'read'):
                        request_content[key] = value.read()
                        file_names[key] = guess_filename(value)
                        has_files = True
                    else:
                        request_content[key] = value

                if has_files:
                    boundary = md5(str(time()).encode('utf-8')).hexdigest()
                    request['headers']['Content-type'] = 'multipart/form-data; boundary=' + boundary

                    body = []
                    for key, value in request_content.items():
                        body.append(b'--' + boundary.encode('utf-8'))
                        if key in file_names:
                            body.append(('Content-Disposition: form-data; name="%s"; filename="%s"' % (key, file_names[key])).encode('utf-8'))
                        else:
                            body.append(('Content-Disposition: form-data; name="%s"' % key).encode('utf-8'))

                        body.append(b'')
                        if isinstance(value, int):
                            value = str(value)
                        if isinstance(value, str):
                            value = value.encode('utf-8')
                        body.append(value)
                    body.append(b'--' + boundary.encode('utf-8') + b'--')
                    body = b"\r\n" + b"\r\n".join(body) + b"\r\n"
                else:
                    request['headers']['Content-type'] = 'application/json'
                    body = ujson.dumps(request_content)
            else:
                request['method'] = 'GET'

            while True:
                try:
                    response = yield AsyncHTTPClient().fetch(url, body=body, **request)
                    break
                except HTTPError as e:
                    if not retry_on_nonuser_error or 400 <= e.code < 500:
                        raise
                    else:
                        yield sleep(5)

            if response and response.body:
                response = ujson.loads(response.body.decode('utf-8'))
                if response['ok']:
                    return response['result']
                else:
                    raise ApiError(response['error_code'], response['description'])
        except HTTPError as e:
            if e.code == 599:
                logging.exception('%s request timed out', method)  # Do nothing on timeout, just return None
            elif e.response and e.response.body:
                response = ujson.loads(e.response.body.decode('utf-8'))
                raise ApiError(response['error_code'], response['description'])
            else:
                raise ApiError(e.code, None)

        return None

    @coroutine
    def get_updates(self, offset: int=None, limit: int=100, timeout: int=2, retry_on_nonuser_error: bool=False):
        assert 1 <= limit <= 100
        assert 0 <= timeout

        request = {
            'limit': limit,
            'timeout': timeout
        }

        if offset is not None:
            request['offset'] = offset

        data = yield self.__request_api('getUpdates', request, request_timeout=timeout * 1.5,
                                        retry_on_nonuser_error=retry_on_nonuser_error)

        if data is None:
            return []

        return data

    @coroutine
    def wait_commands(self, last_update_id=None):
        assert self._finished.is_set()

        self._finished.clear()

        self.consumption_state = self.STATE_WORKING

        if last_update_id is not None:
            last_update_id += 1

        yield self.get_me()

        while not self._finished.is_set():
            try:
                updates = yield self.get_updates(last_update_id, retry_on_nonuser_error=True)
            except:
                self._finished.set()
                raise

            for update in updates:
                yield maybe_future(self.processor(update))
                last_update_id = update['update_id']

            if len(updates):
                last_update_id += 1

    @coroutine
    def send_chat_action(self, chat_id, action: str):
        return (yield self.__request_api('sendChatAction', {'chat_id': chat_id, 'action': action}))

    @coroutine
    def send_message(self, text: str, chat_id=None, reply_to_message: dict=None, parse_mode: str=None,
                     disable_web_page_preview: bool=False, disable_notification: bool=False,
                     reply_to_message_id: int=None, reply_markup=None):
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

        if reply_to_message:
            if chat_id is None:
                request['chat_id'] = reply_to_message['chat']['id']
                if reply_to_message['chat']['id'] != reply_to_message['from']['id']:
                    request['reply_to_message_id'] = reply_to_message['message_id']
            else:
                request['reply_to_message_id'] = reply_to_message['message_id']
        else:
            assert chat_id is not None

        if reply_markup is not None:
            request['reply_markup'] = reply_markup

        try:
            return (yield self.__request_api('sendMessage', request))
        except ApiError as e:
            if e.code == 400 and e.description.startswith("Bad Request: Can\'t parse"):
                logging.exception('Got exception while sending text: %s', text)
            raise

    @coroutine
    def send_photo(self, chat_id, photo, caption: str=None, disable_notification: bool=False,
                   reply_to_message_id: int=None, reply_markup=None):
        request = {
            'chat_id': chat_id,
            'photo': photo,
            'disable_notification': disable_notification,
        }

        if caption is not None:
            request['caption'] = caption

        if reply_to_message_id is not None:
            request['reply_to_message_id'] = reply_to_message_id

        if reply_markup is not None:
            request['reply_markup'] = reply_markup

        return (yield self.__request_api('sendPhoto', request))

    @coroutine
    def forward_message(self, chat_id, from_chat_id, message_id: int, disable_notification: bool=False):
        return (yield self.__request_api('forwardMessage', {
            'chat_id': chat_id,
            'from_chat_id': from_chat_id,
            'disable_notification': disable_notification,
            'message_id': message_id,
        }))

    @staticmethod
    def _prepare_inline_message(message=None, chat_id=None, message_id=None, inline_message_id=None):
        request = {}

        if message:
            request['chat_id'] = message['chat']['id']
            request['message_id'] = message['message_id']
        elif chat_id and message_id:
            request['chat_id'] = chat_id
            request['message_id'] = message_id
        else:
            request['inline_message_id'] = inline_message_id

        return request

    @coroutine
    def edit_message_reply_markup(self, message=None, chat_id=None, message_id=None, inline_message_id=None,
                                  reply_markup=None):
        assert (chat_id and message_id) or message or inline_message_id

        request = self._prepare_inline_message(message=message, chat_id=chat_id, message_id=message_id,
                                               inline_message_id=inline_message_id)

        if reply_markup:
            request['reply_markup'] = reply_markup

        return (yield self.__request_api('editMessageReplyMarkup', request))

    @coroutine
    def edit_message_text(self, text, message=None, chat_id=None, message_id=None, inline_message_id=None,
                          parse_mode=None, disable_web_page_preview=False, reply_markup=None):
        request = self._prepare_inline_message(message=message, chat_id=chat_id, message_id=message_id,
                                               inline_message_id=inline_message_id)

        if parse_mode is not None:
            request['parse_mode'] = parse_mode

        request['disable_web_page_preview'] = disable_web_page_preview
        request['text'] = text

        if reply_markup is not None:
            request['reply_markup'] = reply_markup

        return (yield self.__request_api('editMessageText', request))

    @coroutine
    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        request = {
            'callback_query_id': callback_query_id,
            'show_alert': show_alert
        }

        if text:
            request['text'] = text

        return (yield self.__request_api('answerCallbackQuery', request))


class ApiWithHandlers(Api):
    UPDATE_TYPE_MSG_ANY = 'message_any'
    UPDATE_TYPE_MSG_TEXT = 'message_text'
    UPDATE_TYPE_MSG_AUDIO = 'message_audio'
    UPDATE_TYPE_MSG_PHOTO = 'message_photo'
    UPDATE_TYPE_MSG_DOC = 'message_document'
    UPDATE_TYPE_MSG_STICKER = 'message_sticker'
    UPDATE_TYPE_MSG_VIDEO = 'message_video'
    UPDATE_TYPE_MSG_VOICE = 'message_voice'
    UPDATE_TYPE_MSG_CONTACT = 'message_contact'
    UPDATE_TYPE_MSG_LOCATION = 'message_location'
    UPDATE_TYPE_MSG_VENUE = 'message_venue'
    UPDATE_TYPE_MSG_NEW_CHAT_MEMBER = 'new_chat_member'
    UPDATE_TYPE_MSG_LEFT_CHAT_MEMBER = 'left_chat_member'
    UPDATE_TYPE_MSG_GROUP_CHAT_CREATED = 'group_chat_created'
    UPDATE_TYPE_MSG_SUPERGROUP_CHAT_CREATED = 'supergroup_chat_created'
    UPDATE_TYPE_MSG_UNKNOWN = 'message_unknown'

    UPDATE_TYPE_INLINE_QUERY = 'inline_query'
    UPDATE_TYPE_CHOSEN_INLINE_RESULT = 'chosen_inline_result'
    UPDATE_TYPE_CALLBACK_QUERY = 'callback_query'

    def __init__(self, token, processing_threads_cnt=5):
        super().__init__(token, processor=self._queue_update)
        self.callbacks = []
        self.consumption_state = self.STATE_STOPPED
        self.processing_threads = []
        self.processing_threads_cnt = processing_threads_cnt
        self.processing_queue = Queue(100)

    @coroutine
    def stop(self):
        ret = yield super().stop()
        yield self.processing_queue.join()
        for pt in self.processing_threads:
            pt.set_exception(Return(None))

        for pt in self.processing_threads:
            yield Task(partial(IOLoop.current().add_future, pt))

        self.processing_threads = []
        return ret

    def add_handler(self, handler, cmd=None, msg_type: str=UPDATE_TYPE_MSG_TEXT):
        self.callbacks.append((msg_type, cmd, handler))

    @coroutine
    def _queue_update(self, update):
        yield self.processing_queue.put(update)

    @coroutine
    def __execute_update_handler(self, handler_filter: callable, update):
        handled = False
        for required_message_type, required_cmd, handler in self.callbacks:
            if handler_filter(required_message_type, required_cmd):
                ret = handler(update)
                if isinstance(ret, Future):
                    ret = yield ret

                if ret is None or ret is True:
                    handled = True
                    break

        if not handled:
            logging.info('Handler not found: %s', update)
            return False

    @coroutine
    def _process_update(self):
        def default_filter_text_msg(cmd):
            return lambda r, c: (r == self.UPDATE_TYPE_MSG_TEXT or r == self.UPDATE_TYPE_MSG_ANY) \
                                and (c == cmd or (cmd and hasattr(c, 'match') and c.match(cmd)) or c is False)

        def default_filter_msg(msg_type):
            return lambda r, c: (r == msg_type or r == self.UPDATE_TYPE_MSG_ANY) and c is None

        def default_filter(msg_type):
            return lambda r, _: r == msg_type

        def default_filter_cb(cmd):
            return lambda r, c: r == self.UPDATE_TYPE_CALLBACK_QUERY and \
                                (c == cmd or (cmd and hasattr(c, 'match') and c.match(cmd)) or c is False)

        bot_info = yield self.get_me()
        while True:
            update = yield self.processing_queue.get()

            try:
                if 'message' in update:
                    if 'text' in update['message']:
                        if update['message']['text'].startswith('@' + bot_info['username']):
                            update['message']['text'] = update['message']['text'][len(bot_info['username'])+1:].strip()
                        elif update['message']['text'].endswith('@' + bot_info['username']):
                            update['message']['text'] = update['message']['text'][:-len(bot_info['username'])-1].strip()

                        # Got bot command
                        if len(update['message']['text']) and update['message']['text'][0] == '/':
                            if update['message']['text'].find(' ') > -1:
                                cmd = update['message']['text'][:update['message']['text'].find(' ')]
                            else:
                                cmd = update['message']['text']
                        else:
                            cmd = None

                        yield self.__execute_update_handler(default_filter_text_msg(cmd), update['message'])
                    elif 'left_chat_member' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_LEFT_CHAT_MEMBER), update['message'])
                    elif 'new_chat_member' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_NEW_CHAT_MEMBER), update['message'])
                    elif 'audio' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_AUDIO), update['message'])
                    elif 'document' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_DOC), update['message'])
                    elif 'photo' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_PHOTO), update['message'])
                    elif 'sticker' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_STICKER), update['message'])
                    elif 'video' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_VIDEO), update['message'])
                    elif 'voice' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_VOICE), update['message'])
                    elif 'location' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_LOCATION), update['message'])
                    elif 'venue' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_NEW_CHAT_MEMBER), update['message'])
                    elif 'group_chat_created' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_GROUP_CHAT_CREATED), update['message'])
                    elif 'supergroup_chat_created' in update['message']:
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_SUPERGROUP_CHAT_CREATED), update['message'])
                    else:
                        logging.info('Unsupported message received: %s', update)
                        yield self.__execute_update_handler(default_filter_msg(self.UPDATE_TYPE_MSG_UNKNOWN), update['message'])
                elif 'inline_query' in update:
                    yield self.__execute_update_handler(default_filter(self.UPDATE_TYPE_INLINE_QUERY), update['inline_query'])
                elif 'chosen_inline_result' in update:
                    yield self.__execute_update_handler(default_filter(self.UPDATE_TYPE_CHOSEN_INLINE_RESULT), update['chosen_inline_result'])
                elif 'callback_query' in update:
                    yield self.__execute_update_handler(default_filter_cb(update['callback_query']['data']),
                                                        update['callback_query'])
                else:
                    logging.info('Unsupported message received: %s', update)
            except:
                logging.exception('Error while processing message')

            self.processing_queue.task_done()

    @coroutine
    def wait_commands(self, last_update_id=None):
        if self.consumption_state != self.STATE_STOPPED:
            logging.warning('Another handler still active')
            return False

        if len(self.callbacks) == 0:
            logging.warning('Starting updates consumption without any message handler set')

        self.processing_threads = [self._process_update() for _ in range(self.processing_threads_cnt)]

        try:
            return (yield super().wait_commands(last_update_id))
        finally:
            self.consumption_state = self.STATE_STOPPED
            yield self.stop()


class ReplyMarkup(dict):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


class InlineKeyboardButton(dict):
    def __init__(self, text, url=None, callback_data=None, switch_inline_query=None):
        params = iter((url, callback_data, switch_inline_query))
        assert any(params) and not any(params)
        p = {}
        if url:
            p['url'] = url
        elif callback_data:
            p['callback_data'] = callback_data
        elif switch_inline_query:
            p['switch_inline_query'] = switch_inline_query
        super().__init__(text=text, **p)


class InlineKeyboardMarkup(ReplyMarkup):
    def __init__(self, inline_keyboard: list):
        assert all(map(lambda x: isinstance(x, list), inline_keyboard))
        assert all(map(lambda x: all(map(lambda z: isinstance(z, InlineKeyboardButton), x)), inline_keyboard))
        super().__init__(inline_keyboard=inline_keyboard)


class KeyboardButton(dict):
    def __init__(self, text, request_contact=False, request_location=False):
        super().__init__(text=text, request_contact=request_contact, request_location=request_location)


class ReplyKeyboardMarkup(ReplyMarkup):
    def __init__(self, keyboard: list, resize_keyboard=False, one_time_keyboard=False, selective=False):
        assert all(map(lambda x: isinstance(x, list), keyboard))
        assert all(map(lambda x: all(map(lambda z: isinstance(z, KeyboardButton), x)), keyboard))
        super().__init__(keyboard=keyboard, resize_keyboard=resize_keyboard, one_time_keyboard=one_time_keyboard,
                         selective=selective)


class ReplyKeyboardHide(ReplyMarkup):
    def __init__(self, selective=False):
        super().__init__(hide_keyboard=True, selective=selective)


class ForceReply(ReplyMarkup):
    def __init__(self, selective=False):
        super().__init__(force_reply=True, selective=selective)


class ApiError(Exception):
    def __init__(self, code, description, *args, **kwargs):
        self.code = code
        self.description = description
        super().__init__('Api error: %s, %s' % (code, description), *args, **kwargs)


class ApiInternalError(Exception):
    pass
