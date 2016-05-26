from itertools import groupby

from math import floor
from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import Emoji, pgettext, report_botan
from tobot.telegram import ReplyKeyboardMarkup, KeyboardButton


TYPES = ('text', 'photo', 'video', 'audio', 'document', 'sticker', 'voice', 'gif')


def types_translations(bot):
    ret = {}
    for t in TYPES:
        ret[t] = pgettext('Content type', t[0].upper() + t[1:])
        ret[t].locale = bot.locale
        ret[t] = str(ret[t])

    return ret


def build_contenttype_keyboard(bot):
    content_status = bot.settings['content_status']
    marks = {
        True: Emoji.CIRCLED_BULLET,
        False: Emoji.MEDIUM_SMALL_WHITE_CIRCLE,
    }

    rows = []
    translations = types_translations(bot)
    for row_id, types in groupby(enumerate(TYPES), lambda x: floor(x[0] / 3)):
        row = []
        for _, t in types:
            row.append(KeyboardButton('%s %s' % (marks[content_status[t]], translations[t])))
        rows.append(row)

    return ReplyKeyboardMarkup(rows + [[KeyboardButton(Emoji.END_WITH_LEFTWARDS_ARROW_ABOVE)]], resize_keyboard=True,
                               selective=True)


@coroutine
@CommandFilterTextCmd('/setallowed')
@CommandFilterIsPowerfulUser()
def change_allowed_command(bot, message):
    report_botan(message, 'slave_change_allowed_cmd')
    yield bot.send_message(pgettext('/changeallowed response', 'You can see current status on keyboard, just click on '
                                                               'content type to change it\'s status'),
                           reply_to_message=message, reply_markup=build_contenttype_keyboard(bot))
    return True


@coroutine
def plaintext_contenttype_handler(bot, message):
    try:
        split = message['text'].split(' ')
        action_type, content_type = split[0], ' '.join(split[1:])

        if action_type == Emoji.MEDIUM_SMALL_WHITE_CIRCLE:
            action_type = True
        elif action_type == Emoji.CIRCLED_BULLET:
            action_type = False
        else:
            raise ValueError()

        updated_content_type = content_type[0].upper() + content_type[1:].lower()

        content_status = bot.settings['content_status']

        translations = types_translations(bot)
        content_types_list = dict(zip(translations.values(), translations.keys()))

        if updated_content_type in content_types_list:
            content_type_raw = content_types_list[updated_content_type]
            content_status[content_type_raw] = action_type
            yield bot.update_settings(message['from']['id'], content_status=content_status)
        else:
            raise ValueError()

        action_text = 'enable' if action_type else 'disable'

        report_botan(message, 'slave_content_' + content_type_raw + '_' + action_text)

        msg = content_type_raw[0].upper() + content_type_raw[1:] + 's ' + action_text + 'd'

        yield bot.send_message(pgettext('Content type enabled/disabled', msg), reply_to_message=message,
                               reply_markup=build_contenttype_keyboard(bot))
    except:
        yield bot.send_message(pgettext('Invalid user response', 'Wrong input'), reply_to_message=message)


def __messages():
    pgettext('Content type', 'Text')
    pgettext('Content type', 'Photo')
    pgettext('Content type', 'Video')
    pgettext('Content type', 'Audio')
    pgettext('Content type', 'Document')
    pgettext('Content type', 'Sticker')
    pgettext('Content type', 'Voice')
    pgettext('Content type', 'Gif')

    pgettext('Content type enabled/disabled', 'Texts enabled')
    pgettext('Content type enabled/disabled', 'Texts disabled')
    pgettext('Content type enabled/disabled', 'Photos enabled')
    pgettext('Content type enabled/disabled', 'Photos disabled')
    pgettext('Content type enabled/disabled', 'Videos enabled')
    pgettext('Content type enabled/disabled', 'Videos disabled')
    pgettext('Content type enabled/disabled', 'Audios enabled')
    pgettext('Content type enabled/disabled', 'Audios disabled')
    pgettext('Content type enabled/disabled', 'Voices enabled')
    pgettext('Content type enabled/disabled', 'Voices disabled')
    pgettext('Content type enabled/disabled', 'Stickers enabled')
    pgettext('Content type enabled/disabled', 'Stickers disabled')
    pgettext('Content type enabled/disabled', 'Documents enabled')
    pgettext('Content type enabled/disabled', 'Documents disabled')
    pgettext('Content type enabled/disabled', 'Gifs enabled')
    pgettext('Content type enabled/disabled', 'Gifs disabled')
