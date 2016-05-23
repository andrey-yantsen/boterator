from functools import wraps


class CommandFilterBase:
    def test(self, *args, **kwargs):
        raise NotImplementedError()

    def __call__(self, f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            test_passed = self.test(*args, **kwargs)
            if test_passed is not False:
                if isinstance(test_passed, dict):
                    kwargs.update(test_passed)
                return f(*args, **kwargs)
            return False
        return wrapper


class CommandFilterAny(CommandFilterBase):
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = object.__new__(cls)
        return cls._instance

    @staticmethod
    def test(*args, **kwargs):
        return True


class CommandFilterTextAny(CommandFilterAny):
    @staticmethod
    def test(*args, **kwargs):
        return 'text' in kwargs.get('message', {})


class CommandFilterText(CommandFilterBase):
    def __init__(self, text):
        assert text != ''
        self.text = text

    def test(self, *args, **kwargs):
        if CommandFilterTextAny.test(*args, **kwargs):
            text = kwargs['message']['text'].strip()
            if text == self.text or text.startswith(self.text + '@'):
                return True
        return False


class CommandFilterTextCmd(CommandFilterBase):
    def __init__(self, cmd):
        assert cmd != ''
        self.cmd = cmd

    def test(self, *args, **kwargs):
        if CommandFilterTextAny.test(*args, **kwargs):
            text = kwargs['message']['text'].strip()
            if text == self.cmd or text.startswith(self.cmd + '@') or text.startswith(self.cmd + ' '):
                return True
        return False
