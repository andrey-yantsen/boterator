from tornado.gen import coroutine

from tobot import CommandFilterTextAny, CommandFilterCallbackQueryRegexp
from core.slave_command_filters import CommandFilterIsModerationChat
from tobot.helpers import pgettext, report_botan
from tobot.telegram import ForceReply


@coroutine
@CommandFilterIsModerationChat()
@CommandFilterCallbackQueryRegexp(r'reject_(?P<chat_id>\d+)_(?P<message_id>\d+)')
def reject_command(bot, callback_query, chat_id, message_id):
    report_botan(callback_query, 'slave_reject_cmd')
    msg = pgettext('Reject message request', 'Please enter a reject reason, @{moderator_username}?') \
        .format(moderator_username=callback_query['from'].get('username', callback_query['from']['id']))
    fwd_id = yield bot.get_message_fwd_id(chat_id, message_id)
    yield bot.send_message(msg, chat_id=bot.moderator_chat_id, reply_markup=ForceReply(True),
                           reply_to_message_id=fwd_id)
    yield bot.answer_callback_query(callback_query['id'])
    return {
        'chat_id': chat_id,
        'message_id': message_id,
    }


@coroutine
@CommandFilterTextAny()
def plaintext_reject_handler(bot, message, chat_id, message_id):
    msg = message['text'].strip()
    if len(msg) < 10:
        report_botan(message, 'slave_reply_short_msg')
        yield bot.send_message(
            pgettext('Reject message is too short', 'Reject message is too short (10 symbols required), try '
                                                    'again or send /cancel'),
            reply_to_message=message, reply_markup=ForceReply(True))
    else:
        yield bot.decline_message({
            'chat': {
                'id': chat_id
            },
            'message_id': message_id
        }, 0, False)
    try:
        yield bot.send_message(pgettext('Message to user in case of rejection',
                                        "Your post has been rejected. "
                                        "Reason:\n> {reject_reason}").format(reject_reason=msg),
                               chat_id=chat_id, reply_to_message_id=message_id)
        yield bot.send_message(pgettext('Rejection delivery confirmation', 'Message sent and post rejected'),
                               reply_to_message=message)
    except Exception as e:
        yield bot.send_message(pgettext('Rejection failed', 'Message sending failed: {reason}').format(reason=str(e)),
                               reply_to_message=message)

    return True
