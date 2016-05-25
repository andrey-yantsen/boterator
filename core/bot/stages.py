import logging

from datetime import timedelta, datetime
from tornado.gen import coroutine
from tornado.ioloop import PeriodicCallback, IOLoop
from ujson import dumps


class Stages:
    _instances = {}

    def __new__(cls, bot_id, *args):
        if bot_id not in cls._instances:
            cls._instances[bot_id] = object.__new__(cls)
        return cls._instances[bot_id]

    def __init__(self, bot_id, ttl=7200):
        self.bot_id = bot_id
        self.stages = None
        self.ttl = ttl
        self.cleaner = PeriodicCallback(self.drop_expired, min(300000, ttl * 1000))
        self.cleaner.start()

    def restore(self):
        pass

    def drop_expired(self):
        keys_to_drop = []
        for key, stage_data in self.stages.items():
            if stage_data['created_at'] + timedelta(seconds=self.ttl) < datetime.now():
                keys_to_drop.append(key)

        for key in keys_to_drop:
            logging.debug('Deleting obsolete stage #%s', key)
            del self[key]

    def __getitem__(self, key):
        logging.debug('Requested stage #%s', key)
        if key in self.stages:
            return self.stages[key]['stage'], self.stages[key]['data']
        else:
            logging.debug('Stage #%s not found', key)

    def __setitem__(self, key, value):
        assert isinstance(value[1], dict)
        self.stages[key] = {
            'stage': value[0].__name__,
            'data': value[1],
            'created_at': datetime.now()
        }
        logging.debug('Updated stage #%s', key)

    def __delitem__(self, key):
        if key in self.stages:
            del self.stages[key]
            logging.debug('Deleted stage #%s', key)
            f = self.db.execute('DELETE FROM stages WHERE bot_id = %s AND key = %s', (self.bot_id, key))
            IOLoop.current().add_future(f, lambda x: None)

    def __contains__(self, item):
        return item in self.stages


class PersistentStages(Stages):
    def __init__(self, bot_id, db, ttl=7200):
        super().__init__(bot_id, ttl)
        self.db = db

    @coroutine
    def restore(self):
        if self.stages is None:
            self.stages = {}
            cur = yield self.db.execute('SELECT key, stage, data, created_at FROM stages WHERE bot_id = %s',
                                        (self.bot_id, ))

            for key, stage, data, created_at in cur.fetchall():
                self.stages[key] = {
                    'stage': stage,
                    'data': data,
                    'created_at': created_at
                }

            logging.debug('Loaded %d stages info for bot %d', len(self.stages), self.bot_id)

    def __setitem__(self, key, value):
        super(PersistentStages, self).__setitem__(key, value)
        f = self.db.execute('INSERT INTO stages (bot_id, key, stage, data, created_at) VALUES '
                            '(%s, %s, %s, %s, %s) '
                            'ON CONFLICT ON CONSTRAINT stages_pkey DO UPDATE SET stage = EXCLUDED.stage, '
                            'data = EXCLUDED.data, created_at = EXCLUDED.created_at',
                            (self.bot_id, key, self.stages[key]['stage'], dumps(value[1]), self.stages[key]['created_at']))

        IOLoop.current().add_future(f, lambda x: None)

    def __delitem__(self, key):
        super(PersistentStages, self).__delitem__(key)
        f = self.db.execute('DELETE FROM stages WHERE bot_id = %s AND key = %s', (self.bot_id, key))
        IOLoop.current().add_future(f, lambda x: None)
