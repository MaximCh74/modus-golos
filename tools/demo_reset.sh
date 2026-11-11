#!/usr/bin/env bash
# Вернуть базу в демо-состояние за секунды, без вызовов ИИ. Через сервер, если он запущен (сессии сбросятся — войти заново),
# иначе напрямую по файлу. Даты сдвигаются так, что «сегодня» снапшота = сегодня.
set -euo pipefail
cd "$(dirname "$0")/.."
URL="${MF_LOCAL_URL:-http://127.0.0.1:8070}"
if curl -s --max-time 3 "$URL/api/health" >/dev/null 2>&1; then
  CJ=$(mktemp)
  curl -s -c "$CJ" -X POST -H 'Content-Type: application/json' -d '{"user_id":15}' "$URL/api/auth/login-as" >/dev/null
  curl -s -b "$CJ" -X POST "$URL/api/admin/demo-reset"; echo
  rm -f "$CJ"
else
  python3 -c "from mf import demo; import json; print(json.dumps(demo.reset(), ensure_ascii=False))"
fi
