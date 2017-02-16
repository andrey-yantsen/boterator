from tobot.telegram import ApiError
from tornado.gen import coroutine

from tobot import CommandFilterAny
from tobot.helpers import pgettext


@coroutine
@CommandFilterAny()
def unknown_command(bot, *args, **kwargs):
    if kwargs.get('message'):
        msg = kwargs['message']
        if hasattr(bot, 'moderator_chat_id') and msg['chat']['id'] == bot.moderator_chat_id and \
            msg.get('reply_to_message', {}).get('from', {}).get('id') != bot.id:
            return False

    message = pgettext('Unknown command', 'I have no idea what a hell do you want from me, sorry :(')
    try:
        if kwargs.get('message'):
            yield bot.send_message(message, reply_to_message=kwargs['message'])
        elif kwargs.get('callback_query'):
            yield bot.answer_callback_query(kwargs['callback_query']['message']['chat']['id'], message)
        else:
            return False
    except ApiError as e:
        if e.code != 403:
            raise
