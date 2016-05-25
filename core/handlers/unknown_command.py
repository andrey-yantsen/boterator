from tornado.gen import coroutine

from core.bot import CommandFilterAny
from helpers import pgettext


@coroutine
@CommandFilterAny()
def unknown_command(bot, *args, **kwargs):
    reply_to = dict()
    if kwargs.get('message'):
        reply_to['reply_to_message'] = kwargs['message']
    elif kwargs.get('callback_query'):
        reply_to['chat_id'] = kwargs['callback_query']['message']['chat']['id']
    else:
        return False
    yield bot.send_message(pgettext('Unknown command', 'I have no idea what a hell do you want from me, sorry :('),
                           **reply_to)
