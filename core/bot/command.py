from tornado.gen import coroutine, maybe_future

from core.bot.command_filter import CommandFilterBase
from helpers import pgettext


class Command:
    def __init__(self, bot, handler: callable, cmd_filter: CommandFilterBase, name: pgettext=None):
        self.filter = cmd_filter
        self.handler = handler
        self._name = name
        self.bot = bot

    def test(self, update, **kwargs):
        return self.filter(update, **kwargs)

    @coroutine
    def __call__(self, **kwargs):
        return (yield maybe_future(self.handler(self.bot, **kwargs)))

    @property
    def name(self):
        return self._name
