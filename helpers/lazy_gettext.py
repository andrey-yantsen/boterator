from ujson import dumps

from tornado import locale
from tornado.locale import Locale


class pgettext:
    def __init__(self, context, message):
        self.context = context
        self.message = message
        self._locale = locale.get('en_US')
        self.format_args = ()
        self.format_kwargs = {}

    @property
    def locale(self):
        return self._locale

    @locale.setter
    def locale(self, l: Locale):
        self._locale = l

    def __str__(self):
        ret = self.locale.pgettext(self.context, self.message)
        if self.format_args or self.format_kwargs:
            return ret.format(*self.format_args, **self.format_kwargs)
        return ret

    def format(self, *args, **kwargs):
        self.format_args = args
        self.format_kwargs = kwargs
        return self


class npgettext(pgettext):
    def __init__(self, context, message, plural_message, count):
        super().__init__(context, message)
        self.plural_message = plural_message
        self.count = count

    def __str__(self):
        ret = self.locale.pgettext(self.context, self.message, self.plural_message, self.count)
        if self.format_args or self.format_kwargs:
            return ret.format(*self.format_args, **self.format_kwargs)
        return ret


def set_locale_recursive(data, l):
    if type(data) is dict:
        for k, v in data.items():
            data[k] = set_locale_recursive(v, l)
    elif type(data) is list:
        for k, v in enumerate(data):
            data[k] = set_locale_recursive(v, l)
    elif type(data) is tuple:
        data = tuple([set_locale_recursive(v, l) for v in data])
    elif isinstance(data, pgettext):
        data.locale = l
        return str(data)
    return data
