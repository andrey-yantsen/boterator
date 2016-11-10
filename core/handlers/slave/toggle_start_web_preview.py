from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import report_botan, pgettext


@coroutine
@CommandFilterTextCmd('/toggle_start_web_preview')
@CommandFilterIsPowerfulUser()
def toggle_start_web_preview_command(bot, message):
    report_botan(message, 'slave_toggle_start_web_preview_cmd')
    if bot.settings.get('start_web_preview'):
        yield bot.update_settings(message['from']['id'], start_web_preview=False)
        yield bot.send_message(pgettext('Web preview disabled in /start', 'From now web previews WILL NOT BE generated '
                                                                          'for links in /start message.'),
                               reply_to_message=message)
    else:
        yield bot.update_settings(message['from']['id'], start_web_preview=True)
        yield bot.send_message(pgettext('Web preview enabled in /start', 'From now web previews WILL BE generated for '
                                                                         'links in /start message.'),
                               reply_to_message=message)
