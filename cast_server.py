#!/usr/bin/env python3

import datetime
import json
import logging
import os
import uuid
import pychromecast
import pymysql
import requests
from flask import Flask, request
from flask_restful import Resource, Api

jarvis_url = os.environ.get('JARVIS_URL', 'http://your_jarvis_url')
jarvis_key = os.environ.get('JARVIS_KEY', 'a_jarvis_api_key')

db = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'user': os.environ.get('DB_USER', 'jarvis'),
    'pass': os.environ.get('DB_PASS', 'jarvispass'),
    'db': os.environ.get('DB_NAME', 'jarvis'),
    'commit': bool(os.environ.get('DB_COMMIT', True))
}

cfg = {
    'app': os.environ.get('CFG_APP', 'IOT-BCAST'),
    'web_port': int(os.environ.get('WEB_PORT', 8801))
}


log = logging.getLogger(str(cfg['app']))
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)

app = Flask(__name__)
api = Api(app)

class DB():
    def __init__(self):
        self.connect()

    def connect(self):
        self.db = pymysql.connect(host=db['host'], password=db['pass'], db=db['db'], autocommit=db['commit'], user=db['user'], cursorclass=pymysql.cursors.DictCursor)
        self.cur = self.db.cursor()
        return self.cur

    def check(self):
        try:
            self.cur.execute('SELECT 1')
        except Exception as error:
            self.connect()
            log.info(f'[DB] DB Handler Died.. reconnecting {error}')
        return self.cur

    def cursor(self):
        return self.cur

    def get_scene(self, action):
        self.check()
        self.cur.execute('SELECT scene FROM media_scene WHERE action=%s', (action))
        for row in self.cur.fetchall():
            log.info(f'[GET-SCENE] Get {row} scene for {action}')
            return row['scene']
        return 's_normal'

    def get_bcast_groups(self):
        self.check()
        results = {}
        self.cur.execute("SELECT * FROM bcast_group WHERE enabled='1'")
        rows = self.cur.fetchall()
        if rows is None:
            return results
        for row in rows:
            group_name = row['name']
            if group_name not in results:
                results[group_name] = []
            results[group_name].append({
                'uuid': uuid.UUID(row['uuid']),
                'start': row['start'],
                'end': row['end'],
                'volume': row['volume'] / 100.0
            })
        results['auto'] = results['s_normal']
        return results

    def get_bcast_dev(self):
        self.check()
        results = {}
        self.cur.execute("SELECT * FROM bcast_dev WHERE enabled='1'")
        rows = self.cur.fetchall()
        if rows is None:
            return results
        for row in rows:
            results[row['name']] = row['id']
        return results

    def get_media(self, action):
        self.check()
        results = {}
        self.cur.execute("SELECT * FROM media_library WHERE action=%s", (action))
        rows = self.cur.fetchall()
        if rows is None:
            return results
        for row in rows:
            results[row['action']] = {}
            for x in row:
                if x == 'action':
                    continue
                results[row['action']][x] = row[x]
        return results


class CastServer():
    def __init__(self):
        self.db = DB()
        self.groups = self.db.get_bcast_groups()
        self.devices = {}
        self.uuids = []
        self.cast = False
        self.sync_cast = True

    def is_time(self, start, end):
        now = datetime.datetime.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        now = now - midnight
        if now >= start and now <= end:
            log.debug(f'[is_time] {start} - {end} vs {now} is in range')
            return True
        log.debug(f'[is_time] {start} - {end} vs {now} is NOT in range')
        return False

    def get_scene(self, action):
        return self.db.get_scene(action)

    def get_devices(self, group='s_normal'):
        if group in self.groups:
            return self.groups[group]
        if group == 'auto':
            return self.groups['s_normal']
        return []

    def get_media(self, action):
        data = self.db.get_media(action)
        if action in data:
            return {
                'url': data[action]['mediaUrl'],
                'content_type': data[action]['mediaType'],
                'title': data[action]['mediaTitle'],
                'thumb': data[action]['mediaImageUrl']
            }

    def sync_advise(self, media_id, dev_count, timeout=5):
        payload = {
            'media_id': media_id,
            'dev_count': dev_count,
            'timeout': timeout,
            'secret': jarvis_key
        }
        headers = {
            'Content-Type': 'application/json'
        }
        try:
            result = requests.post(f'{jarvis_url}/media', headers=headers, data=json.dumps(payload))
            log.debug(f'[SYNC-ADVISE] Pushed {media_id} for {dev_count} max {timeout}s for synchronism ({result.status_code})')
        except Exception as error:
            log.error(f'[SYNC-ADVISE] Error handled on sync_advise >>\n {error}')
            return False
        return True

    def bcast_media(self, action, group='s_normal', volume=False, tts=False):
        devices = self.get_devices(group=group)
        self.media = self.get_media(action)
        if tts:
            self.media['url'] = tts
        if not self.media:
            return False
        if not devices:
            return False
        for device in devices:
            self.uuids.append(device['uuid'])
            self.devices[device['uuid']] = device
            log.debug(f'[BCAST-MEDIA] Added {device} from {group} group')
        # Arrived a point, with many speakers.. this turns slow.. need to think how to revamp this piece.
        self.cast, self.browser = pychromecast.get_listed_chromecasts(uuids=self.uuids)
        # Iterate twice, to open the socket and broadcast nearly simultaneously
        if 'getSpeechAlias' in self.media['url']:
            self.media_id = self.media['url'].split('=')[-1]
        elif f'{jarvis_url}/media/' in self.media['url']:
            self.media_id = self.media['ur'].split('/')[-1]
        else:
            self.sync_cast = False
        if self.sync_cast:
            self.sync_cast_url = f'{jarvis_url}/media/{self.media_id}'
            self.media['url'] = self.sync_cast_url
            log.info(f'[BCAST-MEDIA] Initiating Synchronism Request to Sync-Serve.. {self.media_id} as {self.sync_cast_url}')
            self.sync_advise(self.media_id, len(self.cast), timeout=5)
        log.debug(f'[BCAST-MEDIA] Current Casts: ({len(self.cast)}/{len(self.uuids)}) {self.cast}')
        for curr_device in self.cast:
            uuid = curr_device.uuid
            if not volume:
                volume = self.devices[uuid]['volume']
            if self.is_time(self.devices[uuid]['start'], self.devices[uuid]['end']):
                curr_device.wait()
                curr_device.set_volume(volume)
            else:
                log.debug(f'[BCAST-MEDIA] Skipped {uuid} by scene time set')
        for curr_device in self.cast:
            uuid = curr_device.uuid
            if self.is_time(self.devices[uuid]['start'], self.devices[uuid]['end']):
                log.info(f'[BCAST-MEDA] Broadcast {self.media} to {uuid} at {volume} volume')
                curr_device.play_media(**self.media)
            else:
                log.info(f'[BCAST-MEDA] IGNORE Broadcast {self.media} to {uuid} <OUT OF SCHEDULE>')
        return self.cast

class CastWeb(Resource):
    def get(self):
        msg = {}
        action = request.args.get('action', False)
        if not action:
            msg['error'] = 'action param not specified'
            return msg, 503
        volume = request.args.get('volume', False)
        group = request.args.get('group', False)
        tts = request.args.get('tts', False)
        if volume:
            volume = float(volume)
        curr_cast = CastServer()
        if group == 'auto' or not group:
            group = curr_cast.get_scene(action)
        if curr_cast.bcast_media(action, group=group, volume=volume, tts=tts):
            return 'OK', 200
        return 'NOT-FOUND', 404

class TestWeb(Resource):
    def post(self):
        return 'OK', 200

    def get(self):
        return 'OK', 200

api.add_resource(CastWeb, '/cast')
api.add_resource(TestWeb, '/test')

if __name__ == '__main__':
    app.run(debug=False, port=cfg['web_port'], host='0.0.0.0', threaded=False)
