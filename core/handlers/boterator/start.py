from tornado.gen import coroutine

from core.bot import CommandFilterTextCmd
from helpers import pgettext, report_botan


@coroutine
@CommandFilterTextCmd('/start')
def start_command(bot, message):
    report_botan(message, 'boterator_start')
    yield bot.send_message(pgettext('Boterator`s /start response', 'Hello, this is Boterator. In order to start ask '
                                                                   '@BotFather to create a new bot. Then feel free to '
                                                                   'use /reg command to register new bot using token.'),
                           reply_to_message=message)
