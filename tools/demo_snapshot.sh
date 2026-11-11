#!/usr/bin/env bash
# Снять снапшот демо-состояния базы в demo/fixtures/mf-demo.db (безопасно при работающем сервере).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c "from mf import demo; import json; print(json.dumps(demo.snapshot(), ensure_ascii=False))"
