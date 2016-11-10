from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from tobot.helpers import report_botan


@coroutine
@CommandFilterTextCmd('/start')
def start_command(bot, message):
    report_botan(message, 'slave_start')
    username = message['from']['username']
    if message['from'].get('first_name', '').strip():
        username = message['from']['first_name'].strip()

        if message['from'].get('last_name', '').strip():
            username += ' ' + message['from']['last_name'].strip()

    username = username.replace('_', r'\_').replace('*', r'\*').replace('`', r'\`').replace('[', r'\[')
    msg = bot.settings['start'].replace('%user%', username)
    try:
        yield bot.send_message(msg, reply_to_message=message, parse_mode=bot.PARSE_MODE_MD,
                               disable_web_page_preview=not bot.settings['start_web_preview'])
    except:
        yield bot.send_message(msg, reply_to_message=message,
                               disable_web_page_preview=not bot.settings['start_web_preview'])
