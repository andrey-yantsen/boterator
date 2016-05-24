from tornado.gen import coroutine

from core.bot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsPowerfulUser
from helpers import report_botan, pgettext
from telegram import ForceReply


@coroutine
@CommandFilterIsPowerfulUser()
@CommandFilterTextCmd('/setdelay')
def setdelay_command(bot, message):
    report_botan(message, 'slave_setdelay_cmd')
    yield bot.send_message(pgettext('New delay request', 'Set new delay value for messages posting (in minutes)'),
                           reply_to_message=message, reply_markup=ForceReply(True))
    return True


@coroutine
def plaintext_delay_handler(bot, message):
    if message['text'].isdigit() and int(message['text']) >= 0:
        report_botan(message, 'slave_setdelay')
        yield bot.update_settings(message['from']['id'], delay=int(message['text']))
        yield bot.send_message(pgettext('Messages delay successfully changed', 'Delay value updated'),
                               reply_to_message=message)
        return True
    else:
        report_botan(message, 'slave_setdelay_invalid')
        yield bot.send_message(pgettext('Invalid delay value', 'Invalid delay value. Try again or type /cancel'),
                               reply_to_message=message, reply_markup=ForceReply(True))
