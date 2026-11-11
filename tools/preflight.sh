#!/usr/bin/env bash
# Проверка «за час до выхода»: сервер, туннель снаружи, ключ OpenAI, STT на GPU, база в демо-состоянии, место, батарея.
# tools/preflight.sh            — полная проверка (с живым ключом)
# tools/preflight.sh --no-key   — запасной режим: сценарий проходит на заскриптованных разборах без ключа (pytest tests/test_demo.py)
set -uo pipefail
cd "$(dirname "$0")/.."
URL="${MF_LOCAL_URL:-http://127.0.0.1:8070}"
PUB="${MF_PUBLIC_URL:-$(grep -E '^MF_PUBLIC_URL=' .env 2>/dev/null | cut -d= -f2)}"
ok() { printf "  ОК        %s\n" "$1"; }
bad() { printf "  ПРОБЛЕМА  %s\n            → %s\n" "$1" "$2"; FAIL=1; }
FAIL=0
if [ "${1:-}" = "--no-key" ]; then
  echo "Запасной режим без ключа: прогон сценария демо на заскриптованных разборах"
  if OPENAI_API_KEY= MF_STT=off python3 -m pytest -q tests/test_demo.py 2>&1 | tail -2; then ok "сценарий проходит без ключа (tests/test_demo.py)"; else bad "сценарий без ключа" "смотри вывод pytest выше"; fi
  exit $FAIL
fi
echo "Проверка перед выступлением — $(date '+%d.%m %H:%M')"
if curl -s --max-time 4 "$URL/api/health" | grep -q '"ok":true'; then ok "сервер отвечает локально ($URL)"; else bad "сервер не отвечает на $URL" "preview_start modus-dev или: python3 -m uvicorn mf.main:app --port 8070"; fi
if [ -n "$PUB" ]; then
  code=$(curl -s --max-time 12 -o /dev/null -w "%{http_code}" "$PUB/api/health"); if [ "$code" = "200" ]; then ok "туннель отвечает снаружи ($PUB)"; else bad "туннель: $PUB → HTTP $code" "systemctl --user restart cloudflared-modus; проверить интернет / раздачу с телефона"; fi
else bad "MF_PUBLIC_URL не задан в .env" "MF_PUBLIC_URL=https://modus.cq-systems.kz"; fi
CJ=$(mktemp); curl -s -c "$CJ" -X POST -H 'Content-Type: application/json' -d '{"user_id":15}' "$URL/api/auth/login-as" >/dev/null 2>&1
if curl -s --max-time 120 -b "$CJ" "$URL/api/admin/preflight" > /tmp/mf_preflight.json 2>/dev/null; then
  python3 - <<'PY' || FAIL=1
import json
d = json.load(open("/tmp/mf_preflight.json"))
fail = 0
for c in d["checks"]:
    if c["ok"]: print(f"  ОК        {c['name']}: {c['detail']}")
    else:
        fail = 1
        hint = {"ключ OpenAI": "положить OPENAI_API_KEY в .env и перезапустить сервер; без ключа демо идёт в запасном режиме",
                "STT на GPU": "проверить nvidia-smi и pip install --user -r requirements-stt.txt; запасной — MF_STT=openai"}.get(c["name"], "tools/demo_reset.sh")
        print(f"  ПРОБЛЕМА  {c['name']}: {c['detail']}\n            → {hint}")
raise SystemExit(fail)
PY
else bad "сервер не ответил на /api/admin/preflight" "смотри preview_logs"; fi
rm -f "$CJ"
free_gb=$(df -BG --output=avail "$(pwd)" | tail -1 | tr -dc '0-9'); if [ "${free_gb:-0}" -ge 5 ]; then ok "свободно на диске: ${free_gb} ГБ"; else bad "мало места: ${free_gb} ГБ" "освободить место"; fi
if [ -d /sys/class/power_supply/BAT0 ]; then cap=$(cat /sys/class/power_supply/BAT0/capacity 2>/dev/null); st=$(cat /sys/class/power_supply/BAT0/status 2>/dev/null); if [ "${cap:-0}" -ge 40 ] || [ "$st" = "Charging" ] || [ "$st" = "Full" ]; then ok "батарея ${cap}% ($st)"; else bad "батарея ${cap}% ($st)" "подключить зарядку"; fi; fi
if [ $FAIL = 0 ]; then echo "ИТОГ: всё готово"; else echo "ИТОГ: есть проблемы — см. выше"; fi
exit $FAIL
