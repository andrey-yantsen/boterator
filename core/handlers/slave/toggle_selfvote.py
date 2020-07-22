from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.subordinate_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import report_botan, pgettext


@coroutine
@CommandFilterTextCmd('/toggleselfvote')
@CommandFilterIsPowerfulUser()
def toggleselfvote_command(bot, message):
    report_botan(message, 'subordinate_toggleselfvote_cmd')
    if bot.settings.get('selfvote'):
        yield bot.update_settings(message['from']['id'], selfvote=False)
        yield bot.send_message(pgettext('Self-vote disabled', 'From now moderators WILL NOT be able to vote for own '
                                                              'messages.'),
                               reply_to_message=message)
    else:
        yield bot.update_settings(message['from']['id'], selfvote=True)
        yield bot.send_message(pgettext('Self-vote enabled', 'From now moderators WILL BE able to vote for own '
                                                             'messages.'),
                               reply_to_message=message)
