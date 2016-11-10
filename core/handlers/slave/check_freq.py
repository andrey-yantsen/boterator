import datetime
from tobot import CommandFilterAny
from tobot.helpers import npgettext
from tobot.helpers import pgettext
from tornado.gen import coroutine


@coroutine
def get_messages_count(db, user_id, bot_id, days_limit):
    d = datetime.datetime.now() - datetime.timedelta(days=days_limit)

    query = """
        SELECT COUNT(*) FROM incoming_messages
        WHERE bot_id = %s AND owner_id = %s AND created_at >= %s
    """

    cur = yield db.execute(query, (bot_id, user_id, d))
    return cur.fetchone()[0]


@coroutine
@CommandFilterAny()
def check_freq(bot, **kwargs):
    if 'message' not in kwargs or not bot.settings.get('msg_freq_limit') or \
                    kwargs['message']['chat']['id'] == bot.moderator_chat_id:
        return False

    fl = bot.settings['msg_freq_limit']

    msgs = yield get_messages_count(bot.db, kwargs['message']['from']['id'], bot.bot_id, fl[1])
    if msgs < fl[0]:
        return False

    freq_limit_msg_str = npgettext('Messages count', '{msg} message', '{msg} messages', fl[0]).format(msg=fl[0])
    freq_limit_days_str = npgettext('Days', '{n} day', '{n} days', fl[1]).format(n=fl[1])
    freq_limit_str = pgettext('Frequency limit', '{messages_str} per {days_str}') \
        .format(messages_str=freq_limit_msg_str, days_str=freq_limit_days_str)

    msg = pgettext('Out of limits', 'Unfortunately, you\'re out of limits! You can send only {freq_limit_str}')

    yield bot.send_message(msg.format(freq_limit_str=freq_limit_str), reply_to_message=kwargs['message'])
