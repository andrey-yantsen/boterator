import logging
from copy import deepcopy
from tornado.gen import coroutine
from ujson import dumps

from tobot import CommandFilterTextCmd, CommandFilterTextAny
from core.queues import queue_request, QUEUE_SLAVEHOLDER_GET_BOT_INFO, QUEUE_SLAVEHOLDER_GET_MODERATION_GROUP, \
    QUEUE_SLAVEHOLDER_NEW_BOT
from core.settings import DEFAULT_SLAVE_SETTINGS
from tobot.helpers import report_botan
from tobot.helpers.lazy_gettext import pgettext, npgettext
import tornado.locale

from tobot.telegram import Api


@coroutine
@CommandFilterTextCmd('/reg')
def reg_command(bot, message):
    report_botan(message, 'boterator_reg')

    yield bot.send_message(pgettext('/reg response', 'Ok, please tell me the token, which you\'ve received from '
                                                     '@BotFather'),
                           reply_to_message=message)
    slave_settings = deepcopy(DEFAULT_SLAVE_SETTINGS)
    slave_settings['locale'] = bot.get_settings(message['from']['id']).get('locale', 'en_US')
    locale = tornado.locale.get(slave_settings['locale'])
    slave_settings['hello'].locale = locale
    slave_settings['hello'] = str(slave_settings['hello'])
    slave_settings['start'].locale = locale
    slave_settings['start'] = str(slave_settings['start'])

    return {
        'settings': slave_settings,
        'owner_id': message['from']['id'],
    }


@coroutine
@CommandFilterTextAny()
def plaintext_token(bot, message, **kwargs):
    token = message['text'].strip()
    if token == '':
        report_botan(message, 'boterator_token_empty')
        yield bot.send_message(pgettext('Empty token entered', 'I guess you forgot to enter the token :)'),
                               reply_to_message=message)
    else:
        if len(token.split(':')) != 2 or not token.split(':')[0].isdigit():
            report_botan(message, 'boterator_token_invalid')
            yield bot.send_message(pgettext('Non-well formatted token', 'Token is incorrect. And I can do nothing with '
                                                                        'that.'),
                                   reply_to_message=message)
            return

        yield bot.send_chat_action(message['chat']['id'], bot.CHAT_ACTION_TYPING)

        try:
            new_bot_info = yield queue_request(bot.queue, QUEUE_SLAVEHOLDER_GET_BOT_INFO, token=token, timeout=10)
        except:
            yield bot.send_message(pgettext('Unable to validate token', 'Unable to validate token right now, please '
                                                                        'try again later'),
                                   reply_to_message=message)
            return

        if new_bot_info.get('error'):
            if new_bot_info['error'] == 'duplicate':
                report_botan(message, 'boterator_token_duplicate')
                yield bot.send_message(pgettext('Provided token is already registered and alive',
                                                'It seems like this bot is already registered. Try to create another '
                                                'one'), reply_to_message=message)
                return
            else:
                report_botan(message, 'boterator_token_failure')
                yield bot.send_message(pgettext('Token check failed', 'Unable to get bot info: {}') \
                                       .format(new_bot_info['error']),
                                       reply_to_message=message)
                return

        msg = pgettext('Token received',
                       "Ok, I\'ve got basic information for @{bot_username_escaped}\n"
                       'Now add him to a group of moderators (or copy and paste `/attach@{bot_username}` to the '
                       'group, in case you’ve already added him), where I should send messages for verification, or '
                       'type /cancel')

        bot_username_escaped = new_bot_info['username'].replace('_', r'\_')
        kwargs['settings']['hello'] = kwargs['settings']['hello'].format(bot_username=new_bot_info['username'])
        msg.format(bot_username_escaped=bot_username_escaped, bot_username=new_bot_info['username'])

        yield bot.send_message(msg, reply_to_message=message, parse_mode=bot.PARSE_MODE_MD)

        report_botan(message, 'boterator_token')

        try:
            chat = yield queue_request(bot.queue, QUEUE_SLAVEHOLDER_GET_MODERATION_GROUP, token=token, timeout=600)
        except:
            try:
                yield bot.send_message(pgettext('Unable to receive moderation group',
                                                'Unable to receive moderation group. Send me bot`s token if you would '
                                                'like to try again.'),
                                       reply_to_message=message)
            except:
                pass

            return

        yield bot.send_chat_action(message['chat']['id'], bot.CHAT_ACTION_TYPING)

        if chat['type'] == 'private':
            chat['title'] = '@' + chat['sender']['username']
        elif not chat['title']:
            chat['title'] = '<no title>'

        msg = pgettext('Slave attached to moderator`s channel',
                       "Ok, I'll be sending moderation requests to {chat_type} {chat_title}\n"
                       "Now you need to add your bot (@{bot_username_escaped}) to a channel as administrator and tell "
                       "me the channel name (e.g. @mobilenewsru)\n"
                       "As soon as I will receive the channel name I'll send a message with following text:\n> "
                       "{current_hello}\n"
                       "You can change the message, if you mind, just send me /sethello.\n"
                       "Also there is 'start' message for your new bot:\n> {current_start}\n"
                       "You can change it with /setstart.")

        msg.format(chat_type=chat['type'], chat_title=chat['title'], bot_username_escaped=bot_username_escaped,
                   current_hello=kwargs['settings']['hello'], current_start=kwargs['settings']['start'])

        try:
            yield bot.send_message(msg, reply_to_message=message, parse_mode=bot.PARSE_MODE_MD)
        except:
            yield bot.send_message(msg, reply_to_message=message)

        report_botan(message, 'boterator_slave_attached_to_channel')

        return {
            'id': new_bot_info['id'],
            'moderator_chat_id': chat['id'],
            'chat': chat,
            'token': token,
            'settings': kwargs['settings'],
            'bot_info': new_bot_info,
        }


@coroutine
@CommandFilterTextAny()
def plaintext_channel_name(bot, message, **kwargs):
    channel_name = message['text'].strip()
    if message['text'][0] != '@' or ' ' in channel_name:
        report_botan(message, 'boterator_channel_invalid')
        yield bot.send_message(pgettext('Invalid channel name received',
                                        'Invalid channel name. Try again or type /cancel'),
                               reply_to_message=message)
    else:
        settings, bot_info = kwargs['settings'], kwargs['bot_info']
        try:
            yield bot.send_chat_action(message['chat']['id'], bot.CHAT_ACTION_TYPING)
            new_bot = Api(kwargs['token'], lambda x: None)
            try:
                yield new_bot.send_message(kwargs['settings']['hello'], chat_id=channel_name,
                                           parse_mode=Api.PARSE_MODE_MD)
            except:
                yield new_bot.send_message(kwargs['settings']['hello'], chat_id=channel_name)
            report_botan(message, 'boterator_registered')
            kwargs['target_channel'] = channel_name
            yield bot.queue.send(QUEUE_SLAVEHOLDER_NEW_BOT, dumps(kwargs))

            votes_cnt_msg = npgettext('Default votes cnt', '{cnt} vote', '{cnt} votes',
                                      settings['votes']).format(cnt=settings['votes'])

            delay_msg = npgettext('Default delay', '{delay} minute', '{delay} minutes',
                                  settings['delay']).format(delay=settings['delay'])

            timeout_msg = npgettext('Default timeout', '{timeout} hour', '{timeout} hours',
                                    settings['vote_timeout']).format(timeout=settings['vote_timeout'])

            msg = pgettext('New bot registered',
                           "And we're ready for some magic!\n"
                           'By default the bot will wait for {votes_cnt_msg} to approve the '
                           'message, perform {delay_msg} delay between channel messages, '
                           'wait {timeout_msg} before closing a voting for each message and '
                           'allow only text messages (no multimedia content at all). To '
                           'modify this (and few other) settings send /help in PM to @{bot_username}. '
                           'By default you\'re the only user who can change these '
                           'settings and use /help command').format(votes_cnt_msg=votes_cnt_msg,
                                                                    delay_msg=delay_msg, timeout_msg=timeout_msg,
                                                                    bot_username=bot_info['username'])

            try:
                yield bot.send_message(msg, reply_to_message=message)
                yield bot.db.execute("""INSERT INTO registered_bots (id, token, owner_id, moderator_chat_id, target_channel, active, settings)
                                        VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                                        ON CONFLICT (id) DO UPDATE SET token = EXCLUDED.token, owner_id = EXCLUDED.owner_id,
                                        moderator_chat_id = EXCLUDED.moderator_chat_id, target_channel = EXCLUDED.target_channel,
                                        active = EXCLUDED.active""",
                                     (kwargs['id'], kwargs['token'], kwargs['owner_id'], kwargs['moderator_chat_id'],
                                      kwargs['target_channel'], dumps(kwargs['settings'])))
            except:
                logging.exception('Exception while finishing bot registration')
            return True
        except Exception as e:
            report_botan(message, 'boterator_channel_failure')
            yield bot.send_message(pgettext('Sending channel-hello message failed',
                                            'Hey, I\'m unable to send hello message, is everything ready '
                                            'for me? Here is an error from Telegram api: {error}').format(error=str(e)),
                                   reply_to_message=message)


@coroutine
@CommandFilterTextCmd('/sethello')
def change_hello_command(bot, message, **kwargs):
    report_botan(message, 'boterator_change_hello_cmd')
    yield bot.send_message(pgettext('/sethello response',
                                    'Ok, I\'m listening to you. How I should say hello to your '
                                    'subscribers?'),
                           reply_to_message=message)
    return True


@coroutine
@CommandFilterTextAny()
def plaintext_set_hello(bot, message, **kwargs):
    text = message['text'].strip()
    if len(text) >= 10:
        report_botan(message, 'boterator_change_hello_success')
        yield bot.send_message(pgettext('Channel-hello message updated',
                                        'Ok, noted, now tell me the channel name'),
                               reply_to_message=message)
        kwargs['settings']['hello'] = text
        return {
            'settings': kwargs['settings']
        }
    else:
        report_botan(message, 'boterator_change_hello_short')
        yield bot.send_message(pgettext('Channel-hello message is too short',
                                        'Hey, you should write at least 10 symbols'),
                               reply_to_message=message)


@coroutine
@CommandFilterTextCmd('/setstart')
def change_start_command(bot, message, **kwargs):
    report_botan(message, 'boterator_change_start_cmd')
    yield bot.send_message(pgettext('/setstart response',
                                    'Ok, I\'m listening to you. How I should say hello to your authors?'),
                           reply_to_message=message)
    return True


@coroutine
@CommandFilterTextAny()
def plaintext_set_start_message(bot, message, **kwargs):
    text = message['text'].strip()
    if len(text) >= 10:
        report_botan(message, 'boterator_change_start_success')
        yield bot.send_message(pgettext('/start message updated',
                                        'Ok, noted, now tell me the channel name'),
                               reply_to_message=message)
        kwargs['settings']['start'] = text
        return {
            'settings': kwargs['settings']
        }
    else:
        report_botan(message, 'boterator_change_start_short')
        yield bot.send_message(pgettext('/start message is too short',
                                        'Hey, you should write at least 10 symbols'),
                               reply_to_message=message)
