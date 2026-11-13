#!/usr/bin/env bash
# Архив для просмотра без GitHub: zip с паролем (AES-256), внутри — git bundle со всей историей (modus-golos.bundle), распакованный код
# последнего коммита, LICENSE и README_ОТКРЫТЬ.txt. Только то, что лежит в git: без .env, ключей, рабочей базы (var/), HANDOFF.
# Пароль спрашивается при запуске (дважды) и передаётся сборщику через канал — в файлах, аргументах и истории оболочки его нет.
# Запуск:  bash tools/make_review_archive.sh [папка для архива]   (по умолчанию — «для КЛОДА БРАТИКА» на рабочем столе или dist/)
set -euo pipefail
cd "$(dirname "$0")/.."
OUT_DIR="${1:-$HOME/Desktop/для КЛОДА БРАТИКА}"
[ -d "$OUT_DIR" ] || OUT_DIR="$PWD/dist"
mkdir -p "$OUT_DIR"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Внимание: есть незакоммиченные изменения — в архив попадёт последний коммит $(git rev-parse --short HEAD)."
fi
REV=$(git rev-parse --short HEAD)
NAME="modus-golos_$(date +%Y-%m-%d)_${REV}"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STAGE="$WORK/$NAME"
mkdir -p "$STAGE"

echo "Собираем: git bundle со всей историей и код коммита $REV…"
git bundle create "$STAGE/modus-golos.bundle" --all 2>/dev/null
git bundle verify "$STAGE/modus-golos.bundle" >/dev/null 2>&1
git archive --format=tar --prefix=modus-golos/ HEAD | tar -x -C "$STAGE"
cp LICENSE "$STAGE/LICENSE"
cat > "$STAGE/README_ОТКРЫТЬ.txt" <<EOF
«Модус Голос» — код и вся история разработки (коммит $REV, $(date +%d.%m.%Y)).

Как открыть:
  1) Просто смотреть код — папка modus-golos/ (начните с modus-golos/README.md).
  2) Получить репозиторий со всей историей коммитов:
       git clone modus-golos.bundle modus-golos-git
       cd modus-golos-git && git log --oneline
  Запуск — modus-golos/README.md, раздел «Запуск одной командой»: docker compose up --build → http://localhost:8090
  Живое демо: https://modus.cq-systems.kz

Архив зашифрован AES-256: открывается 7-Zip (Windows), Keka или The Unarchiver (Mac), unar / 7z (Linux).
Встроенный распаковщик Windows и «Архиватор» Mac AES-архивы не открывают.

© 2026 ТОО «Gyber QALQAN Systems». Все права защищены. Код предоставлен исключительно для ознакомления в рамках хакатона Pavlodar Hub × ГК «Модус Трейд». Копирование, использование, изменение и распространение — только с письменного разрешения правообладателя.
EOF

# страховка: ни секретов, ни рабочей базы
if find "$STAGE" \( -name '.env' -o -name '*.keystore' -o -name '*.jks' -o -name 'mf.db' -o -path '*/var/*' -o -name 'HANDOFF*.md' \) | grep -q .; then
  echo "Стоп: в архив попали секреты или рабочая база" >&2; exit 1
fi
if grep -rqsE 'sk-(proj-)?[A-Za-z0-9_-]{20,}' "$STAGE/modus-golos"; then echo "Стоп: в коде похоже на ключ OpenAI" >&2; exit 1; fi

if [ -t 0 ]; then
  read -rsp "Пароль на архив (от 8 символов): " PW; echo
  read -rsp "Повторите пароль: " PW2; echo
  [ "$PW" = "$PW2" ] || { echo "Пароли не совпали" >&2; exit 1; }
else
  IFS= read -r PW || true   # для проверок без терминала: пароль одной строкой на входе
fi
OUT="$OUT_DIR/$NAME.zip"
printf '%s' "$PW" | python3 tools/aes_zip.py "$OUT" "$STAGE"
unset PW PW2
echo "Готово: $OUT"
echo "Внутри: $NAME/ (modus-golos.bundle, modus-golos/, LICENSE, README_ОТКРЫТЬ.txt). Пароль передайте отдельно от архива."
