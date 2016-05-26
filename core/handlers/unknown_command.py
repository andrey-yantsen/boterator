from tornado.gen import coroutine

from tobot import CommandFilterAny
from tobot.helpers import pgettext


@coroutine
@CommandFilterAny()
def unknown_command(bot, *args, **kwargs):
    message = pgettext('Unknown command', 'I have no idea what a hell do you want from me, sorry :(')
    if kwargs.get('message'):
        yield bot.send_message(message, reply_to_message=kwargs['message'])
    elif kwargs.get('callback_query'):
        yield bot.answer_callback_query(kwargs['callback_query']['message']['chat']['id'], message)
    else:
        return False
