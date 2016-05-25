from tornado.gen import coroutine

from core.bot import CommandFilterTextCmd
from core.slave_command_filters import CommandFilterIsModerationChat
from helpers import report_botan, pgettext, npgettext


@coroutine
@CommandFilterTextCmd('/pollslist')
@CommandFilterIsModerationChat()
def polls_list_command(bot, message):
    cur = yield bot.db.execute('SELECT owner_id, original_chat_id, id FROM incoming_messages WHERE '
                               'is_voting_success = False AND is_voting_fail = False AND is_published = False AND '
                               'bot_id = %s',
                               (bot.bot_id,))

    pending = cur.fetchall()

    if len(pending):
        polls_cnt_msg = npgettext('Polls count', '{cnt} poll', '{cnt} polls', len(pending)).format(cnt=len(pending))
        reply_part_one = pgettext('/pollslist reply message', 'There is {polls_msg} in progress:') \
            .format(polls_msg=polls_cnt_msg)
        yield bot.send_message(reply_part_one, reply_to_message=message)

        for (owner_id, original_chat_id, message_id) in pending:
            yield bot.send_moderation_request(owner_id, original_chat_id, message_id)
    else:
        yield bot.send_message(pgettext('/pollslist reply on empty pending-polls list',
                                        'There is no polls in progress.'),
                               reply_to_message=message)
