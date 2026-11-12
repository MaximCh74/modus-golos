#!/usr/bin/env bash
# Сборка подписанных APK для Android (TWA через Bubblewrap): «Модус Голос» (~/MODUS_ANDROID/app) и «Директор» (~/MODUS_ANDROID/boss).
#   tools/build_apk.sh                 — собрать оба приложения (спросит пароль ключа)
#   tools/build_apk.sh app|boss        — только одно
#   tools/build_apk.sh --new-key [app|boss] — НОВЫЙ ключ подписи: спросит новый пароль дважды, старый ключ отложит рядом
#                                        (modus-golos.keystore.old-<дата>), заменит отпечаток в web/.well-known/assetlinks.json
#                                        на отпечаток нового ключа и соберёт APK. На телефоне старое приложение удалить и
#                                        поставить новое: APK с другим ключом поверх не встаёт.
# Пароли спрашиваются без отображения, живут только в переменных окружения этого процесса и нигде не сохраняются; перед сборкой
# проверяются keytool, в выводе Bubblewrap маскируются (при ошибке он печатает команду apksigner с паролями). Если пароли уже заданы в
# BUBBLEWRAP_KEYSTORE_PASSWORD / BUBBLEWRAP_KEY_PASSWORD — не спрашивает. Готовые APK — в demo/android/ (modus-golos.apk,
# modus-golos-director.apk). Пути переопределяются переменными MODUS_ANDROID, KEYSTORE, ASSETLINKS, APK_OUT, BUBBLEWRAP, JAVA_HOME,
# ANDROID_HOME. Подробности — docs/ANDROID.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ANDROID_DIR="${MODUS_ANDROID:-$HOME/MODUS_ANDROID}"
KEYSTORE="${KEYSTORE:-$ANDROID_DIR/modus-golos.keystore}"
ASSETLINKS="${ASSETLINKS:-$ROOT/web/.well-known/assetlinks.json}"
OUT="${APK_OUT:-$ROOT/demo/android}"
BW="${BUBBLEWRAP:-$HOME/.local/bubblewrap/node_modules/.bin/bubblewrap}"
export JAVA_HOME="${JAVA_HOME:-$HOME/development/jdk-17}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
KT="$JAVA_HOME/bin/keytool"
ALIAS=modusgolos

NEW_KEY=0
if [ "${1:-}" = "--new-key" ]; then NEW_KEY=1; shift; fi
case "${1:-all}" in
  app)  TARGETS="app" ;;
  boss) TARGETS="boss" ;;
  all)  TARGETS="app boss" ;;
  *) echo "использование: tools/build_apk.sh [--new-key] [app|boss]" >&2; exit 2 ;;
esac

fail() { echo "ОШИБКА: $1" >&2; exit 1; }
mask() { sed -E 's/(pass:")[^"]*(")/\1***\2/g; s/(pass:)[^ "]+/\1***/g'; }
[ -x "$BW" ] || fail "не найден Bubblewrap: $BW (см. docs/ANDROID.md)"
[ -x "$KT" ] || fail "не найден JDK 17: $JAVA_HOME"
[ -d "$ANDROID_HOME/build-tools" ] || fail "не найден Android SDK: $ANDROID_HOME"
for t in $TARGETS; do
  [ -f "$ANDROID_DIR/$t/twa-manifest.json" ] || fail "нет проекта $ANDROID_DIR/$t/twa-manifest.json"
done
[ "$NEW_KEY" = 1 ] || [ -f "$KEYSTORE" ] || fail "нет ключа подписи $KEYSTORE (новый ключ: tools/build_apk.sh --new-key)"

if [ -z "${BUBBLEWRAP_KEYSTORE_PASSWORD:-}" ]; then
  [ -t 0 ] || fail "пароль спрашивается с клавиатуры — запускать в терминале"
  if [ "$NEW_KEY" = 1 ]; then
    echo "Новый ключ подписи для APK. Придумайте пароль (не короче 6 символов) и сохраните его в менеджере паролей."
    read -rs -p "Новый пароль ключа (ввод не отображается): " P1; echo
    read -rs -p "Ещё раз: " P2; echo
    [ "$P1" = "$P2" ] || fail "пароли не совпали"
    [ "${#P1}" -ge 6 ] || fail "пароль короче 6 символов"
    KEY_PASS="$P1"; KS_PASS="$P1"; unset P1 P2
  else
    read -rs -p "Пароль ключа подписи (ввод не отображается): " KS_PASS; echo
    [ -n "$KS_PASS" ] || fail "пустой пароль"
    KEY_PASS="$KS_PASS"
  fi
  export BUBBLEWRAP_KEYSTORE_PASSWORD="$KS_PASS" BUBBLEWRAP_KEY_PASSWORD="$KEY_PASS"
  unset KS_PASS KEY_PASS
fi
export BUBBLEWRAP_KEY_PASSWORD="${BUBBLEWRAP_KEY_PASSWORD:-$BUBBLEWRAP_KEYSTORE_PASSWORD}"

if [ "$NEW_KEY" = 1 ]; then
  if [ -f "$KEYSTORE" ]; then
    old="$KEYSTORE.old-$(date +%Y%m%d-%H%M%S)"; mv "$KEYSTORE" "$old"; echo "Старый ключ отложен: $old"
  fi
  # PKCS12: пароль ключа = пароль хранилища (keytool иначе игнорирует отдельный пароль ключа)
  export BUBBLEWRAP_KEY_PASSWORD="$BUBBLEWRAP_KEYSTORE_PASSWORD"
  "$KT" -genkeypair -storetype PKCS12 -keystore "$KEYSTORE" -alias "$ALIAS" -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Modus Golos, O=Cyber QALQAN Systems, L=Pavlodar, C=KZ" \
    -storepass:env BUBBLEWRAP_KEYSTORE_PASSWORD -keypass:env BUBBLEWRAP_KEY_PASSWORD >/dev/null 2>&1 || fail "keytool не создал ключ"
  chmod 600 "$KEYSTORE"
  FP=$("$KT" -list -v -keystore "$KEYSTORE" -alias "$ALIAS" -storepass:env BUBBLEWRAP_KEYSTORE_PASSWORD 2>/dev/null | sed -n 's/^[[:space:]]*SHA256: //p' | head -1)
  [ -n "$FP" ] || fail "не удалось прочитать отпечаток нового ключа"
  python3 - "$ASSETLINKS" "$FP" <<'PY'
import json, sys
path, fp = sys.argv[1], sys.argv[2]
links = json.load(open(path, encoding="utf-8"))
for l in links:
    l["target"]["sha256_cert_fingerprints"] = [fp]   # оба приложения — одним новым ключом
open(path, "w", encoding="utf-8").write(json.dumps(links, ensure_ascii=False, indent=2) + "\n")
PY
  echo "Новый ключ создан: $KEYSTORE"
  echo "Отпечаток вписан в $ASSETLINKS: $FP"
fi

# проверка паролей до сборки (keytool читает их из переменных окружения — в командной строке и выводе их нет)
"$KT" -list -keystore "$KEYSTORE" -alias "$ALIAS" -storepass:env BUBBLEWRAP_KEYSTORE_PASSWORD >/dev/null 2>&1 \
  || fail "пароль не подходит к $KEYSTORE. Если пароль потерян — tools/build_apk.sh --new-key"
"$KT" -certreq -keystore "$KEYSTORE" -alias "$ALIAS" -storepass:env BUBBLEWRAP_KEYSTORE_PASSWORD \
  -keypass:env BUBBLEWRAP_KEY_PASSWORD -file /dev/null >/dev/null 2>&1 || fail "пароль ключа $ALIAS не подходит"   # certreq трогает закрытый ключ, хранилище не меняет
echo "Пароль подходит. Сборка: $TARGETS"

mkdir -p "$OUT"
for t in $TARGETS; do
  case "$t" in app) name="modus-golos.apk" ;; boss) name="modus-golos-director.apk" ;; esac
  echo
  echo "== $t → $OUT/$name"
  rm -f "$ANDROID_DIR/$t/app-release-signed.apk"
  ( cd "$ANDROID_DIR/$t" && "$BW" build --skipPwaValidation --signingKeyPath="$KEYSTORE" --signingKeyAlias="$ALIAS" 2>&1 | mask )
  [ -f "$ANDROID_DIR/$t/app-release-signed.apk" ] || fail "сборка $t не дала app-release-signed.apk"
  cp "$ANDROID_DIR/$t/app-release-signed.apk" "$OUT/$name"
  ver=$(grep -E '"appVersion(Name|Code)"' "$ANDROID_DIR/$t/twa-manifest.json" | tr -d ' ",' | paste -sd' ' -)
  printf "   готово: %s (%s КБ; %s)\n" "$name" "$(( $(stat -c %s "$OUT/$name") / 1024 ))" "$ver"
done
unset BUBBLEWRAP_KEYSTORE_PASSWORD BUBBLEWRAP_KEY_PASSWORD
echo
echo "Готово. Отпечатки подписи APK (должны совпадать с $ASSETLINKS):"
for t in $TARGETS; do
  case "$t" in app) name="modus-golos.apk" ;; boss) name="modus-golos-director.apk" ;; esac
  "$KT" -printcert -jarfile "$OUT/$name" 2>/dev/null | grep -E 'SHA256:' | sed "s|^[[:space:]]*|   $name |" || true
done
[ "$NEW_KEY" = 1 ] && echo "Ключ новый: на телефоне удалите старое приложение и поставьте новый APK (поверх старого не встанет)."
echo "Дальше: передать APK на телефон (docs/ANDROID.md) и закоммитить demo/android/*.apk и assetlinks.json."
