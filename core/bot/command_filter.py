class CommandFilterBase:
    def __call__(self, message, **kwargs):
        raise NotImplementedError()


class CommandFilterAny(CommandFilterBase):
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = object.__new__(cls)
        return cls._instance

    def __call__(self, message, **kwargs):
        return True


class CommandFilterTextAny(CommandFilterAny):
    def __call__(self, update, **kwargs):
        return 'text' in update.get('message', {})


class CommandFilterTextCmd(CommandFilterBase):
    def __init__(self, cmd):
        assert cmd != ''
        self.cmd = cmd

    def __call__(self, update, **kwargs):
        if CommandFilterTextAny()(update):
            text = update['message']['text'].strip()
            if text == self.cmd or text.startswith(self.cmd + '@') or text.startswith(self.cmd + ' '):
                return True
        return False
