from babel.numbers import format_number
from ujson import dumps

from tobot.telegram import InlineKeyboardMarkup, InlineKeyboardButton
from tornado.gen import coroutine

from tobot import CommandFilterPrivate, CommandFilterTextAny, CommandFilterMultimediaAny, CommandFilterCallbackQuery
from tobot.helpers import report_botan, pgettext


@coroutine
def _request_message_confirmation(bot, message):
    yield bot.forward_message(message['from']['id'], message['chat']['id'], message['message_id'])
    yield bot.send_message(pgettext('Message received, requesting the user to check the message once again',
                                    'Looks good for me. I\'ve printed the message in exact same way as it '
                                    'will be publised. Please, take a look on your message one more time. And '
                                    'click Confirm button if everything is fine'),
                           reply_to_message=message,
                           reply_markup=InlineKeyboardMarkup([
                               [InlineKeyboardButton(pgettext('`Confirm` button on message review keyboard',
                                                              'Confirm'), callback_data='confirm_publishing'),
                                InlineKeyboardButton(pgettext('`Cancel` button on message review keyboard',
                                                              'Cancel'), callback_data='cancel_publishing'),
                                ]
                           ]))


@coroutine
@CommandFilterTextAny()
@CommandFilterPrivate()
def plaintext_post_handler(bot, message):
    if bot.settings['content_status']['text'] is False:
        yield bot.bot.send_message(pgettext('User send text message for verification while texts is disabled',
                                            'Accepting text messages are disabled'),
                                   reply_to_message=message)
        return

    mes = message['text']
    if mes.strip() != '':
        if bot.settings['text_min'] <= len(mes) <= bot.settings['text_max']:
            yield _request_message_confirmation(bot, message)
            report_botan(message, 'slave_message')
            return {
                'sent_message': message
            }
        else:
            report_botan(message, 'slave_message_invalid')
            yield bot.send_message(pgettext('Incorrect text message received', 'Sorry, but we can proceed only '
                                                                               'messages with length between '
                                                                               '{min_msg_length} and {max_msg_length} '
                                                                               'symbols.')
                                   .format(min_msg_length=format_number(bot.settings['text_min'], bot.language),
                                           max_msg_length=format_number(bot.settings['text_max'], bot.language)),
                                   reply_to_message=message)
    else:
        report_botan(message, 'slave_message_empty')
        yield bot.send_message(pgettext('User sent empty message', 'Seriously??? 8===3'),
                               reply_to_message=message)


@coroutine
@CommandFilterMultimediaAny()
@CommandFilterPrivate()
def multimedia_post_handler(bot, message):
    if 'sticker' in message and bot.settings['content_status']['sticker'] is False:
        yield bot.send_message(pgettext('User sent a sticker for verification while stickers are disabled',
                                        'Accepting stickers is disabled'), reply_to_message=message)
        return
    elif 'audio' in message and bot.settings['content_status']['audio'] is False:
        yield bot.send_message(pgettext('User sent an audio for verification while audios are disabled',
                                        'Accepting audios is disabled'), reply_to_message=message)
        return
    elif 'voice' in message and bot.settings['content_status']['voice'] is False:
        yield bot.send_message(pgettext('User sent a voice for verification while voices are disabled',
                                        'Accepting voice is disabled'), reply_to_message=message)
        return
    elif 'video' in message and bot.settings['content_status']['video'] is False:
        yield bot.send_message(pgettext('User sent a video for verification while videos are disabled',
                                        'Accepting videos is disabled'), reply_to_message=message)
        return
    elif 'photo' in message and bot.settings['content_status']['photo'] is False:
        yield bot.send_message(pgettext('User sent a photo for verification while photos are disabled',
                                        'Accepting photos is disabled'), reply_to_message=message)
        return
    elif 'document' in message and bot.settings['content_status']['document'] is False and \
                    message['document'].get('mime_type') != 'video/mp4':
        yield bot.send_message(pgettext('User sent a document for verification while documents are disabled',
                                        'Accepting documents is disabled'), reply_to_message=message)
        return
    elif 'document' in message and bot.settings['content_status']['gif'] is False and \
                    message['document'].get('mime_type') == 'video/mp4':
        yield bot.send_message(pgettext('User sent a gif for verification while gifs are disabled',
                                        'Accepting gifs is disabled'), reply_to_message=message)
        return

    report_botan(message, 'slave_message_multimedia')
    yield _request_message_confirmation(bot, message)
    return {
        'sent_message': message
    }


@coroutine
@CommandFilterCallbackQuery('confirm_publishing')
def cbq_message_review(bot, callback_query, sent_message):
    user_id = callback_query['from']['id']

    report_botan(callback_query, 'slave_confirm')
    yield bot.db.execute("""
    INSERT INTO incoming_messages (id, original_chat_id, owner_id, bot_id, created_at, message)
    VALUES (%s, %s, %s, %s, NOW(), %s)
    """, (sent_message['message_id'], sent_message['chat']['id'], user_id, bot.bot_id, dumps(sent_message)))

    bot.send_moderation_request(sent_message['chat']['id'], sent_message['message_id'])

    yield bot.db.execute('UPDATE registered_bots SET last_moderation_message_at = NOW() WHERE id = %s',
                         (bot.bot_id,))

    yield bot.edit_message_text(pgettext('Message sent for verification', 'Okay, I\'ve sent your message for '
                                                                          'verification. Fingers crossed!'),
                                callback_query['message'])
    yield bot.answer_callback_query(callback_query['id'])
    return True


@coroutine
@CommandFilterCallbackQuery('cancel_publishing')
def cbq_cancel_publishing(bot, callback_query, **kwargs):
    yield bot.edit_message_text(pgettext('Message publishing cancelled', 'Cancelled'), callback_query['message'])
    yield bot.answer_callback_query(callback_query['id'])
    return True
