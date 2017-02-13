from tobot import CommandFilterAny
from tornado.gen import coroutine


@coroutine
@CommandFilterAny()
def migrate_to_supergroup_msg(bot, *args, **kwargs):
    if kwargs.get('message'):
        if kwargs['message'].get('migrate_to_chat_id'):
            to_chat_id = kwargs['message']['migrate_to_chat_id']
            from_chat_id = kwargs['message']['chat']['id']
            if from_chat_id == bot.moderator_chat_id:
                yield migrate(bot, to_chat_id)
                return
        if kwargs['message'].get('migrate_from_chat_id'):
            to_chat_id = kwargs['message']['chat']['id']
            from_chat_id = kwargs['message']['migrate_from_chat_id']
            if from_chat_id == bot.moderator_chat_id:
                yield migrate(bot, to_chat_id)
                return
    return False


@coroutine
def migrate(bot, new_chat_id):
    bot.moderator_chat_id = new_chat_id
    yield bot.db.execute('UPDATE registered_bots SET moderator_chat_id = %s WHERE id = %s', (new_chat_id, bot.bot_id))
