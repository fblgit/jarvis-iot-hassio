import asyncio
import datetime
import json
import logging
import os
import time
import uuid
from pythonping import ping
import pymysql
import requests

db = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'user': os.environ.get('DB_USER', 'jarvis'),
    'pass': os.environ.get('DB_PASS', 'jarvispass'),
    'db': os.environ.get('DB_NAME', 'jarvis'),
    'commit': bool(os.environ.get('DB_COMMIT', True))
}
# WIP
mq = {
    'host': 'mq.local',
    'port': 1883
}
cfg = {
    'app': os.environ.get('CFG_APP', 'PHONE-GUARDIAN'),
    'jarvis_url': os.environ.get('JARVIS_URL', 'http://your_jarvis_url'),
    'jarvis_secret': os.environ.get('JARVIS_SECRET', 'jarvis_api_key')
}

log = logging.getLogger(str(cfg['app']))
log.addHandler(logging.StreamHandler())
log.setLevel(logging.INFO)

def gen_token():
    return str(uuid.uuid4())

def push_token(valid=600):
    token = gen_token()
    if 'jarvis_url' in cfg:
        payload = {
            'token': token,
            'secret': cfg['jarvis_secret'],
            'expire': valid
        }
        log.info(f'+[TOKEN] Generated {token} with {valid} seconds expire')
        try:
            requests.post(f"{cfg['jarvis_url']}/tokens", headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        except Exception as error:
            log.error(f"![TOKEN] Exception on push_token with jarvis:\n{error}")
    return token


def push_mqtt(payload, topic):
    if 'handler' not in mq:
        log.info(f"[MQTT] Connecting.. {topic}")
        mq['handler'] = True
    log.info(f'[MQTT] Push to {topic} >> {payload}')
    payload['unix_time'] = time.time()
    # js = json.dumps(payload)
    # push to MQ


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
            log.info(f'DB Handler Died.. reconnecting {error}')
        return self.cur

    def cursor(self):
        return self.cur

    def last_active(self, ip):
        self.check()
        self.cur.execute('SELECT last_alive FROM phone_guardian WHERE phone_ip=%s', (ip))
        rows = self.cur.fetchall()
        if rows is None:
            return 0
        return rows[0]['last_alive']

    def update_active(self, ip):
        self.check()
        self.cur.execute('UPDATE phone_guardian SET last_alive=CURRENT_TIMESTAMP WHERE phone_ip=%s', (ip))
        return True

    def get_phones(self):
        self.check()
        self.cur.execute('SELECT * FROM phone_guardian')
        rows = self.cur.fetchall()
        results = {}
        for row in rows:
            results[row['phone_ip']] = {}
            results[row['phone_ip']]['last_alive'] = row['last_alive']
            results[row['phone_ip']]['ifttt_url'] = row['ifttt_url']
            results[row['phone_ip']]['mqtt_topic'] = row['mqtt_topic']
        return results


async def isAlive(ip, count=2, timeout=3):
    results = []
    try:
        result = ping(ip, count=count, timeout=timeout)
        for x in result:
            results.append(x.success)
    except Exception as error:
        log.error(f"[isAlive] Exception with IP {ip}:\n{error}")
        return False
    if True not in results:
        return False
    return True


class Guardian():
    def __init__(self):
        self.cur = s.check()
        self.load_data()
        self.alert_period = 120
        self.check_period = 15
        self.alive = []
        self.alerts = []
        self.out_key = []

    def load_data(self):
        self.cur = s.check()
        self.phones = s.get_phones()

    def dead_exceed(self, phone, period):
        now = datetime.datetime.now()
        last_active = self.phones[phone]['last_alive']
        delta = datetime.timedelta(seconds=period)
        if last_active + delta < now:
            return True
        return False

    def gone_period(self, phone, out=False):
        now = datetime.datetime.now()
        period = now - self.phones[phone]['last_alive']
        if out:
            return period
        return str(period)

    def compose_alert(self, phone, alive):
        if phone in self.alerts and not alive:
            log.debug(f'=[ALERTS] {phone} stills not present')
            gone_period = self.gone_period(phone, out=True)
            if phone not in self.out_key and gone_period > datetime.timedelta(minutes=5):
                self.out_key.append(phone)
                token = push_token(valid=21600)
                requests.post(self.phones[phone]['ifttt_url'], headers={'Content-Type': 'application/json'}, data=json.dumps({'value1': token, 'value2': 'wb', 'value3': phone}))
                log.info(f'![OUT-KEY] Generated for {phone} with a 21600s Duration')
                return True
            # here can add actions on non presence
            return False
        elif phone in self.alerts and alive:
            self.alerts.remove(phone)
            if phone in self.out_key:
                log.info(f'-[OUT-KEY] Removed WB Tag for {phone}')
                self.out_key.remove(phone)
            if self.dead_exceed(phone, self.alert_period):
                log.info(f'-[ALERTS] dead_exceed {self.alert_period} for {phone} device')
                token = push_token()
                if 'http' in self.phones[phone]['ifttt_url']:
                    log.info(f'![ALERTS] ifttt trigger for {phone}')
                    requests.post(self.phones[phone]['ifttt_url'], headers={'Content-Type': 'application/json'}, data=json.dumps({'value1': token, 'value2': 'open', 'value3': phone}))
                elif self.phones[phone]['mqtt_topic'] != '':
                    log.info(f'![ALERTS] mqtt trigger for {phone}')
                return True
            else:
                log.info(f'-[ALERTS] dead_exceed NOT passed for {phone} (SKIP-NOTIFICATION)')
                if phone in self.out_key:
                    self.out_key.remove(phone)
                return False
        elif phone not in self.alerts and not alive:
            log.info(f'+[ALERTS] added {phone} to alerted devices list')
            self.alerts.append(phone)
            return False
        return False

    async def check_alive(self):
        while True:
            for phone in self.phones.keys():
                log.debug(f'?[ALIVE] Determine {phone} status')
                is_alive = await isAlive(phone)
                if is_alive:
                    if phone not in self.alive:
                        self.compose_alert(phone, alive=True)
                        self.alive.append(phone)
                        log.info(f'+[ALIVE] added {phone} last_active time')
                    else:
                        log.debug(f'=[ALIVE] updated {phone} last_active time')
                    s.update_active(phone)
                    self.phones[phone]['last_alive'] = s.last_active(phone)
                else:
                    if phone in self.alive:
                        log.info(f'-[ALIVE] removed {phone} from alive list')
                        self.alive.remove(phone)
                    else:
                        log.debug(f'=[ALIVE] phone {phone} stills not present ({self.gone_period(phone)})')
                    self.compose_alert(phone, alive=False)
            log.debug(f'i[ALIVE] Next Cycle in {self.check_period} seconds')
            await asyncio.sleep(self.check_period)


s = DB()
sql = s.cursor()
loop = asyncio.get_event_loop()
g = Guardian()
loop.create_task(g.check_alive())
loop.run_forever()
