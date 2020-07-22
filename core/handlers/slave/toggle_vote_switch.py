from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.subordinate_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import report_botan, pgettext


@coroutine
@CommandFilterTextCmd('/togglevoteswitch')
@CommandFilterIsPowerfulUser()
def togglevoteswitch_command(bot, message):
    report_botan(message, 'subordinate_togglevoteswitch_cmd')
    if bot.settings.get('allow_vote_switch'):
        yield bot.update_settings(message['from']['id'], allow_vote_switch=False)
        yield bot.send_message(pgettext('Vote switching disabled', 'From now Moderators can NOT switch their votes'),
                               reply_to_message=message)
    else:
        yield bot.update_settings(message['from']['id'], allow_vote_switch=True)
        yield bot.send_message(pgettext('Vote switching enabled', 'From now Moderators can switch their votes'),
                               reply_to_message=message)
