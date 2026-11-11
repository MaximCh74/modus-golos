#!/usr/bin/env bash
# Именованный туннель Cloudflare с постоянным поддоменом → localhost:8070 (этап 2: HTTPS для MediaRecorder на телефоне,
# постоянный адрес для напечатанных QR). Один раз делает владелец домена: `cloudflared tunnel login` (браузер, выбрать зону).
# Дальше: tools/tunnel.sh setup modus.cq-systems.kz   — создать туннель, DNS-запись и конфиг
#         tools/tunnel.sh run                          — запустить (или systemd: tools/tunnel.sh install)
set -euo pipefail
CF="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"
NAME="${TUNNEL_NAME:-modus}"
PORT="${MF_PORT_LOCAL:-8070}"
CFG="$HOME/.cloudflared/config.yml"
cmd="${1:-help}"
case "$cmd" in
  setup)
    HOST="${2:?Укажите поддомен, например modus.cq-systems.kz}"
    [ -f "$HOME/.cloudflared/cert.pem" ] || { echo "Сначала: $CF tunnel login (откроется браузер, выберите домен)"; exit 1; }
    if ! "$CF" tunnel list 2>/dev/null | grep -q " $NAME "; then "$CF" tunnel create "$NAME"; fi
    ID=$("$CF" tunnel list --name "$NAME" --output json | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["id"])')
    cat > "$CFG" <<YML
tunnel: $ID
credentials-file: $HOME/.cloudflared/$ID.json
ingress:
  - hostname: $HOST
    service: http://localhost:$PORT
    originRequest:
      noTLSVerify: true
  - service: http_status:404
YML
    "$CF" tunnel route dns --overwrite-dns "$NAME" "$HOST"
    echo "Готово: https://$HOST → localhost:$PORT. Пропишите в .env: MF_PUBLIC_URL=https://$HOST и перезапустите сервер."
    ;;
  run) exec "$CF" tunnel --config "$CFG" run "$NAME" ;;
  install)   # пользовательский systemd (без sudo): стартует при входе, перезапускается сам
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/cloudflared-$NAME.service" <<UNIT
[Unit]
Description=Cloudflare tunnel $NAME → localhost:$PORT
After=network-online.target
[Service]
ExecStart=$CF tunnel --config $CFG run $NAME
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable --now "cloudflared-$NAME.service"
    systemctl --user status "cloudflared-$NAME.service" --no-pager | head -5
    ;;
  status) "$CF" tunnel info "$NAME" 2>&1 | head -20; systemctl --user status "cloudflared-$NAME.service" --no-pager 2>/dev/null | head -5 || true ;;
  *) echo "Использование: $0 setup <host> | run | install | status" ;;
esac
