from tornado.gen import coroutine

from core.bot import CommandFilterTextRegexp, CommandFilterCallbackQueryRegexp
from core.slave_command_filters import CommandFilterIsModerationChat
from helpers import pgettext, report_botan


@coroutine
def __is_user_voted(db, user_id, original_chat_id, message_id):
    cur = yield db.execute('SELECT 1 FROM votes_history WHERE user_id = %s AND message_id = %s AND '
                           'original_chat_id = %s',
                           (user_id, message_id, original_chat_id))

    if cur.fetchone():
        return True

    return False


@coroutine
def __is_voting_opened(db, original_chat_id, message_id):
    cur = yield db.execute('SELECT is_voting_fail, is_published FROM incoming_messages WHERE id = %s AND '
                           'original_chat_id = %s',
                           (message_id, original_chat_id))
    row = cur.fetchone()
    if not row or (row[0] != row[1]):
        return False

    return True


@coroutine
def __vote(bot, callback_query, message_id, original_chat_id, yes: bool):
    user_id = callback_query['from']['id']
    voted = yield __is_user_voted(bot.db, user_id, original_chat_id, message_id)
    opened = yield __is_voting_opened(bot.db, user_id, message_id)

    cur = yield bot.db.execute('SELECT SUM(vote_yes::INT), COUNT(*) FROM votes_history WHERE message_id = %s AND '
                               'original_chat_id = %s',
                               (message_id, original_chat_id))
    current_yes, current_total = cur.fetchone()
    if not current_yes:
        current_yes = 0

    if not voted and opened:
        current_yes += int(yes)
        current_total += 1

        yield bot.db.execute("""INSERT INTO votes_history (user_id, message_id, original_chat_id, vote_yes, created_at)
                                VALUES (%s, %s, %s, %s, NOW())""",
                             (user_id, message_id, original_chat_id, yes))

        if current_yes >= bot.settings.get('votes', 5):
            msg, keyboard = yield bot.get_verification_message(message_id, original_chat_id, True)
            yield bot.edit_message_text(msg, callback_query['message'], reply_markup=keyboard)

            cur = yield bot.db.execute('SELECT is_voting_success, message FROM incoming_messages WHERE id = %s '
                                       'AND original_chat_id = %s',
                                       (message_id, original_chat_id))
            row = cur.fetchone()
            if not row[0]:
                yield bot.db.execute('UPDATE incoming_messages SET is_voting_success = TRUE WHERE id = %s AND '
                                     'original_chat_id = %s',
                                     (message_id, original_chat_id))
                try:
                    yield bot.send_message(pgettext('Message verified and queued for publishing',
                                                    'Your message was verified and queued for publishing.'),
                                           chat_id=original_chat_id, reply_to_message_id=message_id)
                except:
                    pass
                report_botan(row[1], 'slave_verification_success')
        elif current_total - current_yes >= bot.settings.get('votes', 5):
            cur = yield bot.db.execute('SELECT is_voting_fail, is_voting_success, message FROM incoming_messages '
                                       'WHERE id = %s AND original_chat_id = %s', (message_id, original_chat_id))
            row = cur.fetchone()

            if row and not row[0] and not row[1]:
                yield bot.decline_message(row[2], current_yes)
        else:
            msg, keyboard = yield bot.get_verification_message(message_id, original_chat_id, False)
            yield bot.edit_message_text(msg, callback_query['message'], reply_markup=keyboard)

        yield bot.answer_callback_query(callback_query['id'], pgettext('User`s vote successfully counted', 'Counted.'))
    elif not opened:
        msg, keyboard = yield bot.get_verification_message(message_id, original_chat_id, True)
        yield bot.edit_message_text(msg, callback_query['message'], reply_markup=keyboard)
        yield bot.answer_callback_query(callback_query['id'])
    elif voted:
        yield bot.answer_callback_query(callback_query['id'], pgettext('User tapped voting button second time',
                                                                       'Your vote is already counted. You changed '
                                                                       'nothing this time.'))


@coroutine
@CommandFilterIsModerationChat()
@CommandFilterCallbackQueryRegexp(r'vote_(?P<original_chat_id>\d+)_(?P<message_id>\d+)_yes')
def vote_yes(bot, callback_query, original_chat_id, message_id):
    report_botan(callback_query, 'slave_vote_yes')
    yield __vote(bot, callback_query, message_id, original_chat_id, True)


@coroutine
@CommandFilterIsModerationChat()
@CommandFilterCallbackQueryRegexp(r'vote_(?P<original_chat_id>\d+)_(?P<message_id>\d+)_no')
def vote_no(bot, callback_query, message_id, original_chat_id):
    report_botan(callback_query, 'slave_vote_no')
    yield __vote(bot, callback_query, message_id, original_chat_id, False)