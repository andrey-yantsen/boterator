from tornado.gen import coroutine

from core.bot import CommandFilterTextCmd
from helpers import report_botan


@coroutine
@CommandFilterTextCmd('/start')
def start_command(bot, message):
    report_botan(message, 'slave_start')
    try:
        yield bot.send_message(bot.settings['start'], reply_to_message=message, parse_mode=bot.PARSE_MODE_MD)
    except:
        yield bot.send_message(bot.settings['start'], reply_to_message=message)
