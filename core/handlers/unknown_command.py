from tornado.gen import coroutine

from core.bot import CommandFilterAny
from helpers import pgettext


@coroutine
@CommandFilterAny()
def unknown_command(bot, message, *args, **kwargs):
    yield bot.send_message(pgettext('Unknown command', 'I have no idea what a hell do you want from me, sorry :('),
                           reply_to_message=message)
