from tornado.gen import coroutine

from core.bot import CommandFilterText
from helpers import Emoji
from helpers import pgettext
from telegram import ReplyKeyboardHide


@coroutine
@CommandFilterText(Emoji.END_WITH_LEFTWARDS_ARROW_ABOVE)
def emoji_end(bot, message, **kwargs):
    yield bot.send_message(pgettext('Reply to END button press on a keyboard', 'Ok'),
                           reply_to_message=message, reply_markup=ReplyKeyboardHide())
    return True
