from tornado.gen import coroutine

from tobot import CommandFilterTextRegexp, CommandFilterTextCmd, CommandFilterTextAny, \
    CommandFilterCallbackQueryRegexp
from core.subordinate_command_filters import CommandFilterIsModerationChat
from tobot.helpers import report_botan, pgettext
from tobot.telegram import ForceReply


@coroutine
@CommandFilterIsModerationChat()
@CommandFilterCallbackQueryRegexp(r'ban_(?P<user_id>\d+)(?:_(?P<chat_id>\d+)_(?P<message_id>\d+))?')
def ban_command(bot, callback_query, user_id, chat_id=None, message_id=None):
    report_botan(callback_query, 'subordinate_ban_cmd')

    if int(user_id) == callback_query['from']['id']:
        yield bot.answer_callback_query(callback_query['id'],
                                        pgettext('Somebody trying to ban himself', 'It\'s not allowed to ban yourself'))
        return None

    if int(user_id) == bot.owner_id:
        yield bot.answer_callback_query(callback_query['id'],
                                        pgettext('Somebody trying to ban the owner',
                                                 'It\'s not allowed to ban the bot owner'))
        return None

    cur = yield bot.db.execute('SELECT banned_at FROM users WHERE bot_id = %s AND user_id = %s', (bot.bot_id, user_id))
    row = cur.fetchone()
    if row and row[0]:
        yield bot.answer_callback_query(callback_query['id'], pgettext('User already banned', 'User already banned'))
        return None

    msg = pgettext('Ban reason request', 'Please enter a ban reason for the user, @{moderator_username}')\
        .format(moderator_username=callback_query['from']['username'])

    if chat_id and message_id:
        fwd_id = yield bot.get_message_fwd_id(chat_id, message_id)
    else:
        fwd_id = None

    yield bot.send_message(msg, chat_id=bot.moderator_chat_id, reply_markup=ForceReply(True),
                           reply_to_message_id=fwd_id)
    yield bot.answer_callback_query(callback_query['id'])
    return {
        'user_id': user_id
    }


@coroutine
@CommandFilterTextAny()
def plaintext_ban_handler(bot, message, user_id):
    chat_id = message['chat']['id']

    cur = yield bot.db.execute('SELECT banned_at FROM users WHERE bot_id = %s AND user_id = %s', (bot.bot_id, user_id))
    row = cur.fetchone()
    if row and row[0]:
        yield bot.send_message(pgettext('Somebody banned a user faster than another one',
                                        'Somebody already banned the user. Be faster next time.'),
                               reply_to_message=message)
        return True

    msg = message['text'].strip()
    if len(msg) < 5:
        report_botan(message, 'subordinate_ban_short_msg')
        yield bot.send_message(pgettext('Ban reason too short', 'Reason is too short (5 symbols required), '
                                                                'try again or send /cancel'),
                               reply_to_message=message, reply_markup=ForceReply(True))
    else:
        report_botan(message, 'subordinate_ban_success')
        yield bot.send_chat_action(chat_id, bot.CHAT_ACTION_TYPING)
        try:
            yield bot.send_message(pgettext('Message to user in case of ban',
                                            "You've been banned from further communication with this bot. "
                                            "Reason:\n> {ban_reason}").format(ban_reason=msg),
                                   chat_id=user_id)
        except:
            pass
        cur = yield bot.db.execute('SELECT message FROM incoming_messages WHERE bot_id = %s AND owner_id = %s AND '
                                   'is_voting_success = FALSE AND is_voting_fail = FALSE AND is_published = FALSE',
                                   (bot.id, user_id,))
        while True:
            row = cur.fetchone()
            if not row:
                break
            yield bot.decline_message(row[0], 0, False)

        yield bot.db.execute('UPDATE users SET banned_at = NOW(), ban_reason = %s WHERE user_id = %s AND '
                             'bot_id = %s', (msg, user_id, bot.id))
        yield bot.send_message(pgettext('Ban confirmation', 'User banned'), reply_to_message=message)

        return True


@coroutine
@CommandFilterIsModerationChat()
@CommandFilterTextRegexp(r'/unban_(?P<user_id>\d+)')
def unban_command(bot, message, user_id):
    report_botan(message, 'subordinate_unban_cmd')
    yield bot.db.execute('UPDATE users SET banned_at = NULL, ban_reason = NULL WHERE user_id = %s AND '
                         'bot_id = %s', (user_id, bot.id))
    yield bot.send_message(pgettext('Unban confirmation', 'User unbanned'), reply_to_message=message)
    try:
        yield bot.send_message(pgettext('User notification in case of unban', 'Access restored'),
                               chat_id=user_id)
    except:
        pass


@coroutine
@CommandFilterIsModerationChat()
@CommandFilterTextCmd('/banlist')
def ban_list_command(bot, message):
    chat_id = message['chat']['id']
    report_botan(message, 'subordinate_ban_list_cmd')
    yield bot.send_chat_action(chat_id, bot.CHAT_ACTION_TYPING)
    cur = yield bot.db.execute('SELECT user_id, first_name, last_name, username, banned_at, ban_reason '
                               'FROM users WHERE bot_id = %s AND '
                               'banned_at IS NOT NULL ORDER BY banned_at DESC', (bot.bot_id,))

    bans = cur.fetchall()

    msg = '{}\n' * len(bans) if len(bans) > 0 else ''
    msg = msg.strip()

    data = []
    for row_id, (user_id, first_name, last_name, username, banned_at, ban_reason) in enumerate(bans):
        if first_name and last_name:
            user = first_name + ' ' + last_name
        elif first_name:
            user = first_name
        else:
            user = 'userid %s' % user_id

        data.append(pgettext('Ban user item', '{row_id}. {user} - {ban_reason} (banned {ban_date}) {unban_cmd}') \
                    .format(row_id=row_id + 1, user=user, ban_reason=ban_reason,
                            ban_date=banned_at.strftime('%Y-%m-%d'), unban_cmd='/unban_%s' % (user_id,)))

    msg = msg.format(*data)

    if msg:
        yield bot.send_message(msg, reply_to_message=message)
        if chat_id != bot.moderator_chat_id:
            yield bot.send_message(pgettext('Bot owner notification', 'You can use /unban command only in moderators '
                                                                      'group'),
                                   reply_to_message=message)
    else:
        yield bot.send_message(pgettext('Ban list is empty', 'No banned users yet'),
                               reply_to_message=message)
