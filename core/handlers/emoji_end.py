from tornado.gen import coroutine

from helpers import Emoji
from helpers import pgettext
from telegram import ReplyKeyboardHide


@coroutine
def emoji_end(bot, message, **kwargs):
    if message['text'] in (Emoji.END_WITH_LEFTWARDS_ARROW_ABOVE,):
        yield bot.send_message(pgettext('Reply to END button press on a keyboard', 'Ok'),
                               reply_to_message=message, reply_markup=ReplyKeyboardHide())
        return True
    return False
