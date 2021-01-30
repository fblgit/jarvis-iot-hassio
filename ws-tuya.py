#!/usr/bin/env python3

import time
import os
import logging
import pymysql
from flask import Flask, request
from flask_restful import Resource, Api
from tuyaface.tuyaclient import TuyaClient
from tuyaface.tuyaclient import logging as tuyalog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from tuya_devices import GATHER_DEVICES

executors = {
    'default': ThreadPoolExecutor(1),
    'processpool': ProcessPoolExecutor(1)
}

sched = BackgroundScheduler(timezone='Asia/Singapore', job_defaults={'max_instances': 1, 'coalesce': True})

db = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'user': os.environ.get('DB_USER', 'jarvis'),
    'pass': os.environ.get('DB_PASS', 'jarvispass'),
    'db': os.environ.get('DB_NAME', 'jarvis'),
    'commit': bool(os.environ.get('DB_COMMIT', True))
}

cfg = {
    'app': os.environ.get('CFG_APP', 'IOT-TUYA'),
    'web_port': int(os.environ.get('WEB_PORT', 8844))
}

log = logging.getLogger(str(cfg['app']))
log.addHandler(logging.StreamHandler())
if os.environ.get('DEBUG', False):
    log.setLevel(logging.DEBUG)
else:
    log.setLevel(logging.INFO)

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

    def exist_sensor(self, name, key):
        self.check()
        self.cur.execute('SELECT time FROM sensor_readings WHERE sensor=%s AND key_name=%s', (name, key))
        rows = self.cur.fetchall()
        if rows is None:
            return False
        if len(rows) > 0:
            return True
        return False

    def update_sensor(self, name, key, value):
        self.check()
        if not self.exist_sensor(name, key):
            self.cur.execute('INSERT INTO sensor_readings VALUES ( %s, %s, %s, CURRENT_TIMESTAMP)', (name, key, value))
        else:
            self.cur.execute('UPDATE sensor_readings SET key_value=%s WHERE key_name=%s AND sensor=%s', (value, key, name))
        return True

    def get_sensor(self, name):
        self.check()
        payload = {}
        self.cur.execute('SELECT key_name, key_value FROM sensor_readings WHERE sensor=%s', (name))
        rows = self.cur.fetchall()
        for row in rows:
            for col in row.keys():
                try:
                    payload[row['key_name']] = float(row['key_value'])
                except:
                    payload[row['key_name']] = row['key_value']
        return payload

class SensorScheduler():
    def __init__(self):
        self.devices = {}
        self.gather = GATHER_DEVICES
        self.db = DB()
        tuyalog.getLogger().setLevel(tuyalog.CRITICAL)
        for device in self.gather.keys():
            if 'sensor' in device:
                handler = TuyaClient(self.gather[device], self.on_status, self.on_connect)
                log.info(f'[S-CONN] Connecting to {device} device {self}')
                self.devices[device] = handler
                self.devices[device].start()
                log.info(f'[S-CONN] Connected to {device} device {self}')
                time.sleep(1)

    def conn(self, device):
        if device in self.gather and device not in self.devices:
            log.debug(f'[S-CONN] Connecting to {device} device')
            #self.devices[device] = TuyaClient(self.gather[device], self.on_status, self.on_connect)
            self.devices[device] = TuyaClient(self.gather[device])
            self.devices[device].start()

    def on_status(self, arg_one, arg_two=False):
        log.debug(f'[S-ON-STATUS] >> {arg_one} / {arg_two}')

    def on_connect(self, arg_one, arg_two=False):
        log.debug(f'[S-ON-CONN] >> {arg_one} / {arg_two}')

    def get_handler(self, device):
        if device in self.devices:
            return self.devices[device]
        return False

    def get_th_sensor(self):
        for device in self.devices:
            log.debug(f'[S-GET-TH-SENSOR] Running for {device}..')
            data = self.devices[device].status()
            if not isinstance(data, dict):
                log.debug(f'[S-GET-TH-SENSOR] Error Gathering {device}')
                continue
            if 'dps' not in data:
                log.debug(f'[S-GET-TH-SENSOR] Error Gatehring {device}')
                continue
            payload = {
                'temperature': float(data['dps']['105'] / 10.0),
                'humidity': float(data['dps']['106']),
                'alarm_temperature_low': data['dps'].get('107', 20),
                'alarm_temperature_high': data['dps'].get('108', 35),
                'alarm_humidity_low': data['dps'].get('109', 0),
                'alarm_humidity_high': data['dps'].get('110', 90),
                'status': 'on'
            }
            try:
                if payload['humidity'] > payload['alarm_humidity_high']:
                    payload['status'] = 'alarm_humidity_high'
                elif payload['humidity'] < payload['alarm_humidity_low']:
                    payload['status'] = 'alarm_humidity_low'
                if payload['temperature'] > payload['alarm_temperature_high']:
                    payload['status'] = 'alarm_temperature_high'
                elif payload['temperature'] < payload['alarm_temperature_low']:
                    payload['status'] = 'alarm_temperature_low'
                if payload['status'] != 'on':
                    payload['alarm'] = 'WARNING'
                else:
                    payload['alarm'] = 'HEALTHY'
            except:
                # Some sensor may return something weird sometime.. ignore it.
                pass
            log.info(f"[S-GET-TH] {device} >> {payload}")
            for entry in payload:
                self.db.update_sensor(device, entry, payload[entry])

class TuyaData():
    def __init__(self):
        self.devices = {}
        self.gather = GATHER_DEVICES
        #tuyalog.getLogger().setLevel(tuyalog.CRITICAL)
        self.db = DB()

    def conn(self, device):
        log.debug(f'[CONN] Connecting to {device} device')
        if device in self.gather:
            self.devices[device] = TuyaClient(self.gather[device], self.on_status, self.on_connect)

    def on_status(self, data: dict):
        log.debug(f'[ON-STATUS] >> {data}')

    def on_connect(self, value: bool):
        log.debug(f'[ON-CONN] >> {value}')

    def get_handler(self, device):
        if device in self.devices:
            return self.devices[device]
        return False

    def sunny_curtains(self, device):
        log.info(f'[CURTAINS] THIRD >> {device}')
        self.set_curtains(device, 33)

    def half_curtains(self, device):
        log.info(f'[CURTAINS] HALF >> {device}')
        self.set_curtains(device, 50)

    def open_curtains(self, device):
        log.info(f'[CURTAINS] OPEN >> {device}')
        self.set_curtains(device, 0)

    def close_curtains(self, device):
        log.info(f'[CURTAINS] CLOSE >> {device}')
        self.set_curtains(device, 100)

    def get_curtains(self, device):
        if device not in self.gather:
            return False
        self.conn(device)
        self.devices[device].start()
        for x in range(0, 3):
            data = self.devices[device].status()
            if isinstance(data, dict):
                if 'dps' in data:
                    break
            time.sleep(2)
        if not isinstance(data, dict):
            self.devices[device].stop_client()
            return False
        if 'dps' not in data:
            self.devices[device].stop_client()
            return False
        log.info(f'[GET-CURTAINS] {device} Data >> {data}')
        if '3' not in data['dps']:
            c_pos = data['dps']['2']
        else:
            c_pos = data['dps']['3']
        payload = {
            'position': data['dps']['2'],
            'current_position': c_pos,
            'status': data['dps']['1']
        }
        self.devices[device].stop_client()
        return payload

    def set_light_preset(self, device, preset):
        presets = {
            'low_warm': {
                'switch_led': True,
                'mode': 'white',
                'bright': 100,
                'temp': 0
            },
            'mid_warm': {
                'switch_led': True,
                'mode': 'white',
                'bright': 500,
                'temp': 0
            },
            'high_warm': {
                'switch_led': True,
                'mode': 'white',
                'bright': 1000,
                'temp': 0
            },
            'low_white': {
                'switch_led': True,
                'mode': 'white',
                'bright': 100,
                'temp': 1000
            },
            'mid_white': {
                'switch_led': True,
                'mode': 'white',
                'bright': 500,
                'temp': 1000
            },
            'high_white': {
                'switch_led': True,
                'mode': 'white',
                'bright': 1000,
                'temp': 1000
            }
        }
        colors = {
            'low_cyan': '00CC024E00FA',
            'mid_cyan': '00CC024E028A',
            'high_cyan': '00CC024E03E8',
            'low_blue': '00DF039800FA',
            'mid_blue': '00DF0398028A',
            'high_blue': '00DF039803E8',
            'low_deep_blue': '00F003E800FA',
            'mid_deep_blue': '00F003E8028A',
            'high_deep_blue': '00F003E803E8',
            'low_purple': '011903E800FA',
            'mid_purple': '011903E8028A',
            'high_purple': '011903E803E8',
            'low_red': '000003E800FA',
            'mid_red': '000003E8028A',
            'high_red': '000003E803E8',
            'low_orange': '001803E800FA',
            'mid_orange': '001803E8028A',
            'high_orange': '001803E803E8'
        }
        param_list = []
        value_list = []
        if preset in presets:
            for x in presets[preset]:
                param_list.append(x)
                value_list.append(presets[preset][x])
        if preset in colors:
            param_list = ['switch_led', 'mode', 'color']
            value_list = [True, 'colour', colors[preset]]
        if not param_list or not value_list:
            return False
        return self.set_light_combined(device, param_list, value_list)

    def set_light_combined(self, device, param_list, value_list):
        params = {
            'switch_led': '20',
            'mode': '21',
            'bright': '22',
            'temp': '23',
            'color': '24',
            'scene': '25'
        }
        values = {
            'switch_led': [True,False],
            'mode': ['white', 'colour', 'scene'],
            'bright': {'min': 10, 'max': 1000},
            'temp': {'min': 0, 'max': 1000}
        }
        payload = {}
        for x in range(0, len(param_list)):
            param = param_list[x]
            value = value_list[x]
            if param not in params:
                log.error(f'![SET-LIGHT] {param} not found')
                return False
            if param in values:
                if 'min' in values[param]:
                    if value < values[param]['min']:
                        log.error(f"![SET-LIGHT] Min value for {param} is {values[param]['min']} vs {value}")
                        return False
                if 'max' in values[param]:
                    if value > values[param]['max']:
                        log.error(f"![SET-LIGHT] Max value for {param} is {values[param]['max']} vs {value}")
                        return False
                if value not in values[param] and 'max' not in values[param]:
                    log.error(f"![SET-LIGHT] Value for {param} is {values[param]} vs {value}")
                    return False
            payload[params[param]] = value
        self.conn(device)
        self.devices[device].start()
        log.info(f"[SET-LIGHT] Set {payload} for {device}")
        self.devices[device].set_status(payload)
        self.devices[device].set_status(payload)
        self.devices[device].stop_client()
        return True

    def set_light(self, device, param, value):
        params = {
            'switch_led': '20',
            'mode': '21',
            'bright': '22',
            'temp': '23',
            'color': '24',
            'scene': '25'
        }
        values = {
            'switch_led': [True,False],
            'mode': ['white', 'colour', 'scene'],
            'bright': {'min': 10, 'max': 1000},
            'temp': {'min': 0, 'max': 1000}
        }
        if param not in params:
            log.error(f'![SET-LIGHT] {param} not found')
            return False
        if param in values:
            if 'min' in values[param]:
                if value < values[param]['min']:
                    log.error(f"![SET-LIGHT] Min value for {param} is {values[param]['min']}")
                    return False
            if 'max' in values[param]:
                if value > values[param]['max']:
                    log.error(f"![SET-LIGHT] Max value for {param} is {values[param]['max']}")
                    return False
            if value not in values[param]:
                log.error(f"![SET-LIGHT] Value for {param} is {values[param]}")
                return False
        self.conn(device)
        self.devices[device].start()
        log.info(f"[SET-LIGHT] Set {param} to {value} for {device}")
        self.devices[device].set_status({params[param]: value})
        self.devices[device].set_status({params[param]: value})
        self.devices[device].stop_client()
        return True

    def set_curtains(self, device, percentage):
        if device not in self.gather:
            return False
        self.conn(device)
        self.devices[device].start()
        #action = '1'
        position = '2'
        current_pos = '3'
        for x in range(0, 3):
            data = self.devices[device].status()
            if isinstance(data, dict):
                if 'dps' in data:
                    break
            time.sleep(2)
        if not isinstance(data, dict):
            self.devices[device].stop_client()
            return False
        if 'dps' not in data:
            self.devices[device].stop_client()
            return False
        if current_pos in data['dps']:
            if data['dps'][current_pos] > percentage:
                next_action = 'open'
            else:
                next_action = 'close'
        else:
            next_action = 'n/a'
        payload = {
            position: percentage
        }
        self.devices[device].set_status(payload)

        log.info(f'[CURTAINS] {device} Curtains Set to {percentage}% ({next_action})')
        self.devices[device].stop_client()
        return True

    def get_th_data(self, device):
        return self.db.get_sensor(device)

    def get_device_name(self, devid):
        for device in self.gather.keys():
            if device == devid:
                return device
            for prop in self.gather[device]:
                if devid == self.gather[device][prop]:
                    return device
                if devid.split('.')[-1] == self.gather[device][prop]:
                    return device
        return False


def check_payload(req, payload):
    if req is None:
        return False
    for x in req:
        if x not in payload:
            log.error(f'Missing {x} in payload')
            return False
    return True

old_data_sensor = {}

class GetSensor(Resource):
    def get(self):
        device = request.args.get('device', False)
        name = t.get_device_name(device)
        msg = {}
        if not name:
            msg['error'] = f'Sensor {name} vs {device} not found'
            return msg, 404
        data = t.get_th_data(name)
        return data, 200

    def post(self):
        global old_data_sensor
        try:
            payload = request.get_json()
            log.debug(f'Payload >> {payload}')
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}, 503
        required = ['device']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        device = payload['device']
        name = t.get_device_name(device)
        if not name:
            msg['error'] = f'Device {device} >> {name} not found'
            log.error(f'Device {name} >> not found vs {device}')
            return msg, 404
        data = t.get_th_data(name)
        return data, 200

class SetLight(Resource):
    def post(self):
        try:
            payload = request.get_json()
            log.debug(f'Payload >> {payload}')
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}, 503
        required = ['device', 'param', 'value']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        device = payload['device']
        name = t.get_device_name(device)
        if not name:
            msg['error'] = f'Device {device} >> {name} not found'
            return msg, 404
        msg['status'] = t.set_light(device, payload['param'], payload['value'])
        return msg, 200

class SetLightPreset(Resource):
    def post(self):
        try:
            payload = request.get_json()
            log.debug(f'Payload >> {payload}')
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}, 503
        required = ['device', 'preset']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        device = payload['device']
        name = t.get_device_name(device)
        if not name:
            msg['error'] = f'Device {device} >> {name} not found'
            return msg, 404
        msg['status'] = t.set_light_preset(device, payload['preset'])
        return msg, 200

class SetLightCombined(Resource):
    def post(self):
        try:
            payload = request.get_json()
            log.debug(f'Payload >> {payload}')
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}, 503
        required = ['device', 'params', 'values']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        device = payload['device']
        name = t.get_device_name(device)
        if not name:
            msg['error'] = f'Device {device} >> {name} not found'
            return msg, 404
        msg['status'] = t.set_light_combined(device, payload['params'], payload['values'])
        return msg, 200

class SetCurtain(Resource):
    def get(self):
        msg = {}
        device = request.args.get('device', False)
        if not device:
            msg['error'] = 'MISSING ENTITY ID'
            return msg, 404
        name = t.get_device_name(device)
        payload = t.get_curtains(name)
        if not payload:
            # There are scenarios where Tuya scrapes the device..
            # then you will get a socket error, race condition effect.
            # this prevents hassio to store a Null
            if name in old_data_sensor:
                log.info(f'[GET-CURTAIN] Returning Cached Result for {name}')
                return old_data_sensor[name], 200
            msg['error'] = f'{name} device not found vs {device} input'
            return msg, 404
        old_data_sensor[name] = payload
        return payload, 200

    def post(self):
        try:
            payload = request.get_json()
            log.debug(f'Payload >> {payload}')
        except Exception as error:
            log.error(f'Exception {error} on getDeviceDetails Endpoint')
            return {'error': 'Malformed Payload'}, 503
        required = ['device', 'position']
        msg = {}
        if not check_payload(required, payload):
            msg['error'] = 'Incomplete Payload'
            return msg, 503
        device = payload['device']
        name = t.get_device_name(device)
        if not name:
            msg['error'] = f'Device {device} >> {name} not found'
            return msg, 404
        if payload['position'] == 'open':
            t.open_curtains(name)
        elif payload['position'] == 'close':
            t.close_curtains(name)
        elif payload['position'] == 'half':
            t.half_curtains(name)
        elif payload['position'] == 'sunny':
            t.sunny_curtains(name)
        else:
            t.set_curtains(name, int(payload['position']))
        log.info(f"[SET-CURTAIN-WWW] >> Curtain {name} set to {payload['position']}")
        return 'OK', 200

class TestWeb(Resource):
    def post(self):
        return 'OK', 200

    def get(self):
        return 'OK', 200

# Some experiment.. when u enable debug on Flask.. 
# it will trigger twice this handler .. weird.
sensor_handler = SensorScheduler()
def get_th_sensors():
    sensor_handler.get_th_sensor()

t = TuyaData()
sensor_handler.get_th_sensor()

sched.add_job(get_th_sensors, 'interval', seconds=60, max_instances=1, replace_existing=True)

if __name__ == '__main__':
    api.add_resource(SetCurtain, '/curtain')
    api.add_resource(GetSensor, '/sensor')
    api.add_resource(SetLight, '/light')
    api.add_resource(SetLightPreset, '/light_preset')
    api.add_resource(SetLightCombined, '/light_combined')
    api.add_resource(TestWeb, '/test')
    sched.start()
    app.run(threaded=False, debug=False, port=cfg['web_port'], host='0.0.0.0')
