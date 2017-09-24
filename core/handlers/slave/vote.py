from tornado.gen import coroutine

from tobot import CommandFilterCallbackQueryRegexp, CommandFilterTextRegexp
from core.slave_command_filters import CommandFilterIsModerationChat
from tobot.helpers import pgettext, report_botan


@coroutine
def __prev_vote(db, user_id, original_chat_id, message_id):
    cur = yield db.execute('SELECT vote_yes FROM votes_history WHERE user_id = %s AND message_id = %s AND '
                           'original_chat_id = %s',
                           (user_id, message_id, original_chat_id))

    row = cur.fetchone()
    return row[0]


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
def __vote(bot, message_id, original_chat_id, yes: bool, callback_query=None, message=None):
    assert callback_query or message

    user_id = callback_query['from']['id'] if callback_query else message['from']['id']

    if not bot.settings.get('selfvote') and int(original_chat_id) == user_id and user_id != bot.moderator_chat_id:
        if callback_query:
            yield bot.answer_callback_query(callback_query['id'], pgettext('Moderator voted for own message',
                                                                           'It\'s not allowed to vote for own messages'))
        return False

    prev_vote = yield __prev_vote(bot.db, user_id, original_chat_id, message_id)
    voted = False
    if prev_vote:
        voted = True
    opened = yield __is_voting_opened(bot.db, original_chat_id, message_id)

    cur = yield bot.db.execute('SELECT SUM(vote_yes::INT), COUNT(*) FROM votes_history WHERE message_id = %s AND '
                               'original_chat_id = %s',
                               (message_id, original_chat_id))
    current_yes, current_total = cur.fetchone()
    if not current_yes:
        current_yes = 0

    if opened:

        if not voted:
            current_yes += int(yes)
            current_total += 1

            yield bot.db.execute("""INSERT INTO votes_history (user_id, message_id, original_chat_id, vote_yes, created_at)
                                    VALUES (%s, %s, %s, %s, NOW())""",
                                 (user_id, message_id, original_chat_id, yes))
        else:

            if yes == prev_vote and callback_query:
                yield bot.answer_callback_query(callback_query['id'], pgettext('User tapped voting button second time',
                                                                               'Your vote is already counted. You changed '
                                                                               'nothing this time.'))
            elif yes != prev_vote and bot.settings.get('allow_vote_switch'):
                current_yes += int(yes)

                yield bot.db.execute("""UPDATE votes_history SET vote_yes  = %s
                                        WHERE user_id = %s AND message_id = %s AND original_chat_id = %s""",
                                     (yes, user_id, message_id, original_chat_id))


        if current_yes >= bot.settings.get('votes', 5):
            if callback_query:
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
        elif callback_query:
            msg, keyboard = yield bot.get_verification_message(message_id, original_chat_id, False)
            yield bot.edit_message_text(msg, callback_query['message'], reply_markup=keyboard)

        if callback_query:
            yield bot.answer_callback_query(callback_query['id'], pgettext('User`s vote successfully counted', 'Counted.'))
    elif not opened and callback_query:
        msg, keyboard = yield bot.get_verification_message(message_id, original_chat_id, True)
        yield bot.edit_message_text(msg, callback_query['message'], reply_markup=keyboard)
        yield bot.answer_callback_query(callback_query['id'])


@coroutine
@CommandFilterIsModerationChat()
@CommandFilterCallbackQueryRegexp(r'vote_(?P<original_chat_id>\d+)_(?P<message_id>\d+)_(?P<vote_type>yes|no)')
def vote_new(bot, callback_query, original_chat_id, message_id, vote_type):
    report_botan(callback_query, 'slave_vote_yes')
    yield __vote(bot, message_id, original_chat_id, vote_type == 'yes', callback_query=callback_query)


@coroutine
@CommandFilterIsModerationChat()
@CommandFilterTextRegexp(r'/vote_(?P<original_chat_id>\d+)_(?P<message_id>\d+)_(?P<vote_type>yes|no)')
def vote_old(bot, message, original_chat_id, message_id, vote_type):
    report_botan(message, 'slave_vote_yes')
    yield __vote(bot, message_id, original_chat_id, vote_type == 'yes', message=message)
