#!/usr/bin/env bash
# Публикация репозитория на GitHub (закрытый) и доступ на чтение стороне заказчика.
# Один раз владелец: gh auth login  (браузер, учётка GitHub). Потом: tools/github_publish.sh [имя-репо]
set -euo pipefail
GH="${GH:-$HOME/.local/bin/gh}"
NAME="${1:-modus-feedback}"
READER="${READER:-}"
cd "$(dirname "$0")/.."
"$GH" auth status >/dev/null 2>&1 || { echo "Сначала: $GH auth login"; exit 1; }
# проверка секретов по всей истории перед первым пушем
if git log -p --all | grep -q -E "sk-(proj-)?[A-Za-z0-9_-]{20,}"; then echo "В истории есть ключ OpenAI — НЕ пушим"; exit 1; fi
git ls-files | grep -q -E "^\.env$|docs/source/" && { echo "В индексе .env или docs/source — НЕ пушим"; exit 1; }
OWNER=$("$GH" api user -q .login)
if ! "$GH" repo view "$OWNER/$NAME" >/dev/null 2>&1; then
  "$GH" repo create "$NAME" --private --source . --remote origin --push \
    --description "Обратная связь и предложения сотрудников + режим совещания — хакатон Pavlodar Hub × ГК «Модус Трейд»"
else
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "git@github.com:$OWNER/$NAME.git"
  git push -u origin main
fi
"$GH" api -X PUT "repos/$OWNER/$NAME/collaborators/$READER" -f permission=pull >/dev/null && echo "Приглашение на чтение отправлено: $READER"
echo "https://github.com/$OWNER/$NAME"
