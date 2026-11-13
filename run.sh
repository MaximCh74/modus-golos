#!/usr/bin/env bash
# «Модус Голос» без Docker — Linux и macOS. Создаёт окружение .venv, ставит зависимости, поднимает демо-базу и сервер.
# Требуется Python 3.11 или новее. Запуск из папки проекта:  ./run.sh   (или  bash run.sh)
# Порт — MF_PORT (по умолчанию 8090). Ключи и настройки — в .env по образцу .env.example (без ключа — демо-режим).
set -euo pipefail
cd "$(dirname "$0")"
PORT="${MF_PORT:-8090}"

PY=""
for c in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Нужен Python 3.11 или новее (python.org/downloads или пакетный менеджер системы). Либо запуск через Docker: docker compose up --build" >&2
  exit 1
fi
echo "Python: $($PY --version)"

if [ ! -x .venv/bin/python ]; then
  echo "Создаём окружение .venv…"
  "$PY" -m venv .venv
fi
echo "Ставим зависимости (первый раз — пара минут)…"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

export MF_DEMO_SNAPSHOT=1          # пустая база при первом запуске — демо-снапшот (даты сдвигаются на «сегодня»)
export MF_STT="${MF_STT:-openai}"  # расшифровка голоса без видеокарты — через OpenAI (нужен ключ в .env); локальная модель — requirements-stt.txt
export MF_STT_WARMUP=0
echo
echo "Готово. Откройте http://localhost:$PORT  — демо-вход без паролей: /login → «Войти как…». Остановить — Ctrl+C."
echo
exec .venv/bin/python -m uvicorn mf.main:app --host 127.0.0.1 --port "$PORT"
