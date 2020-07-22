from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.subordinate_command_filters import CommandFilterIsPowerfulUser
from tobot.helpers import report_botan, pgettext, npgettext, Emoji


@coroutine
@CommandFilterIsPowerfulUser()
@CommandFilterTextCmd('/help')
def help_command(bot, message):
    report_botan(message, 'subordinate_help')
    delay_str = npgettext('Delay between channel messages', '{delay} minute', '{delay} minutes', bot.settings['delay'])
    timeout_str = npgettext('Voting timeout', '{timeout} hour', '{timeout} hours', bot.settings['vote_timeout'])
    power_state = 'on' if bot.settings.get('power') else 'off'
    power_state_str = pgettext('Boolean settings', power_state)
    public_vote_state = 'on' if bot.settings.get('public_vote') else 'off'
    public_vote_state_str = pgettext('Boolean settings', public_vote_state)
    selfvote_state = 'on' if bot.settings.get('selfvote') else 'off'
    selfvote_state_str = pgettext('Boolean settings', selfvote_state)
    start_web_preview_state = 'on' if bot.settings.get('start_web_preview') else 'off'
    start_web_preview_state_str = pgettext('Boolean settings', start_web_preview_state)
    voteswitch_state = 'on' if bot.settings.get('allow_vote_switch') else 'off'
    voteswitch_state_str = pgettext('Boolean settings', voteswitch_state)
    tag_polls_state = 'on' if bot.settings.get('tag_polls') else 'off'
    tag_polls_state_str = pgettext('Boolean settings', tag_polls_state)

    if bot.settings.get('msg_freq_limit'):
        fl = bot.settings['msg_freq_limit']
        freq_limit_msg_str = npgettext('Messages count', '{msg} message', '{msg} messages', fl[0]).format(msg=fl[0])
        freq_limit_days_str = npgettext('Days', '{n} day', '{n} days', fl[1]).format(n=fl[1])
        freq_limit_str = pgettext('Frequency limit', '{messages_str} per {days_str}') \
            .format(messages_str=freq_limit_msg_str, days_str=freq_limit_days_str)
    else:
        freq_limit_str = pgettext('No frequency limit', 'unlimited')

    msg = pgettext('/help command response', 'bot.help.response') \
        .format(current_delay_with_minutes=delay_str.format(delay=bot.settings['delay']),
                current_votes_required=bot.settings['votes'],
                current_timeout_with_hours=timeout_str.format(timeout=bot.settings['vote_timeout']),
                thumb_up_sign=Emoji.THUMBS_UP_SIGN, thumb_down_sign=Emoji.THUMBS_DOWN_SIGN,
                current_start_message=bot.settings['start'], power_state=power_state_str,
                public_vote_state=public_vote_state_str,
                current_text_limit={'min': bot.settings['text_min'], 'max': bot.settings['text_max']},
                selfvote_state=selfvote_state_str, start_web_preview_state=start_web_preview_state_str,
                current_freqlimit=freq_limit_str, voteswitch_state=voteswitch_state_str,
                tag_polls_state=tag_polls_state_str)

    try:
        yield bot.send_message(msg, reply_to_message=message, parse_mode=bot.PARSE_MODE_MD,
                               disable_web_page_preview=True)
    except:
        yield bot.send_message(msg, reply_to_message=message, disable_web_page_preview=True)


def __messages():
    pgettext('Boolean settings', 'on')
    pgettext('Boolean settings', 'off')
