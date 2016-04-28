from logging import Handler, NOTSET

from telegram import Api


class TelegramHandler(Handler):
    def __init__(self, bot: Api, target_user_id, level=NOTSET):
        super().__init__(level)
        self.bot = bot
        self.user_id = target_user_id

    def emit(self, record):
        if not self.user_id:
            return

        self.bot.send_message(self.user_id, record)
