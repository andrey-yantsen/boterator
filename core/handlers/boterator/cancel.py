from tornado.gen import coroutine

from helpers import pgettext
from telegram import ReplyKeyboardHide


@coroutine
def cancel_command(bot, message, **kwargs):
    yield bot.send_message(pgettext('Boterator: /cancel response', 'Oka-a-a-a-a-ay.'),
                           reply_to_message=message, reply_markup=ReplyKeyboardHide())
    return True
