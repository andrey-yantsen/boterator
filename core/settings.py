import os

from tornado.locale import get_supported_locales, load_gettext_translations
from babel import Locale
from helpers import pgettext, Emoji

DEFAULT_SLAVE_SETTINGS = {
    'delay': 15,
    'votes': 2,
    'vote_timeout': 24,
    'text_min': 50,
    'text_max': 1000,
    'start': pgettext('Default start message', "Just enter your message, and we're ready."),
    'hello': pgettext('Default channel-hello message',
                      'Hi there, guys! Now it is possible to publish messages in this channel by '
                      'any of you. All you need to do — is to write a message to me (bot named '
                      '@{bot_username}), and it will be published after verification by our team.'),
    'public_vote': True,
    'power': False,
    'content_status': {
        'text': True,
        'photo': False,
        'voice': False,
        'video': False,
        'audio': False,
        'document': False,
        'sticker': False,
        'gif': False,
    },
}

supported_locales = sorted(get_supported_locales())
LANGUAGE_LIST = []
for locale in supported_locales:
    l = Locale.parse(locale)
    locale_name = l.display_name[0].upper() + l.display_name[1:]
    if locale in Emoji.FLAGS:
        locale_name = Emoji.FLAGS[locale] + ' ' + locale_name
    LANGUAGE_LIST.append((locale, locale_name))
LANGUAGE_LIST = tuple(LANGUAGE_LIST)
