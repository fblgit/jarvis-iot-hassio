#!/usr/bin/env python3

import os
import logging
import requests
from flask import Flask, request
from flask_restful import  Api

jarvis_url = os.environ.get('JARVIS_URL', 'https://yourjarvis.url')


cfg = {
    'syslog_ip': os.environ.get('CFG_SYSLOG', 'YOUR-SYSLOG-IP'),
    'app': os.environ.get('CFG_APP', 'JARVIS-PROXY'),
    'web_port': int(os.environ.get('WEB_PORT', 8800))
}


log = logging.getLogger(str(cfg['app']))
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)

app = Flask(__name__)
api = Api(app)


@app.route('/', defaults={'path': ''}, methods=['GET'])
@app.route('/<path:path>', methods=['GET'])
def def_get(path):
    headers = {
        'Host': 'jarvis.fblnet.net'
    }
    for x in request.headers:
        if x[0] == 'Host':
            continue
        headers[x[0]] = x[1]
    args = {}
    for x in request.args:
        args[x] = request.args[x]
    log.debug(f'[GET] to {jarvis_url}{path} >> H: {headers} >> A: {args}')
    if path:
        r = requests.get(f'{jarvis_url}/{path}', headers=headers, params=args)
        return r.content, r.status_code, {'Content-Type': r.headers['Content-Type'], 'Connection': 'close'}
    return 'Not-Proxied', 404


@app.route('/', defaults={'path': ''}, methods=['POST'])
@app.route('/<path:path>', methods=['POST'])
def def_post(path):
    headers = {
        'Host': 'jarvis.fblnet.net'
    }
    for x in request.headers:
        if x[0] == 'Host':
            continue
        headers[x[0]] = x[1]
    log.debug(f'[POST] to {jarvis_url}{path} >> H: {headers} >> D: {request.data}')
    if path:
        r = requests.post(f'{jarvis_url}/{path}', headers=headers, data=request.data)
        return r.content, r.status_code, {'Content-Type': r.headers['Content-Type'], 'Connection': 'close'}
    return 'Not-Proxied', 404


@app.route('/', defaults={'path': ''}, methods=['PUT'])
@app.route('/<path:path>', methods=['PUT'])
def def_put(path):
    headers = {
        'Host': 'jarvis.fblnet.net'
    }
    for x in request.headers:
        if x[0] == 'Host':
            continue
        headers[x[0]] = x[1]
    log.debug(f'[PUT] to {jarvis_url}{path} >> H: {headers} >> D: {request.data}')
    if path:
        r = requests.put(f'{jarvis_url}/{path}', headers=headers, data=request.data)
        return r.content, r.status_code, {'Content-Type': r.headers['Content-Type'], 'Connection': 'close'}
    return 'Not-Proxied', 404


if __name__ == '__main__':
    app.run(debug=True, port=cfg['web_port'], host='0.0.0.0')
