from tobot import CommandFilterAny


class CommandFilterIsModerationChat(CommandFilterAny):
    @staticmethod
    def test(bot, *args, **kwargs):
        return bot.moderator_chat_id == kwargs.get('message', kwargs.get('callback_query', {}).get('message', {}))\
            .get('chat', {}).get('id')


class CommandFilterIsBotOwner(CommandFilterAny):
    @staticmethod
    def test(bot, *args, **kwargs):
        return bot.owner_id == kwargs.get('message', kwargs.get('callback_query', {})).get('from', {}).get('id')


class CommandFilterIsModerator(CommandFilterAny):
    @staticmethod
    def test(bot, *args, **kwargs):
        if not bot.moderator_chat_id:
            return False
        if CommandFilterIsBotOwner.test(bot, *args, **kwargs) or CommandFilterIsModerationChat.test(bot, *args, **kwargs):
            return True

        user_id = kwargs.get('message', kwargs.get('callback_query', {})).get('from', {}).get('id')

        return user_id in bot.administrators


class CommandFilterIsPowerfulUser(CommandFilterAny):
    @staticmethod
    def test(bot, *args, **kwargs):
        if not bot.moderator_chat_id:
            return False
        if CommandFilterIsBotOwner.test(bot, *args, **kwargs):
            return True

        return bot.settings['power'] and CommandFilterIsModerationChat.test(bot, *args, **kwargs)
