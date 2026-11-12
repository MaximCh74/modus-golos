#!/usr/bin/env bash
# Сборка подписанных APK для Android (TWA через Bubblewrap): «Модус Голос» (~/MODUS_ANDROID/app) и «Директор» (~/MODUS_ANDROID/boss).
# Пароли ключа подписи спрашиваются при запуске без отображения, живут только в переменных окружения этого процесса и нигде не
# сохраняются (ни в файлы, ни в журналы); перед сборкой пароли проверяются keytool, а в выводе Bubblewrap они маскируются (при ошибке
# он печатает команду apksigner с паролями). Готовые APK копируются в demo/android/ (modus-golos.apk, modus-golos-director.apk).
#   tools/build_apk.sh            — собрать оба приложения
#   tools/build_apk.sh app|boss   — только одно
# Пути можно переопределить переменными MODUS_ANDROID, BUBBLEWRAP, JAVA_HOME, ANDROID_HOME. Подробности — docs/ANDROID.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ANDROID_DIR="${MODUS_ANDROID:-$HOME/MODUS_ANDROID}"
BW="${BUBBLEWRAP:-$HOME/.local/bubblewrap/node_modules/.bin/bubblewrap}"
export JAVA_HOME="${JAVA_HOME:-$HOME/development/jdk-17}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
OUT="$ROOT/demo/android"

case "${1:-all}" in
  app)  TARGETS="app" ;;
  boss) TARGETS="boss" ;;
  all)  TARGETS="app boss" ;;
  *) echo "использование: tools/build_apk.sh [app|boss]" >&2; exit 2 ;;
esac

fail() { echo "ОШИБКА: $1" >&2; exit 1; }
[ -x "$BW" ] || fail "не найден Bubblewrap: $BW (см. docs/ANDROID.md)"
[ -x "$JAVA_HOME/bin/java" ] || fail "не найден JDK 17: $JAVA_HOME"
[ -d "$ANDROID_HOME/build-tools" ] || fail "не найден Android SDK: $ANDROID_HOME"
for t in $TARGETS; do
  [ -f "$ANDROID_DIR/$t/twa-manifest.json" ] || fail "нет проекта $ANDROID_DIR/$t/twa-manifest.json"
done
[ -f "$ANDROID_DIR/modus-golos.keystore" ] || fail "нет ключа подписи $ANDROID_DIR/modus-golos.keystore"
[ -t 0 ] || fail "пароль спрашивается с клавиатуры — запускать в терминале"

echo "Сборка APK: $TARGETS (проекты в $ANDROID_DIR, результат в demo/android/)"
read -rs -p "Пароль хранилища ключей (ввод не отображается): " KS_PASS; echo
[ -n "$KS_PASS" ] || fail "пустой пароль"
read -rs -p "Пароль ключа modusgolos (Enter — тот же, что у хранилища): " KEY_PASS; echo
[ -n "$KEY_PASS" ] || KEY_PASS="$KS_PASS"
export BUBBLEWRAP_KEYSTORE_PASSWORD="$KS_PASS" BUBBLEWRAP_KEY_PASSWORD="$KEY_PASS"
unset KS_PASS KEY_PASS
# проверка паролей до сборки (keytool читает их из переменных окружения — в командной строке и выводе их нет)
"$JAVA_HOME/bin/keytool" -list -keystore "$ANDROID_DIR/modus-golos.keystore" -alias modusgolos -storepass:env BUBBLEWRAP_KEYSTORE_PASSWORD >/dev/null 2>&1 \
  || fail "пароль хранилища не подходит к $ANDROID_DIR/modus-golos.keystore (это пароль из отчёта сессии 12.11, не ваш обычный)"
"$JAVA_HOME/bin/keytool" -certreq -keystore "$ANDROID_DIR/modus-golos.keystore" -alias modusgolos -storepass:env BUBBLEWRAP_KEYSTORE_PASSWORD \
  -keypass:env BUBBLEWRAP_KEY_PASSWORD -file /dev/null >/dev/null 2>&1 || fail "пароль ключа modusgolos не подходит"   # certreq трогает закрытый ключ, хранилище не меняет
echo "Пароли подходят."
# вывод Bubblewrap фильтруем: при ошибке он печатает команду apksigner вместе с паролями
mask() { sed -E 's/(pass:")[^"]*(")/\1***\2/g; s/(pass:)[^ "]+/\1***/g'; }

mkdir -p "$OUT"
for t in $TARGETS; do
  case "$t" in app) name="modus-golos.apk" ;; boss) name="modus-golos-director.apk" ;; esac
  echo
  echo "== $t → demo/android/$name"
  ( cd "$ANDROID_DIR/$t" && "$BW" build --skipPwaValidation 2>&1 | mask )
  [ -f "$ANDROID_DIR/$t/app-release-signed.apk" ] || fail "сборка $t не дала app-release-signed.apk"
  cp "$ANDROID_DIR/$t/app-release-signed.apk" "$OUT/$name"
  ver=$(grep -E '"appVersion(Name|Code)"' "$ANDROID_DIR/$t/twa-manifest.json" | tr -d ' ",' | paste -sd' ' -)
  printf "   готово: %s (%s КБ; %s)\n" "$name" "$(( $(stat -c %s "$OUT/$name") / 1024 ))" "$ver"
done
unset BUBBLEWRAP_KEYSTORE_PASSWORD BUBBLEWRAP_KEY_PASSWORD
echo
echo "Готово. Проверка подписи (отпечаток должен совпадать с web/.well-known/assetlinks.json):"
for t in $TARGETS; do
  case "$t" in app) name="modus-golos.apk" ;; boss) name="modus-golos-director.apk" ;; esac
  "$JAVA_HOME/bin/keytool" -printcert -jarfile "$OUT/$name" 2>/dev/null | grep -E 'SHA256:' | sed "s|^|   $name |" || true
done
echo "Дальше: передать APK на телефон (docs/ANDROID.md) и закоммитить demo/android/*.apk."
