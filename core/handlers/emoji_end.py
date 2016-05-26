from tornado.gen import coroutine

from tobot import CommandFilterText
from tobot.helpers import Emoji
from tobot.helpers import pgettext
from tobot.telegram import ReplyKeyboardHide


@coroutine
@CommandFilterText(Emoji.END_WITH_LEFTWARDS_ARROW_ABOVE)
def emoji_end(bot, message, **kwargs):
    yield bot.send_message(pgettext('Reply to END button press on a keyboard', 'Ok'),
                           reply_to_message=message, reply_markup=ReplyKeyboardHide())
    return True
