from tornado.gen import coroutine

from tobot import CommandFilterTextAny, CommandFilterCallbackQueryRegexp
from core.slave_command_filters import CommandFilterIsModerationChat
from tobot.helpers import pgettext, report_botan
from tobot.telegram import ForceReply


@coroutine
@CommandFilterIsModerationChat()
@CommandFilterCallbackQueryRegexp(r'reply_(?P<chat_id>\d+)_(?P<message_id>\d+)')
def reply_command(bot, callback_query, chat_id, message_id):
    report_botan(callback_query, 'slave_reply_cmd')
    msg = pgettext('Reply message request', 'What message should I send to user, @{moderator_username}?') \
        .format(moderator_username=callback_query['from'].get('username', callback_query['from']['id']))
    yield bot.send_message(msg, chat_id=bot.moderator_chat_id, reply_markup=ForceReply(True))
    yield bot.answer_callback_query(callback_query['id'])
    return {
        'chat_id': chat_id,
        'message_id': message_id,
    }


@coroutine
@CommandFilterTextAny()
def plaintext_reply_handler(bot, message, chat_id, message_id):
    msg = message['text'].strip()
    if len(msg) < 10:
        report_botan(message, 'slave_reply_short_msg')
        yield bot.send_message(pgettext('Reply message is too short', 'Message is too short (10 symbols required), try '
                                                                      'again or send /cancel'),
                               reply_to_message=message, reply_markup=ForceReply(True))
    else:
        try:
            yield bot.send_message(msg, chat_id=chat_id, reply_to_message_id=message_id)
            yield bot.send_message(pgettext('Reply delivery confirmation', 'Message sent'), reply_to_message=message)
        except Exception as e:
            yield bot.send_message(pgettext('Reply failed', 'Failed: {reason}').format(reason=str(e)),
                                   reply_to_message=message)

        return True
