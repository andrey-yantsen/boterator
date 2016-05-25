from tornado.gen import coroutine

from core.bot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsPowerfulUser
from helpers import report_botan, pgettext


@coroutine
@CommandFilterTextCmd('/togglevote')
@CommandFilterIsPowerfulUser()
def togglevote_command(bot, message):
    report_botan(message, 'slave_togglevote_cmd')
    if bot.settings.get('public_vote'):
        yield bot.update_settings(message['from']['id'], public_vote=False)
        yield bot.send_message(pgettext('Vote status displaying disabled', 'From now other chat users WILL NOT see '
                                                                           'current votes distribution.'),
                               reply_to_message=message)
    else:
        yield bot.update_settings(message['from']['id'], public_vote=True)
        yield bot.send_message(pgettext('Vote status displaying enabled', 'From now other chat users WILL see current '
                                                                          'votes distribution.'),
                               reply_to_message=message)
