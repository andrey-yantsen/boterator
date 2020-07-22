from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.subordinate_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import pgettext
from tobot.telegram import ForceReply


@coroutine
@CommandFilterTextCmd('/settextlimits')
@CommandFilterIsPowerfulUser()
def settextlimits_command(bot, message):
    yield bot.send_message(pgettext('New length limits request', 'Please enter new value for length limits formatted '
                                                                 'like `{min_length}..{max_length}` (e.g. `1..10`)'),
                           reply_to_message=message, parse_mode=bot.PARSE_MODE_MD, reply_markup=ForceReply(True))
    return True


@coroutine
def plaintext_textlimits_handler(bot, message):
    limits = message['text'].strip().split('..')

    if len(limits) == 2 and limits[0].isdigit() and limits[1].isdigit():
        limits[0] = int(limits[0])
        limits[1] = int(limits[1])

        if limits[0] < 1:
            yield bot.send_message(pgettext('Bottom limit is too low', 'Bottom limit must be greater than 0'),
                                   reply_to_message=message, reply_markup=ForceReply(True))
        elif limits[1] <= limits[0]:
            yield bot.send_message(pgettext('Top limit is too low', 'Top limit must be greater than bottom one'),
                                   reply_to_message=message, reply_markup=ForceReply(True))
        else:
            yield bot.update_settings(message['from']['id'], text_min=limits[0], text_max=limits[1])
            yield bot.send_message(pgettext('Text limits changed successfully', 'Limits updated'),
                                   reply_to_message=message)
            return True
    else:
        yield bot.send_message(pgettext('Non-well formated text limits provided',
                                        'Please use following format: `{min_length}..{max_length}` (e.g. `1..10`), or '
                                        'send /cancel'), reply_to_message=message,
                               parse_mode=bot.PARSE_MODE_MD, reply_markup=ForceReply(True))
