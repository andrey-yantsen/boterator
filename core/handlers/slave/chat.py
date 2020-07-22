from tornado.gen import coroutine

from tobot import CommandFilterNewChatMemberAny, CommandFilterLeftChatMemberAny
from tobot.helpers import report_botan


@coroutine
@CommandFilterNewChatMemberAny()
def new_chat(bot, message):
    if message['new_chat_member']['id'] == bot.bot_id and message['chat']['id'] == bot.moderator_chat_id:
        report_botan(message, 'subordinate_renew_chat')
        yield bot.db.execute('UPDATE registered_bots SET active = TRUE WHERE id = %s', (bot.bot_id,))
    else:
        return False


@coroutine
@CommandFilterLeftChatMemberAny()
def left_chat(bot, message):
    if message['left_chat_member']['id'] == bot.bot_id and message['chat']['id'] == bot.moderator_chat_id:
        report_botan(message, 'subordinate_left_chat')
        yield bot.db.execute('UPDATE registered_bots SET active = FALSE WHERE id = %s', (bot.bot_id,))
    else:
        return False
