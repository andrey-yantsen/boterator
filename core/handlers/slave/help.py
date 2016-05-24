from tornado.gen import coroutine

from core.bot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsPowerfulUser
from helpers import report_botan, pgettext, npgettext, Emoji


@coroutine
@CommandFilterIsPowerfulUser()
@CommandFilterTextCmd('/help')
def help_command(bot, message):
    report_botan(message, 'slave_help')
    delay_str = npgettext('Delay between channel messages', '{delay} minute', '{delay} minutes', bot.settings['delay'])
    timeout_str = npgettext('Voting timeout', '{timeout} hour', '{timeout} hours', bot.settings['vote_timeout'])
    power_state = 'yes' if bot.settings.get('power') else 'no'
    power_state_str = pgettext('Moderator\'s ability to alter settings', power_state)
    msg = pgettext('/help command response', 'bot.help.response') \
        .format(current_delay_with_minutes=delay_str.format(delay=bot.settings['delay']),
                current_votes_required=bot.settings['votes'],
                current_timeout_with_hours=timeout_str.format(timeout=bot.settings['vote_timeout']),
                thumb_up_sign=Emoji.THUMBS_UP_SIGN, thumb_down_sign=Emoji.THUMBS_DOWN_SIGN,
                current_start_message=bot.settings['start'], power_state=power_state_str,
                current_text_limit={'min': bot.settings['text_min'], 'max': bot.settings['text_max']})

    try:
        yield bot.send_message(msg, reply_to_message=message, parse_mode=bot.PARSE_MODE_MD)
    except:
        yield bot.send_message(msg, reply_to_message=message)


def __messages():
    pgettext('Moderator\'s ability to alter settings', 'yes')
    pgettext('Moderator\'s ability to alter settings', 'no')
