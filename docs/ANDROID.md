# Android-приложения «Модус Голос» (TWA)

Пункт 5 очереди 12.11.2026. Два приложения для Android — обёртки Trusted Web Activity над нашими PWA: сайт открывается в Chrome
без адресной строки, как обычное приложение. iOS — только PWA («На экран „Домой“» в Safari), App Store — в роадмапе.

| Приложение | Пакет | Что открывает | APK |
|---|---|---|---|
| **Модус Голос** | `kz.cqsystems.modusgolos` | `https://modus.cq-systems.kz/app` — приложение сотрудника (и панель через ссылки) | `demo/android/modus-golos.apk` |
| **Директор** | `kz.cqsystems.modusgolos.boss` | `https://modus.cq-systems.kz/boss` — «Директор в кармане» | `demo/android/modus-golos-director.apk` |

Оба подписаны одним демо-ключом; его отпечаток SHA-256 опубликован в `web/.well-known/assetlinks.json` (отдаётся по
`https://modus.cq-systems.kz/.well-known/assetlinks.json`). По нему Chrome проверяет, что приложение принадлежит сайту, и убирает
адресную строку. Если файл недоступен (туннель выключен), приложение всё равно откроется — но в виде вкладки Chrome с адресной строкой.

## Установка на телефон (демо)

1. Передать файл APK на телефон: через WhatsApp/Telegram «файлом», по кабелю или ссылкой на `demo/android/…apk` из репозитория.
2. Открыть файл на телефоне → Android спросит «Разрешить установку из этого источника?» → разрешить (для мессенджера или «Файлов»).
3. Установить → на экране появится значок «Модус Голос» (или «Директор»).
4. Первый запуск требует интернета: приложение загружает сайт. Вход — как обычно: `/login` (демо) или через Битрикс24; «Директор»
   пускает только директора.
5. Нужны Android 7.0 и новее (minSdk 24 — требование библиотеки TWA) и Chrome на телефоне — он есть на всех современных Android.

Google Play не требуется. Для публикации в Play понадобится отдельный ключ выпуска и аккаунт разработчика — это роадмап.

## Пересборка (на ноутбуке владельца)

Сборка идёт вне репозитория, в `~/MODUS_ANDROID/`:

```
~/MODUS_ANDROID/
  modus-golos.keystore      # демо-ключ подписи (alias modusgolos); пароли — у владельца (сообщение от 12.11)
  app/twa-manifest.json     # проект Bubblewrap «Модус Голос»
  boss/twa-manifest.json    # проект Bubblewrap «Директор»
```

Инструменты: Node 22, Bubblewrap CLI (`~/.local/bubblewrap/node_modules/.bin/bubblewrap`), JDK 17 (`~/development/jdk-17`),
Android SDK (`~/Android/Sdk`; Bubblewrap ждёт `tools/bin/sdkmanager` — сделана ссылка `tools → cmdline-tools/latest`),
конфиг `~/.bubblewrap/config.json` с путями к JDK и SDK.

```bash
cd ~/MODUS_ANDROID/app   # или boss
export BUBBLEWRAP_KEYSTORE_PASSWORD=… BUBBLEWRAP_KEY_PASSWORD=… JAVA_HOME=~/development/jdk-17 ANDROID_HOME=~/Android/Sdk
~/.local/bubblewrap/node_modules/.bin/bubblewrap update --skipVersionUpgrade   # после правок twa-manifest.json (иконки качаются с сайта)
~/.local/bubblewrap/node_modules/.bin/bubblewrap build --skipPwaValidation      # → app-release-signed.apk, app-release-bundle.aab
cp app-release-signed.apk ~/MODUS_FEEDBACK/demo/android/modus-golos.apk        # для boss — modus-golos-director.apk
```

При новой версии поднять `appVersionCode`/`appVersionName` в `twa-manifest.json`. Если ключ подписи меняется — обновить отпечаток
в `web/.well-known/assetlinks.json` (`keytool -list -v -keystore … | grep SHA256`) и переустановить приложения.

## Что проверить на телефоне

- Открывается без адресной строки (значит, assetlinks прочитан); при первом запуске может быть короткая заставка с логотипом.
- Голосовой ввод и запись планёрки работают (микрофон запрашивается как у сайта).
- «Директор»: вход не директором показывает «Только для директора».
- Уведомления push не реализованы (in-app и Битрикс24) — как и в PWA.
