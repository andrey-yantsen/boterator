from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from tobot.helpers import pgettext
from tobot.telegram import ReplyKeyboardHide


@coroutine
@CommandFilterTextCmd('/cancel')
def cancel_command(bot, message, **kwargs):
    yield bot.send_message(pgettext('Pending command cancelled', 'Oka-a-a-a-a-ay.'),
                           reply_to_message=message, reply_markup=ReplyKeyboardHide())
    return True
