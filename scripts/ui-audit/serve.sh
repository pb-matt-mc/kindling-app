#!/usr/bin/env bash
# Isolated mock-data Kindling for UI audits. Never touches port 8010 or ~/kindling/data.
#   serve.sh start   build a fresh seeded instance on 127.0.0.1:8099
#   serve.sh stop
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
export KINDLING_DATA_DIR="${KINDLING_UI_DIR:-/tmp/kindling-ui}"
export KINDLING_SOURCE=mock          # fake listings, nothing spent
export ANTHROPIC_API_KEY=""          # forces the keyword brain; an empty env var beats .env
export SCRAPECREATORS_API_KEY="" APIFY_TOKEN="" KINDLING_OBSIDIAN_DIR=""
PORT="${KINDLING_UI_PORT:-8099}"
PIDFILE="$KINDLING_DATA_DIR.pid"

stop() { [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true; rm -f "$PIDFILE"; }

case "${1:-start}" in
  stop) stop ;;
  start)
    stop
    case "$KINDLING_DATA_DIR" in /tmp/*) ;; *) echo "refusing: data dir must be under /tmp" >&2; exit 1;; esac
    rm -rf "$KINDLING_DATA_DIR"; mkdir -p "$KINDLING_DATA_DIR"
    cd "$ROOT"
    .venv/bin/python "$HERE/seed.py" init
    .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning >"$KINDLING_DATA_DIR/uvicorn.out" 2>&1 &
    echo $! > "$PIDFILE"
    for _ in $(seq 1 40); do curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 0.5; done
    .venv/bin/python "$HERE/seed.py" populate "http://127.0.0.1:$PORT"
    echo "ready: http://127.0.0.1:$PORT  (tokens in $KINDLING_DATA_DIR/tokens.json)"
    ;;
esac
