#!/bin/bash
GIT_URL=${GIT_URL:-https://github.com/fblgit/jarvis.git}

MODE=${MODE:-jarvis}
if [[ ! -f "/scraper/.git" ]]; then
	git config --global http.sslverify false
	git clone $GIT_URL /app/jarvis
fi
cd /app/jarvis
if [[ "$MODE" == "jarvis" ]]; then
	python3 /app/jarvis/ws.py
fi
if [[ "$MODE" == "tuya" ]]; then
	python3 /app/jarvis/ws-tuya.py
fi
if [[ "$MODE" == "bcast" ]]; then
	python3 /app/jarvis/cast_server.py
fi
if [[ "$MODE" == "sync" ]]; then
	python3 /app/jarvis/sync_serve.py
fi
