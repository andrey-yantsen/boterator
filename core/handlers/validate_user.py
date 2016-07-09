from tornado.gen import coroutine

from tobot import CommandFilterAny
from tobot.helpers import pgettext


@coroutine
def is_allowed_user(db, user, bot_id):
    query = """
        INSERT INTO users (bot_id, user_id, first_name, last_name, username, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT ON CONSTRAINT users_pkey
        DO UPDATE SET first_name = EXCLUDED.first_name, last_name = COALESCE(EXCLUDED.last_name, users.last_name),
         username = COALESCE(EXCLUDED.username, users.username), updated_at = EXCLUDED.updated_at
    """

    yield db.execute(query, (bot_id, user['id'], user['first_name'], user.get('last_name'), user.get('username')))

    cur = yield db.execute('SELECT banned_at FROM users WHERE bot_id = %s AND user_id = %s', (bot_id, user['id']))
    row = cur.fetchone()
    if row and row[0]:
        return False

    return True


@coroutine
@CommandFilterAny()
def validate_user(bot, **kwargs):
    if 'message' not in kwargs:
        return False

    allowed = yield is_allowed_user(bot.db, kwargs['message']['from'], bot.bot_id)
    if allowed:
        return False

    yield bot.send_message(pgettext('User banned', 'Access denied'), reply_to_message=kwargs['message'])
