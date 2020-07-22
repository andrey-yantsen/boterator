from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.subordinate_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import pgettext, report_botan
from tobot.telegram import ForceReply


@coroutine
@CommandFilterTextCmd('/setvotes')
@CommandFilterIsPowerfulUser()
def setvotes_command(bot, message):
    report_botan(message, 'subordinate_setvotes_cmd')
    yield bot.send_message(
        pgettext('New required votes count request', 'Set new amount of required votes'),
        reply_to_message=message, reply_markup=ForceReply(True))
    return True


@coroutine
def plaintext_votes_handler(bot, message):
    if message['text'].isdigit() and int(message['text']) > 0:
        report_botan(message, 'subordinate_setvotes')
        yield bot.update_settings(message['from']['id'], votes=int(message['text']))
        yield bot.send_message(pgettext('Required votes count successfully changed', 'Required votes '
                                                                                     'amount updated'),
                               reply_to_message=message)
        return True
    else:
        report_botan(message, 'subordinate_setvotes_invalid')
        yield bot.send_message(pgettext('Invalid votes amount value', 'Invalid votes amount value. Try again or type '
                                                                      '/cancel'),
                               reply_to_message=message, reply_markup=ForceReply(True))
