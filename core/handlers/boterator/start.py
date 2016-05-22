from tornado.gen import coroutine

from helpers import pgettext, report_botan


@coroutine
def start_command(bot, message):
    report_botan(message, 'boterator_start')
    yield bot.send_message(pgettext('Boterator: /start response', 'Hello, this is Boterator. In order to start ask '
                                                                  '@BotFather to create a new bot. Then feel free to '
                                                                  'use /reg command to register new bot using token.'),
                           reply_to_message=message)
