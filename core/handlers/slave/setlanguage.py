from itertools import groupby

from math import floor

from tornado.gen import coroutine

from tobot import CommandFilterTextCmd, CommandFilterTextAny
from core.settings import LANGUAGE_LIST
from core.slave_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import Emoji, pgettext
from tobot.telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardHide


def get_keyboard(with_back: bool):
    keyboard_rows = []

    for row_id, languages in groupby(enumerate(LANGUAGE_LIST), lambda l: floor(l[0] / 2)):
        keyboard_rows.append([
                                 KeyboardButton(lang_name)
                                 for lang_idx, (lang_code, lang_name) in languages
                                 ])

    if with_back:
        keyboard_rows.append([KeyboardButton(Emoji.END_WITH_LEFTWARDS_ARROW_ABOVE)])

    return ReplyKeyboardMarkup(keyboard_rows, resize_keyboard=True, selective=True)


@coroutine
@CommandFilterTextCmd('/setlanguage')
@CommandFilterIsPowerfulUser()
def setlanguage(bot, message):
    yield bot.send_message(pgettext('Change language prompt', 'Select your language'),
                           reply_to_message=message, reply_markup=get_keyboard(True))
    return True


@coroutine
@CommandFilterTextAny()
def setlanguage_plaintext(bot, message, **kwargs):
    languages = {
        lang_name: lang_code
        for lang_code, lang_name in LANGUAGE_LIST
    }

    if message['text'] in languages:
        yield bot.update_settings(message['from']['id'], locale=languages[message['text']])
        yield bot.send_message(pgettext('Language changed', 'Language changed'),
                               reply_to_message=message, reply_markup=ReplyKeyboardHide())
        return True
    else:
        yield bot.send_message(pgettext('Invalid user response', 'Wrong input'), reply_to_message=message)
