from tornado.gen import coroutine

from tobot import CommandFilterTextCmd, CommandFilterTextAny
from core.handlers.boterator.start import start_command
from core.handlers.boterator.setlanguage import get_keyboard, setlanguage_plaintext
from tobot.helpers import pgettext


@coroutine
@CommandFilterTextCmd('/start')
def setlanguage_at_start(bot, message):
    if bot.get_settings(message['from']['id']) != {}:
        return False

    yield bot.send_message(pgettext('Change language prompt', 'Select your language'),
                           reply_to_message=message, reply_markup=get_keyboard(False))
    return True


@coroutine
@CommandFilterTextAny()
def setlanguage_at_start_plaintext(bot, message):
    ret = yield setlanguage_plaintext(bot, message=message)
    if ret is True:
        yield start_command(bot, message=message)
        return True
