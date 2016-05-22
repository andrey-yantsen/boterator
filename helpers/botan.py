from ujson import loads, dumps
from urllib.parse import urlencode

from tornado.gen import coroutine
from tornado.httpclient import AsyncHTTPClient
from tornado.options import options, define


@coroutine
def report_botan(message, event_name):
    token = options.botan_token
    if not token:
        return

    uid = message['from']['id']

    params = {
        'token': token,
        'uid': uid,
        'name': event_name,
    }

    resp = yield AsyncHTTPClient().fetch('https://api.botan.io/track?' + urlencode(params), body=dumps(message),
                                         method='POST')

    return loads(resp.body.decode('utf-8'))


define('botan_token', type=str, help='Bot\'s botan.io token')
