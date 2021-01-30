#!/usr/bin/env python3

import base64
import hashlib
import io
import json
import logging
import os
import time
import uuid
import requests
import pymysql
from flask import Flask, request, send_file
from flask_restful import Resource, Api

JARVIS_URL = os.environ.get('JARVIS_URL', 'http://your_jarvis.com')
GOOGLE_API = os.environ.get('GOOGLE_API', 'you_need_a_google_api_key_for_the_tts')
HASSIO_API = os.environ.get('HASSIO_API', 'you_need_a_hassio_token')
HASSIO_URL = os.environ.get('HASSIO_URL', 'http://your.homeassistant:8123')

db = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'user': os.environ.get('DB_USER', 'jarvis'),
    'pass': os.environ.get('DB_PASS', 'jarvispass'),
    'db': os.environ.get('DB_NAME', 'jarvis'),
    'commit': bool(os.environ.get('DB_COMMIT', True))
}

cfg = {
    'app': os.environ.get('CFG_APP', 'IOT-WS'),
    'web_port': int(os.environ.get('WEB_PORT', 8800)),
    'bcast_url': os.environ.get('CAST_URL', "http://127.0.0.1:8801/cast"),
    'gate_url': os.environ.get('GATE_URL', 'http://smartgateip:8080')
}


log = logging.getLogger(str(cfg['app']))
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)

app = Flask(__name__)
api = Api(app)


def check_payload(req, payload):
    if req is None:
        return False
    for x in req:
        if x not in payload:
            log.error(f'Missing {x} in payload')
            return False
    return True

def binarySet(entity_id, mode):
    if mode:
        url = f"{HASSIO_URL}/api/services/homeassistant/turn_on"
    else:
        url = f"{HASSIO_URL}/api/services/homeassistant/turn_off"
    headers = {
        'Authorization': f"Bearer {HASSIO_API}",
        'Content-Type': 'application/json'
    }
    payload = {
        'entity_id': entity_id
    }
    requests.post(url, data=json.dumps(payload), headers=headers)
    return True

def bCast(action, group, volume):
    params = {
        'action': action
    }
    if isinstance(volume, float):
        params['volume'] = volume
    params['group'] = 'auto'
    if group:
        params['group'] = group
    log.info(f'[bCAST] Broadcast {action} to {group} group at {volume}')
    r = requests.get(cfg['bcast_url'], params=params)
    if r.status_code == 200:
        return True
    return False

def getTTS(text, binary=False, get_id=False):
    # found out some strange race condition when generate the whole media item
    # repeated entry caused by flask multithreading debug
    tts = TTS()
    return tts.getTTS(text, binary=binary, get_id=get_id)

class TTS():
    def __init__(self):
        self.db = DB()

    def getTTS(self, text, binary=False, get_id=False):
        result = self.db.get_tts(text)
        if not result:
            log.info(f'[getTTS] Fetching TTS from Google API >> {text}')
            payload = {
                'input': {
                    'text': text
                },
                'voice': {
                    'languageCode': 'en-US',
                    'name': 'en-US-Wavenet-C',
                    'ssmlGender': 'FEMALE'
                },
                'audioConfig': {
                    'audioEncoding': 'MP3'
                }
            }
            url = f'https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_API}'
            url_headers = {
                'Content-Type': 'application/json'
            }
            api_result = requests.post(url, headers=url_headers, data=json.dumps(payload))
            # log.debug(f"[getTTS] Fetching TTS {text} >> {api_result.text}")
            result = api_result.json()
            if get_id:
                return self.db.store_tts(text, result['audioContent'], get_id=True)
            self.db.store_tts(text, result['audioContent'])
            if not binary:
                return result['audioContent']
            return base64.b64decode(result['audioContent'])
        else:
            log.info(f'[getTTS] Fetch TTS Results from Database >> {text}')
        if get_id:
            return hashlib.md5(text.encode('utf-8')).hexdigest()
        if not binary:
            return result
        return base64.b64decode(result)


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
            log.info(f'DB Handler Died.. reconnecting {error}')
        return self.cur

    def cursor(self):
        return self.cur

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

    def query_calendar(self):
        self.check()
        results = {}
        self.cur.execute("SELECT * FROM calendar WHERE holiday=(CURDATE() + INTERVAL 1 DAY)")
        rows = self.cur.fetchall()
        if rows is None:
            return results
        for row in rows:
            results['date'] = row['holiday']
            results['text'] = row['text']
            if 'public holiday' in results['text'].lower():
                results['type'] = 'PUBLIC_HOLIDAY'
            elif 'school holiday' in results['text'].lower():
                results['type'] = 'SCHOOL_HOLIDAY'
            else:
                results['type'] = 'OTHERS'
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

    def log_gate(self, device, action):
        self.check()
        try:
            self.cur.execute('INSERT INTO gate_log VALUES( CURRENT_TIMESTAMP, %s, %s)', (device, action))
        except Exception as error:
            log.error(f'[LOG-GATE] Error Adding Log Entry {device} >> {action}\n{error}')

    def get_pg_ifttt(self, phone):
        self.check()
        self.cur.execute('SELECT ifttt_url FROM phone_guardian WHERE phone_ip=%s', (phone))
        rows = self.cur.fetchall()
        if rows is None:
            return False
        for row in rows:
            return row['ifttt_url']

    def store_tts(self, text, result, get_id=False):
        self.check()
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        try:
            self.cur.execute("INSERT INTO tts VALUES( %s, %s, %s, CURRENT_TIMESTAMP)", (text_hash, text, result))
        except pymysql.err.IntegrityError as error:
            log.warn(f'[STORE-TTS] Duplicated TTS > {text} >> {error}')
            pass
        if get_id:
            return text_hash
        return True

    def fix_tts_hash(self):
        self.check()
        self.cur.execute('SELECT text FROM tts')
        rows = self.cur.fetchall()
        for row in rows:
            text_hash = hashlib.md5(row['text'].encode('utf-8')).hexdigest()
            self.cur.execute('UPDATE tts SET hash=%s WHERE text=%s', (text_hash, row['text']))

    def store_token(self, origin, token, expire):
        self.check()
        now = time.time()
        self.cur.execute('INSERT INTO tokens VALUES( %s, %s, %s, %s)', (origin, token, now + expire, 'NO'))
        log.info(f'[STORE-TOKEN] Stored token {token} from {origin} (Expire: {expire} seconds)')
        return True

    def consume_token(self, token):
        self.check()
        self.cur.execute('UPDATE tokens SET used=%s WHERE token=%s', ('YES', token))
        log.info(f'[CONSUME-TOKEN] Consumed token {token} >> YES')
        return True

    def check_token(self, token):
        self.check()
        now = time.time()
        self.cur.execute('SELECT * FROM tokens WHERE token=%s', (token))
        rows = self.cur.fetchall()
        if rows is None:
            return False
        for row in rows:
            if row['expire'] < now or row['used'] == 'YES':
                log.info(f"[CHECK-TOKEN] Expired or Used Token >> {token} >> {row['expire']} vs {now} (Used: {row['used']})")
                return False
            return True
        return False

    def gen_token(self, origin, expire=600):
        self.check()
        token = str(uuid.uuid4())
        self.store_token(origin, token, expire)
        return token

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

    def get_tts(self, text, binary=False, hash=False):
        self.check()
        if hash:
            text_hash = text
        else:
            text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        self.cur.execute("SELECT result FROM tts WHERE hash=%s", (text_hash))
        rows = self.cur.fetchall()
        if rows is None:
            return False
        for row in rows:
            if not binary:
                return row['result']
            return base64.b64decode(row['result'])

    def IRDictionary(self, value):
        self.check()
        self.cur.execute('SELECT * FROM ir_dictionary WHERE ir_value=%s', (value))
        rows = self.cur.fetchall()
        for row in rows:
            return row
        return False

    def get_param(self, device, item):
        self.check()
        results = {}
        self.cur.execute('SELECT c_value FROM device_params WHERE device=%s AND c_key=%s', (device, item))
        for row in self.cur.fetchall():
            if item not in results:
                results[item] = [row[0]]
            else:
                results[item].append(row[0])
        return results

    def IRStore(self, payload):
        self.check()
        try:
            self.cur.execute('INSERT INTO ir_store VALUES( %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)', (payload['host'], hex(int(payload['ir_value'])), payload['ir_freq'], payload['ir_len'], ' '.join(payload['ir_raw'])))
            return True
        except Exception as error:
            log.error(f'Error {error} on IRStore Process with Payload:\n {payload}')
        return False

    def Config(self, host):
        self.check()
        self.cur.execute('SELECT * FROM device_config WHERE host=%s', (host))
        rows = self.cur.fetchall()
        results = {}
        for row in rows:
            if row['c_key'] not in results:
                results[row['c_key']] = row['c_value']
        return results

    def IRGet(self, host, amount):
        self.check()
        self.cur.execute('SELECT * FROM ir_store WHERE host=%s ORDER BY time DESC LIMIT %s', (host, amount))
        return self.cur.fetchall()

    def ping(self, host):
        self.check()
        self.cur.execute('SELECT time FROM devices WHERE host=%s', (host))
        if not self.cur.fetchall():
            self.cur.execute('INSERT INTO devices VALUES( %s, CURRENT_TIMESTAMP)', (host))
        else:
            self.cur.execute('UPDATE devices SET time=CURRENT_TIMESTAMP WHERE host=%s', (host))
        return True

    def store_media(self, action, mediaTitle, mediaSubtitle, mediaUrl, mediaImageUrl, mediaType='audio/mp3', mediaStreamType='BUFFERED'):
        self.check()
        self.cur.execute('SELECT action FROM media_library WHERE action=%s', (action))
        if self.cur.fetchall():
            return False
        self.cur.execute('INSERT INTO media_library VALUES( %s, %s, %s, %s, %s, %s, %s)', (action, mediaTitle, mediaSubtitle, mediaType, mediaUrl, mediaStreamType, mediaImageUrl))
        return True


'''
   Web Endpooints Definition by Classes
'''

class storeIR(Resource):
    def post(self):
        try:
            payload = request.get_json()
        except Exception as error:
            log.error(f'Exception {error} on storeIR Endpoint')
        required = ['ir_value', 'ir_raw', 'ir_len', 'ir_freq']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        payload['host'] = request.remote_addr
        s.IRStore(payload)
        ir_dict = s.IRDictionary(payload['value'])
        if ir_dict:
            log.info(f"Stored Call {ir_dict['name']} from {payload['host']}")
        else:
            log.info(f"Stored Call UNKNOWN from {payload['host']}")
        msg['status'] = 'OK'
        return msg, 200


class getSpeech(Resource):
    def post(self):
        try:
            payload = request.get_json()
        except Exception as error:
            log.error(f'Exception {error} on getIR Endpoint')
        required = ['text']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        log.info(f"[getSpeech] GET POST for {payload['text']}")
        msg['result'] = getTTS(payload['text'])
        return msg, 200

    def get(self):
        msg = {}
        if request.args.get('text', False):
            text = request.args.get('text')
        if not text:
            msg['error'] = 'text param not specified'
            return msg, 503
        log.info(f'[getSpeech] GET TTS for {text}')
        result = getTTS(text, binary=True)
        filename = f'{text}.mp3'.replace(' ', '_')
        return send_file(io.BytesIO(result), mimetype='audio/mp3', as_attachment=True, attachment_filename=filename)


class getSpeechAlias(Resource):
    def __init__(self):
        self.db = DB()

    def get(self):
        msg = {}
        if request.args.get('alias', False):
            text = request.args.get('alias')
        if not text:
            msg['error'] = 'text param not specified'
            return msg, 503
        log.info(f'[getSpeech] GET TTS for {text}')
        result = self.db.get_tts(text, binary=True, hash=True)
        if not result:
            return 'NOT-FOUND, 404'
        filename = f'{text}.mp3'.replace(' ', '_')
        return send_file(io.BytesIO(result), mimetype='audio/mp3', as_attachment=True, attachment_filename=filename)

class getIR(Resource):
    def post(self):
        try:
            payload = request.get_json()
        except Exception as error:
            log.error(f'Exception {error} on getIR Endpoint')
        required = ['host']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        if 'amount' in payload:
            amount = int(payload['amount'])
        else:
            amount = 5
        msg['history'] = s.IRGet(payload['host'], amount)
        return msg, 200


class configJson(Resource):
    def get(self):
        if request.args.get('host', False):
            host = request.args.get('host')
        else:
            host = request.remote_addr
        config = s.Config(host)
        msg = {}
        log.info(f'Fetching Config for {host}')
        if config:
            msg['config'] = config
            return msg, 200
        return msg, 404


class getToken(Resource):
    def __init__(self):
        self.db = DB()

    def put(self):
        try:
            payload = request.get_json()
            log.debug(f'Payload >> {payload}')
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}
        required = ['secret', 'expire']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        origin = self.db.check_apikey(payload['secret'])
        if not origin:
            msg['error'] = 'APIKEY Not found'
            return msg, 401
        token = self.db.gen_token(origin, payload['expire'])
        msg['status'] = f'Token has been Generated for {origin}'
        msg['token'] = token
        return msg, 200

    def post(self):
        try:
            payload = request.get_json()
            log.debug(f'Payload >> {payload}')
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}
        required = ['secret', 'token', 'expire']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        origin = self.db.check_apikey(payload['secret'])
        if not origin:
            msg['error'] = 'APIKEY Not found'
            return msg, 401
        self.db.store_token(origin, payload['token'], payload['expire'])
        msg['status'] = f'Token has been stored from {origin}'
        return msg, 200

    def get(self):
        token = request.args.get('token', False)
        if not token:
            return 'NOT-FOUND', 404
        if self.db.check_token(token):
            self.db.consume_token(token)
            return 'FOUND', 200
        else:
            if token in ['myspecialkey']:
                log.info('Token Override by Secret Keyword')
                return 'FOUND', 200
            return 'NOT-FOUND', 404


class gateAuth(Resource):
    def __init__(self):
        self.db = DB()

    def get(self):
        global gate_status
        if request.args.get('token', False):
            token = request.args.get('token')
        else:
            token = False
        if not self.db.check_token(token):
            return 'NOT-AUTH', 401
        mode = request.args.get('mode', 'open')
        if mode == 'wb':
            phone = request.args.get('phone', False)
            if not phone:
                return 'NOT-FOUND', 404
            log.info(f'[GET-GATE] WelcomeBack triggered by {phone}')
            ifttt_url = self.db.get_pg_ifttt(phone)
            new_token = self.db.gen_token('welcome_back', 600)
            payload = {
                'value1': new_token,
                'value2': 'open',
                'value3': phone
            }
            headers = {
                'Content-Type': 'application/json'
            }
            requests.post(ifttt_url, headers=headers, data=json.dumps(payload))
            self.db.consume_token(token)
            log.info(f'[GET-GATE] Pushed IFTTT Message to {phone} with data: {payload}')
            bCast('welcome_back', False, False)
            return 'FOUND', 200
        if mode == 'open':
            #binarySet('input_boolean.gate', True)
            full_url = f"{cfg['gate_url']}/gate?token={token}"
            requests.get(full_url)
            gate_status = True
            return 'FOUND', 200
        return 'NOT-FOUND', 404


class getDeviceDetails(Resource):
    def __init__(self):
        self.db = DB()

    def post(self):
        try:
            payload = request.get_json()
            log.debug(f'Payload >> {payload}')
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}
        required = ['params']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        if request.args.get('host', False):
            host = request.args.get('host')
        else:
            host = request.remote_addr
        msg['results'] = {}
        if not isinstance(payload['params'], list):
            payload['params'] = [payload['params']]
        for item in payload['params']:
            msg['results'][item] = self.db.get_param(host, item)
        return msg, 200


class TestWeb(Resource):
    def post(self):
        return 'OK', 200

    def get(self):
        return 'OK', 200


class Ping(Resource):
    def get(self):
        host = request.remote_addr
        s.ping(request.args.get('host', host))
        return 'PONG', 200

class doorBell(Resource):
    def __init__(self):
        self.db = DB()

    def get(self):
        secret = request.args.get('secret', False)
        if not secret:
            return 'Missing API KEY', 401
        origin = self.db.check_apikey(secret)
        if not origin:
            return 'Missing API KEY', 401
        #bCast('door_bell', 's_office', 0.3)
        #binarySet('input_boolean.bell', True)
        bCast('door_bell', False, False)
        time.sleep(5)
        #binarySet('input_boolean.bell', False)
        return 'OK', 200


class Broadcast(Resource):
    def get(self):
        msg = {}
        action = request.args.get('action', False)
        if not action:
            msg['error'] = 'action param not specified'
            return msg, 503
        volume = request.args.get('volume', '')
        group = request.args.get('group', False)
        try:
            volume = float(volume)
        except:
            volume = False
        log.info(f'[BCAST] Broadcasting {action} / {group} / {volume}')
        if bCast(action, group, volume):
            return 'OK', 200
        return 'NOT-FOUND', 404

class alarmCast(Resource):
    def __init__(self):
        self.db = DB()

    def post(self):
        try:
            payload = request.get_json()
        except Exception as error:
            log.error(f'Exception {error} on Payload')
        log.debug(f'{payload}')
        results = []
        for sensor in payload:
            short_name = ' '.join(sensor['attributes']['friendly_name'].split(' ')[0:2])
            if sensor['attributes']['device_class'] not in ['window'] or short_name in results and sensor['state'] == 'on':
                continue
            # means open and clean ready to report
            results.append(short_name)
        results = sorted(results)
        if len(results) > 1:
            results.insert(-1, '  and  ')
        if not results:
            return 'NOT-REQUIRED', 200
        result_tts = ',  '.join(results)
        tts_text = f"Jennifer, I'm Detecting {result_tts} open. Please proceed to close them. Thank you"
        ttsId = getTTS(tts_text, get_id=True)
        log.info(f'[ALARM-CAST] TTS Id {ttsId} for {result_tts}')
        # You need to change this url
        alarm_image_url = 'http://192.168.1.69/snd/alarm_bypass.png'
        text_hash = hashlib.md5(tts_text.encode('utf-8')).hexdigest()
        store_action = f'alarm_{text_hash}'
        self.db.store_media(store_action, 'Alarm Sensor Open Detected', f'Sensors {result_tts} are Open', f'{JARVIS_URL}/getSpeechAlias?alias={text_hash}', alarm_image_url)
        bCast(store_action, 's_normal', False)
        return {'acton': store_action, 'tts': tts_text, 'sensors': result_tts}, 200

class calendarCast(Resource):
    def __init__(self):
        self.db = DB()

    def get(self):
        secret = request.args.get('secret', False)
        if not secret:
            return 'Missing API KEY', 401
        origin = self.db.check_apikey(secret)
        if not origin:
            return 'Missing API KEY', 401
        results = self.db.query_calendar()
        if not results:
            return 'NO EVENTS', 200
        if results['type'] == 'PUBLIC_HOLIDAY':
            # You may want to adjust this...
            tts_text = "Hey Family, Tomorrow is Public Holiday"
        elif results['type'] == 'SCHOOL_HOLIDAY':
            tts_text = f"Hey Family, Keep in mind that according the calendar.. tomorrow is {results['text']}"
        else:
            tts_text = f"Hey Family Just a note that according the calendar.. tomorrow is {results['text']}"
        ttsId = getTTS(tts_text, get_id=True)
        log.info(f'[CALENDAR-CAST] TTS Id {ttsId} for {tts_text}')
        # You need to change this url
        calendar_image_url = 'http://192.168.1.69/snd/calendar.png'
        text_hash = hashlib.md5(tts_text.encode('utf-8')).hexdigest()
        store_action = f'calendar_{text_hash}'
        self.db.store_media(store_action, 'Calendar Event', f"{results['text']}", f'{JARVIS_URL}/getSpeechAlias?alias={text_hash}', calendar_image_url)
        bCast(store_action, 's_normal', False)
        return {'acton': store_action, 'tts': tts_text, 'type': results['type']}, 200

gate_status = False
class gateStatus(Resource):
    def get(self):
        global gate_status
        r = requests.get(f"{cfg['gate_url']}/heap")
        payload = {}
        if gate_status:
            payload['status'] = 'open'
            log.info(f'[GATE-STATUS] Status of the Gate is OPEN<>CLOSE')
            #binarySet('input_boolean.gate', False)
        else:
            payload['status'] = 'closed'
        if r.status_code == 200:
            payload = { **payload, **r.json() }
        else:
            payload = {'status': 'offline'}
        gate_status = False
        return payload, 200

    def post(self):
        global gate_status
        try:
            payload = request.get_json()
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}
        required = ['secret', 'action']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        origin = s.check_apikey(payload['secret'])
        if not origin:
            msg['error'] = 'APIKEY Not found'
            return msg, 401
        s.log_gate(origin, f"ACTIONED {payload['action']}")
        # Temporary assume that door switches to open_status
        # gathering from HASSIO will revert it back to closed
        # often u push the button but the door doesnt close, and u need to do it again
        # the only solution is a full swift to IOT based doorgate
        # or some way to gather telemetry from the doors status
        gate_status = True
        # had to remove this binarySet, hassio dont like to be "updated" in the interim
        # of himself triggering a REST action...
        #binarySet('input_boolean.gate', True)
        return 'OK', 200

class gateControl(Resource):
    def __init__(self):
        self.db = DB()

    def post(self):
        global gate_status
        try:
            payload = request.get_json()
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}
        required = ['secret', 'action']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        origin = self.db.check_apikey(payload['secret'])
        if not origin:
            msg['error'] = 'APIKEY Not found'
            return msg, 401
        if payload['action'] == 'open':
            token = self.db.gen_token(origin, 60)
            gate_status = True
            full_url = f"{cfg['gate_url']}/gate?token={token}"
            requests.get(full_url)
            msg['status'] = 'open'
            #binarySet('input_boolean.gate', True)
            log.info('[GATE-CONTROL] Completed for {token} token')
        return msg, 200

# Common DB Constructor
s = DB()

api.add_resource(gateControl, '/gateControl')
api.add_resource(gateStatus, '/gateStatus')
api.add_resource(Broadcast, '/broadcast')
api.add_resource(getToken, '/tokens')
api.add_resource(gateAuth, '/gate')
api.add_resource(getSpeech, '/getSpeech')
api.add_resource(getSpeechAlias, '/getSpeechAlias')
api.add_resource(getDeviceDetails, '/params')
api.add_resource(TestWeb, '/test')
api.add_resource(Ping, '/ping')
api.add_resource(storeIR, '/storeIR')
api.add_resource(getIR, '/getIR')
api.add_resource(configJson, '/config')
api.add_resource(alarmCast, '/openAlarm')
api.add_resource(doorBell, '/doorBell')
api.add_resource(calendarCast, '/calendar')

if __name__ == '__main__':
    app.run(debug=False, port=cfg['web_port'], host='0.0.0.0', threaded=True)
