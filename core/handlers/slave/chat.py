from tornado.gen import coroutine

from core.bot import CommandFilterNewChatMemberAny, CommandFilterLeftChatMemberAny
from helpers import report_botan


@coroutine
@CommandFilterNewChatMemberAny()
def new_chat(bot, message):
    if message['new_chat_member']['id'] == bot.bot_id and message['new_chat_member']['chat']['id'] == bot.moderator_chat_id:
        report_botan(message, 'slave_renew_chat')
        yield bot.db.execute('UPDATE registered_bots SET active = TRUE WHERE id = %s', (me['id'],))
    else:
        return False


@coroutine
@CommandFilterLeftChatMemberAny()
def left_chat(bot, message):
    if message['left_chat_member']['id'] == bot.bot_id and message['left_chat_member']['chat']['id'] == bot.moderator_chat_id:
        report_botan(message, 'slave_left_chat')
        yield bot.db.execute('UPDATE registered_bots SET active = FALSE WHERE id = %s', (me['id'],))
    else:
        return False
