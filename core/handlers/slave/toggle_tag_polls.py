from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import report_botan, pgettext


@coroutine
@CommandFilterTextCmd('/toggletagpolls')
@CommandFilterIsPowerfulUser()
def toggletagpolls_command(bot, message):
    report_botan(message, 'slave_toggletagpolls_cmd')
    if bot.settings.get('tag_polls'):
        yield bot.update_settings(message['from']['id'], tag_polls=False)
        yield bot.send_message(pgettext('Polls tagging disabled', 'State tags shall not pass.'),
                               reply_to_message=message)
    else:
        yield bot.update_settings(message['from']['id'], tag_polls=True)
        yield bot.send_message(pgettext('Polls tagging enabled', 'State tags will be added to future polls.'),
                               reply_to_message=message)
