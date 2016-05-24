from tornado.gen import coroutine

from core.bot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsPowerfulUser
from helpers import report_botan, pgettext
from telegram import ForceReply


@coroutine
@CommandFilterTextCmd('/setstartmessage')
@CommandFilterIsPowerfulUser()
def setstartmessage_command(bot, message):
    report_botan(message, 'slave_setstartmessage_cmd')
    yield bot.send_message(pgettext('New start message request', 'Set new start message'), reply_to_message=message,
                           reply_markup=ForceReply(True))
    return True


@coroutine
def plaintext_startmessage_handler(bot, message):
    if message['text'] and len(message['text'].strip()) > 10:
        report_botan(message, 'slave_setstartmessage')
        yield bot.update_settings(message['from']['id'], start=message['text'].strip())
        yield bot.send_message(pgettext('Start message successfully changed', 'Start message updated'),
                               reply_to_message=message)
        return True
    else:
        report_botan(message, 'slave_setstartmessage_invalid')
        yield bot.send_message(pgettext('Too short start message entered', 'Invalid start message, you should write at '
                                                                           'least 10 symbols. Try again or type '
                                                                           '/cancel'),
                               reply_to_message=message, reply_markup=ForceReply(True))
