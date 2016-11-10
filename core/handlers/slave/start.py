from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from tobot.helpers import report_botan


@coroutine
@CommandFilterTextCmd('/start')
def start_command(bot, message):
    report_botan(message, 'slave_start')
    try:
        yield bot.send_message(bot.settings['start'], reply_to_message=message, parse_mode=bot.PARSE_MODE_MD,
                               disable_web_page_preview=not bot.settings['start_web_preview'])
    except:
        yield bot.send_message(bot.settings['start'], reply_to_message=message,
                               disable_web_page_preview=not bot.settings['start_web_preview'])
