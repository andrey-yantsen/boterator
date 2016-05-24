import re
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
        if not isinstance(cls._instance, cls):
            cls._instance = object.__new__(cls)
        return cls._instance

    @staticmethod
    def test(*args, **kwargs):
        return True


class CommandFilterTextAny(CommandFilterAny):
    @staticmethod
    def test(*args, **kwargs):
        return 'text' in kwargs.get('message', {})


class CommandFilterMultimediaAny(CommandFilterAny):
    @staticmethod
    def test(*args, **kwargs):
        if 'message' not in kwargs:
            return False

        multimedia_types = ('sticker', 'audio', 'voice', 'video', 'photo', 'document')
        return any(t in kwargs['message'].keys() for t in multimedia_types)


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


class CommandFilterTextRegexp(CommandFilterBase):
    def __init__(self, regexp: str, flags: int=0):
        assert regexp != ''
        self.re = re.compile(regexp, flags)

    def test(self, *args, **kwargs):
        if CommandFilterTextAny.test(*args, **kwargs):
            text = kwargs['message']['text'].strip()
            match = self.re.match(text)
            if match:
                return match.groupdict()
        return False


class CommandFilterNewChatMemberAny(CommandFilterBase):
    @staticmethod
    def test(*args, **kwargs):
        return 'new_chat_member' in kwargs.get('message', {})


class CommandFilterNewChatMember(CommandFilterBase):
    def __init__(self, user_id: int):
        assert user_id > 0
        self.user_id = user_id

    def test(self, *args, **kwargs):
        if CommandFilterNewChatMemberAny.test(*args, **kwargs):
            return kwargs['message']['new_chat_member']['id'] == self.user_id
        return False


class CommandFilterLeftChatMemberAny(CommandFilterAny):
    @staticmethod
    def test(*args, **kwargs):
        return 'left_chat_member' in kwargs.get('message', {})


class CommandFilterGroupChatCreated(CommandFilterAny):
    @staticmethod
    def test(*args, **kwargs):
        return kwargs.get('message', {}).get('group_chat_created', False)


class CommandFilterSupergroupChatCreated(CommandFilterAny):
    @staticmethod
    def test(*args, **kwargs):
        return kwargs.get('message', {}).get('supergroup_chat_created', False)


class CommandFilterPrivate(CommandFilterAny):
    @staticmethod
    def test(*args, **kwargs):
        return kwargs.get('message', {}).get('chat', {}).get('type') == 'private'


class CommandFilterCallbackQuery(CommandFilterBase):
    def __init__(self, text):
        self.text = text

    def test(self, *args, **kwargs):
        return kwargs.get('callback_query', {}).get('data') == self.text


class CommandFilterCallbackQueryRegexp(CommandFilterBase):
    def __init__(self, regexp: str, flags: int=0):
        assert regexp != ''
        self.re = re.compile(regexp, flags)

    def test(self, *args, **kwargs):
        text = kwargs.get('callback_query', {}).get('data')
        if text:
            match = self.re.match(text)
            if match:
                return match.groupdict()
        return False
