from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import report_botan, pgettext


@coroutine
@CommandFilterTextCmd('/togglepower')
@CommandFilterIsPowerfulUser()
def togglepower_command(bot, message):
    report_botan(message, 'slave_togglepower_cmd')
    if bot.settings.get('power'):
        yield bot.update_settings(message['from']['id'], power=False)
        yield bot.send_message(pgettext('Power mode disabled', 'From now other chat users can not modify bot settings'),
                               reply_to_message=message)
    else:
        yield bot.update_settings(message['from']['id'], power=True)
        yield bot.send_message(pgettext('Power mode enabled', 'From now other chat users can modify bot settings (only '
                                                              'inside moderators chat)'),
                               reply_to_message=message)
