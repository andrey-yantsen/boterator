from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.subordinate_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import pgettext
from tobot.telegram import ForceReply


@coroutine
@CommandFilterTextCmd('/setfreqlimit')
@CommandFilterIsPowerfulUser()
def setfreqlimit_command(bot, message):
    yield bot.send_message(pgettext('New frequency limits request', 'Please enter new value for messages frequency '
                                                                    'limits formatted like `{messages_count}/{days}`, '
                                                                    'or `0` to disable limits '
                                                                    '(e.g. `1/7` to set limit to 1 message per week)'),
                           reply_to_message=message, parse_mode=bot.PARSE_MODE_MD, reply_markup=ForceReply(True))
    return True


@coroutine
def plaintext_freqlimit_handler(bot, message):
    limits = message['text'].strip().split('/')

    if len(limits) == 1 and limits[0] == '0':
        yield bot.update_settings(message['from']['id'], msg_freq_limit=None)
        yield bot.send_message(pgettext('Limits reset', 'Limits reset'),
                               reply_to_message=message)
        return True
    elif len(limits) == 2 and limits[0].isdigit() and limits[1].isdigit():
        limits[0] = int(limits[0])
        limits[1] = int(limits[1])

        if limits[0] < 1:
            yield bot.send_message(pgettext('Msg limit is too low', 'Messages count limit must be greater than 0'),
                                   reply_to_message=message, reply_markup=ForceReply(True))
        elif limits[1] < 1:
            yield bot.send_message(pgettext('Days limit is too low', 'Days count must be greater than 0'),
                                   reply_to_message=message, reply_markup=ForceReply(True))
        else:
            yield bot.update_settings(message['from']['id'], msg_freq_limit=[limits[0], limits[1]])
            yield bot.send_message(pgettext('Limits changed successfully', 'Limits updated'),
                                   reply_to_message=message)
            return True
    else:
        yield bot.send_message(pgettext('Non-well formatted freq limits provided',
                                        'Please use following format: `{messages_count}/{days}` (e.g. `1/7`), or '
                                        'send /cancel'), reply_to_message=message,
                               parse_mode=bot.PARSE_MODE_MD, reply_markup=ForceReply(True))
