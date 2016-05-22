from tornado.gen import coroutine

from helpers import pgettext


@coroutine
def unknown_command(bot, message):
    yield bot.send_message(pgettext('Unknown command', 'I have no idea what a hell do you want from me, sorry :('),
                           reply_to_message=message)
