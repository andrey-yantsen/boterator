from tornado.gen import coroutine, maybe_future

from core.bot.command_filter import CommandFilterBase
from helpers import pgettext


class Command:
    def __init__(self, bot, handler: callable, name: pgettext=None):
        self.handler = handler
        self._name = name
        self.bot = bot

    @coroutine
    def __call__(self, **kwargs):
        return (yield maybe_future(self.handler(self.bot, **kwargs)))

    @property
    def name(self):
        return self._name
