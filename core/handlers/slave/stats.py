from datetime import datetime, timedelta

from babel.dates import format_date
from babel.numbers import format_number
from tornado.gen import coroutine

from tobot import CommandFilterTextCmd
from core.subordinate_command_filters import CommandFilterIsModerator
from tobot.helpers import pgettext, Emoji, npgettext, report_botan
from tobot.helpers.lazy_gettext import set_locale_recursive


@coroutine
@CommandFilterTextCmd('/stats')
@CommandFilterIsModerator()
def stats_command(bot, message):
    def format_top(rows, f: callable):
        ret = []
        for row_id, row in enumerate(rows):
            user_id, first_name, last_name = row[:3]
            row = row[3:]
            if first_name and last_name:
                user = first_name + ' ' + last_name
            elif first_name:
                user = first_name
            else:
                user = 'userid %s' % user_id

            ret.append(pgettext('Stats user item', '{row_id}. {user} - {rating_details}')
                       .format(row_id=row_id + 1, user=user, rating_details=f(row)))

        if not ret:
            ret.append(pgettext('No data for stats report', '{cross_mark} no data').format(cross_mark=Emoji.CROSS_MARK))

        return ret

    report_botan(message, 'subordinate_stats')

    period = message['text'][6:].strip()
    if period:
        if period.isdigit():
            period_end = datetime.now()
            period_begin = period_end - timedelta(days=int(period) - 1)
        elif ' ' in period and '-' in period:
            period = period.split(' ')
            try:
                period_begin = datetime.strptime(period[0], '%Y-%m-%d')
                period_end = datetime.strptime(period[1], '%Y-%m-%d')
            except:
                yield bot.send_message(pgettext('Invalid stats request', 'Invalid period provided, correct value: '
                                                                         '`/stats 2016-01-01 2016-01-13`'),
                                       reply_to_message=message, parse_mode=bot.PARSE_MODE_MD)
                return
        elif '-' in period:
            try:
                period_begin = datetime.strptime(period, '%Y-%m-%d')
                period_end = datetime.strptime(period, '%Y-%m-%d')
            except:
                yield bot.send_message(pgettext('Invalid stats request', 'Invalid period provided, correct value: '
                                                                         '`/stats 2016-01-01`'),
                                       reply_to_message=message, parse_mode=bot.PARSE_MODE_MD)
                return
        else:
            yield bot.send_message(pgettext('Invalid stats request', 'Invalid period provided, correct values: '
                                                                     '`/stats 2016-01-01 2016-01-13`, `/stats 5` for '
                                                                     'last 5 days or `/stats 2016-01-01`'),
                                   reply_to_message=message, parse_mode=bot.PARSE_MODE_MD)
            return
    else:
        period_end = datetime.now()
        period_begin = period_end - timedelta(days=6)

    period_begin = period_begin.replace(hour=0, minute=0, second=0)
    period_end = period_end.replace(hour=23, minute=59, second=59)

    yield bot.send_chat_action(message['chat']['id'], bot.CHAT_ACTION_TYPING)

    period_str = format_date(period_begin.date(), locale=bot.language) \
        if period_begin.strftime('%Y-%m-%d') == period_end.strftime('%Y-%m-%d') \
        else '%s - %s' % (format_date(period_begin.date(), locale=bot.language),
                          format_date(period_end.date(), locale=bot.language))

    lines = [
        pgettext('Stats header', 'Stats for {period}').format(period=period_str),
        '',
        pgettext('TOP type', 'TOP5 voters:'),
    ]

    query = """
        SELECT vh.user_id, u.first_name, u.last_name, count(*), SUM(vote_yes::INT) FROM votes_history vh
        JOIN incoming_messages im ON im.id = vh.message_id AND im.original_chat_id = vh.original_chat_id
        LEFT JOIN users u ON u.user_id = vh.user_id AND u.bot_id = im.bot_id
        WHERE im.bot_id = %s AND vh.created_at BETWEEN %s AND %s
        GROUP BY vh.user_id, u.first_name, u.last_name
        ORDER BY COUNT(*) DESC
        LIMIT 5
        """

    cur = yield bot.db.execute(query, (bot.bot_id, period_begin, period_end))
    votes_cnt=format_number(row[0], bot.language)
    votes_yes_cnt=format_number(row[1], bot.language)

    def format_top_votes(row):
        return npgettext('Votes count', '{votes_cnt} vote with {votes_yes_cnt} {thumb_up_sign} ({votes_percent}%)',
                         '{votes_cnt} votes with {votes_yes_cnt} {thumb_up_sign} ({votes_percent}%)',
                         row[0]).format(votes_cnt,
                                        votes_yes_cnt,
                                        thumb_up_sign=Emoji.THUMBS_UP_SIGN,
                                        votes_percent=100 * votes_yes_cnt // votes_cnt)

    lines += format_top(cur.fetchall(), format_top_votes)
    lines.append('')
    lines.append(pgettext('TOP type', 'TOP5 users by messages count:'))

    query = """
        SELECT im.owner_id, u.first_name, u.last_name, count(*) FROM incoming_messages im
        LEFT JOIN users u ON u.user_id = im.owner_id AND u.bot_id = im.bot_id
        WHERE im.bot_id = %s AND im.created_at BETWEEN %s AND %s
        GROUP BY im.owner_id, u.first_name, u.last_name
        ORDER BY COUNT(*) DESC
        LIMIT 5
        """

    cur = yield bot.db.execute(query, (bot.bot_id, period_begin, period_end))

    def format_top_messages(row):
        return npgettext('Messages count', '{messages_cnt} message', '{messages_cnt} messages', row[0]) \
            .format(messages_cnt=format_number(row[0], bot.language))

    lines += format_top(cur.fetchall(), format_top_messages)
    lines.append('')
    lines.append(pgettext('TOP type', 'TOP5 users by published messages count:'))

    query = """
        SELECT im.owner_id, u.first_name, u.last_name, count(*) FROM incoming_messages im
        LEFT JOIN users u ON u.user_id = im.owner_id AND u.bot_id = im.bot_id
        WHERE im.bot_id = %s AND im.created_at BETWEEN %s AND %s AND im.is_published = TRUE
        GROUP BY im.owner_id, u.first_name, u.last_name
        ORDER BY COUNT(*) DESC
        LIMIT 5
        """

    cur = yield bot.db.execute(query, (bot.bot_id, period_begin, period_end))

    lines += format_top(cur.fetchall(), format_top_messages)
    lines.append('')
    lines.append(pgettext('TOP type', 'TOP5 users by declined messages count:'))

    query = """
        SELECT im.owner_id, u.first_name, u.last_name, count(*) FROM incoming_messages im
        LEFT JOIN users u ON u.user_id = im.owner_id AND u.bot_id = im.bot_id
        WHERE im.bot_id = %s AND im.created_at BETWEEN %s AND %s AND is_voting_fail = TRUE
        GROUP BY im.owner_id, u.first_name, u.last_name
        ORDER BY COUNT(*) DESC
        LIMIT 5
        """

    cur = yield bot.db.execute(query, (bot.bot_id, period_begin, period_end))

    lines += format_top(cur.fetchall(), format_top_messages)

    msg = '\n'.join(set_locale_recursive(lines, bot.locale))

    yield bot.send_message(msg, reply_to_message=message)
