from tornado.gen import coroutine

from core.bot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsPowerfulUser
from helpers import pgettext, report_botan
from telegram import ForceReply


@coroutine
@CommandFilterTextCmd('/settimeout')
@CommandFilterIsPowerfulUser()
def settimeout_command(bot, message):
    report_botan(message, 'slave_settimeout_cmd')
    yield bot.send_message(pgettext('New voting duration request', 'Set new voting duration value (in hours, only a '
                                                                   'digits)'),
                           reply_to_message=message, reply_markup=ForceReply(True))
    return True


@coroutine
def plaintext_timeout_handler(bot, message):
    if message['text'].isdigit() and int(message['text']) > 0:
        report_botan(message, 'slave_settimeout')
        yield bot.update_settings(message['from']['id'], vote_timeout=int(message['text']))
        yield bot.send_message(pgettext('Voting duration successfully changed', 'Voting duration updated'),
                               reply_to_message=message)
        return True
    else:
        report_botan(message, 'slave_settimeout_invalid')
        yield bot.send_message(pgettext('Invalid voting duration value', 'Invalid voting duration value. Try again or '
                                                                         'type /cancel'),
                               reply_to_message=message, reply_markup=ForceReply(True))
