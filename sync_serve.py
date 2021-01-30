#!/usr/bin/env python3

import io
import time
import datetime
import os
import logging
import base64
import pymysql
from flask import Flask, request, send_file
from flask_restful import Resource, Api

jarvis_url = os.environ.get('JARVIS_URL', 'http://your_jarvis_url')

db = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'user': os.environ.get('DB_USER', 'jarvis'),
    'pass': os.environ.get('DB_PASS', 'jarvispass'),
    'db': os.environ.get('DB_NAME', 'jarvis'),
    'commit': bool(os.environ.get('DB_COMMIT', True))
}

cfg = {
    'app': os.environ.get('CFG_APP', 'IOT-SERVESYNC'),
    'web_port': int(os.environ.get('WEB_PORT', 8899))
}


log = logging.getLogger(str(cfg['app']))
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)

app = Flask(__name__)
api = Api(app)
ctx = app.app_context()


def check_payload(req, payload):
    if req is None:
        return False
    for x in req:
        if x not in payload:
            log.error(f'[PAYLOAD] Missing {x} in payload')
            return False
    return True

class DB():
    def __init__(self):
        self.connect()

    def connect(self):
        self.db = pymysql.connect(host=db['host'], password=db['pass'], db=db['db'], autocommit=db['commit'], user=db['user'], cursorclass=pymysql.cursors.DictCursor)
        self.cur = self.db.cursor()
        return self.cur

    def check(self):
        self.db.ping(reconnect=True)
        try:
            self.cur.execute('SELECT 1')
        except Exception as error:
            self.db.ping(reconnect=True)
            log.info(f'[DB] DB Handler Died.. reconnecting {error}')
        return self.cur

    def cursor(self):
        return self.cur

    def check_apikey(self, apikey):
        self.check()
        self.cur.execute('SELECT * FROM api_key WHERE token=%s', (apikey))
        rows = self.cur.fetchall()
        if rows is None:
            return False
        for row in rows:
            if row['token'] == apikey:
                return row['origin']
        return False

    def get_tts(self, query_hash, binary=False):
        self.check()
        self.cur.execute("SELECT result FROM tts WHERE hash=%s", (query_hash))
        rows = self.cur.fetchall()
        if rows is None:
            return False
        for row in rows:
            if not binary:
                return row['result']
            return base64.b64decode(row['result'])
        return False


cast_control = {}
class ServeMedia(Resource):
    def __init__(self):
        self.db = DB()
        self.cast_timeout = 3
        self.sync_timeout = 0.5

    def get(self, media_id):
        global cast_control
        media_binary = self.db.get_tts(media_id, binary=True)
        if not media_binary:
            return 'NOT-FOUND', 404
        media_file = f'{media_id}.mp3'.replace(' ', '_')
        current_step = 0.0
        if media_id not in cast_control:
            while self.sync_timeout > current_step:
                current_step += 0.1
                time.sleep(0.1)
            # give half second for sync, just in case
            if media_id not in cast_control:
                log.info(f'[CAST-CONTROL] Not Found Cast Control Information for {media_id}')
                return send_file(io.BytesIO(media_binary), mimetype='audio/mp3', as_attachment=True, attachment_filename=media_file)
        # Synchronism starts (Case: First)
        if cast_control[media_id]['served']:
            log.info(f'[CAST-CONTROL] Already Consumed Control Information for {media_id} >> Serving with no Delay')
            return send_file(io.BytesIO(media_binary), mimetype='audio/mp3', as_attachment=True, attachment_filename=media_file)
        cast_control[media_id]['cast_count'] += 1
        if cast_control[media_id]['cast_count'] == 1:
            cast_control[media_id]['start'] = datetime.datetime.now()
            cast_control[media_id]['end'] = cast_control[media_id]['start'] + datetime.timedelta(seconds=cast_control[media_id]['timeout'])
        log.info(f"[CAST-CONTROL] ({media_id}) [{cast_control[media_id]['cast_count']}/{cast_control[media_id]['dev_count']}] in sync")
        while datetime.datetime.now() < cast_control[media_id]['end'] and cast_control[media_id]['cast_count'] < cast_control[media_id]['dev_count']:
            time.sleep(0.03)
        log.info(f"[CAST-CONTROL] ({media_id}) Achieved Syncronism IO at {time.time()} in {datetime.datetime.now() - cast_control[media_id]['start']}!!")
        cast_control[media_id]['served'] = True
        return send_file(io.BytesIO(media_binary), mimetype='audio/mp3', as_attachment=True, attachment_filename=media_file)

    def post(self):
        global cast_control
        try:
            payload = request.get_json()
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}
        required = ['secret', 'media_id', 'dev_count']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        origin = self.db.check_apikey(payload['secret'])
        if not origin:
            msg['error'] = 'APIKEY Not found'
            return msg, 401
        cast_timeout = payload.get('timeout', self.cast_timeout)
        cast_id = payload['media_id']
        cast_control[cast_id] = {
            # Start & End is computed by the first request
            'start': False,
            'end': False,
            'dev_count': payload['dev_count'],
            'cast_count': 0,
            'timeout': cast_timeout,
            'served': False
        }
        log.debug(f'[CAST-CONTROL] Added {cast_id} to cast_control >> {cast_control}')
        return cast_control[cast_id], 200, {'Content-Type': 'application/json'}


class TestWeb(Resource):
    def post(self):
        return 'OK', 200

    def get(self):
        return 'OK', 200


api.add_resource(TestWeb, '/test')
api.add_resource(ServeMedia, '/media', '/media/<media_id>')


if __name__ == '__main__':
    app.run(debug=False, port=cfg['web_port'], host='0.0.0.0', threaded=True)
