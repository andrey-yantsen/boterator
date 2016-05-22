from tornado.gen import coroutine


@coroutine
def __wait_for_registration_complete(self, original_message, npgettext=None, pgettext=None, timeout=3600):
    stage = self.stages.get(original_message)
    slave = Slave(stage[1]['token'], self, None, None, {}, original_message['from']['id'], None)
    slave.listen()
    while True:
        stage_id, stage_meta, stage_begin = self.stages.get(original_message)

        if stage_id == self.STAGE_REGISTERED:
            settings = deepcopy(self.default_slave_settings)
            settings['start'] = stage_meta['start_message']

            yield slave.stop()

            yield self.bot.send_chat_action(original_message['chat']['id'], self.bot.CHAT_ACTION_TYPING)
            yield DB.execute("""
                                      INSERT INTO registered_bots (id, token, owner_id, moderator_chat_id, target_channel, active, settings)
                                      VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                                      ON CONFLICT (id) DO UPDATE SET token = EXCLUDED.token, owner_id = EXCLUDED.owner_id,
                                      moderator_chat_id = EXCLUDED.moderator_chat_id, target_channel=EXCLUDED.target_channel,
                                      active = EXCLUDED.active, settings = EXCLUDED.settings
                                      """, (stage_meta['bot_info']['id'], stage_meta['token'],
                                            original_message['from']['id'], stage_meta['moderation'],
                                            stage_meta['channel'], dumps(settings)))
            slave = Slave(stage_meta['token'], self, stage_meta['moderation'], stage_meta['channel'],
                          settings, original_message['from']['id'], stage_meta['bot_info']['id'])
            slave.listen()
            self.slaves[stage_meta['bot_info']['id']] = slave

            votes_cnt_msg = npgettext('Boterator: default votes cnt', '%d vote', '%d votes',
                                      self.default_slave_settings['votes']) % self.default_slave_settings['votes']

            delay_msg = npgettext('Boterator: default delay', '%d minute', '%d minutes',
                                  self.default_slave_settings['delay']) % self.default_slave_settings['delay']

            timeout_msg = npgettext('Boterator: default timeout', '%d hour', '%d hours',
                                    self.default_slave_settings['vote_timeout']) \
                          % self.default_slave_settings['vote_timeout']

            msg = pgettext('Boterator: new bot registered',
                           "And we're ready for some magic!\n"
                           'By default the bot will wait for {votes_cnt_msg} to approve the '
                           'message, perform {delay_msg} delay between channel messages, '
                           'wait {timeout_msg} before closing a voting for each message and '
                           'allow only text messages (no multimedia content at all). To '
                           'modify this (and few other) settings send /help in PM to @{bot_username}. '
                           'By default you\'re the only user who can change these '
                           'settings and use /help command').format(votes_cnt_msg=votes_cnt_msg,
                                                                    delay_msg=delay_msg, timeout_msg=timeout_msg,
                                                                    bot_username=stage_meta['bot_info']['username'])

            try:
                yield self.bot.send_message(msg, reply_to_message=original_message)
            except:
                pass
            break
        elif time() - stage_begin >= timeout:
            yield slave.stop()
            try:
                yield self.bot.send_message(pgettext('Boterator: registration cancelled due to timeout',
                                                     '@%s registration aborted due to timeout')
                                            % stage_meta['bot_info']['username'],
                                            reply_to_message=original_message)
            except:
                pass
            break
        elif stage_id is None:
            # Action cancelled
            yield slave.stop()
            break

        yield sleep(0.05)

    self.stages.drop(original_message)
