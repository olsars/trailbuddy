#!/usr/bin/env bash
# One-time setup, run ON THE PI from the repo:   sudo bash hardware/install-autostart.sh
#
# Installs two services so the Pi starts everything by itself when it is powered on:
#   trailbuddy-backend  the web page + API (port 8000)
#   trailbuddy-menu     the device program (OLED, button, GPS), talking to that local backend
#
# Optional settings (environment variables):
#   TB_VENV   Python virtualenv to use         (default: /home/<you>/tb-env)
#   TB_PORT   port for the backend             (default: 8000)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(id -un)}"
VENV="${TB_VENV:-/home/$RUN_USER/tb-env}"
PORT="${TB_PORT:-8000}"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"       # UNIT_DIR / DRY_RUN exist so this script can be tested off the Pi
PY="$VENV/bin/python"

if [ "${DRY_RUN:-0}" != "1" ]; then
  [ "$(id -u)" = "0" ] || { echo "Run this with sudo:  sudo bash hardware/install-autostart.sh"; exit 1; }
  command -v systemctl >/dev/null || { echo "systemctl not found: this script is for the Raspberry Pi."; exit 1; }
fi

[ -x "$PY" ] || { echo "No Python found at $PY. If your virtualenv is somewhere else, run: sudo TB_VENV=/path/to/venv bash $0"; exit 1; }
if [ "${DRY_RUN:-0}" != "1" ]; then
  "$PY" -c "import fastapi, uvicorn" 2>/dev/null || { echo "The backend's packages are missing. Run:"; echo "  $VENV/bin/pip install -r $REPO/backend/requirements.txt"; exit 1; }
  "$PY" -c "import serial, pynmea2, requests, gpiozero, luma.oled" 2>/dev/null || { echo "The device packages are missing. Run:"; echo "  $VENV/bin/pip install pynmea2 pyserial requests gpiozero luma.oled pillow smbus2"; exit 1; }
fi
[ -f "$REPO/frontend/dist/index.html" ] || echo "NOTE: $REPO/frontend/dist is missing, so the web page will not load until you copy it over (see hardware/README.md, 'Copy the web page')."

mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/trailbuddy-backend.service" << UNIT
[Unit]
Description=TrailBuddy backend (API and web page)
After=network.target

[Service]
User=$RUN_USER
WorkingDirectory=$REPO
Environment=PYTHONUNBUFFERED=1
ExecStart=$PY -m uvicorn backend.main:app --host 0.0.0.0 --port $PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

cat > "$UNIT_DIR/trailbuddy-menu.service" << UNIT
[Unit]
Description=TrailBuddy device program (OLED, button, GPS)
After=trailbuddy-backend.service
Wants=trailbuddy-backend.service

[Service]
User=$RUN_USER
WorkingDirectory=$REPO
Environment=PYTHONUNBUFFERED=1
Environment=TRAILBUDDY_API=http://127.0.0.1:$PORT
ExecStart=$PY $REPO/hardware/menu.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "Dry run: wrote the unit files to $UNIT_DIR"
  exit 0
fi

systemctl daemon-reload
systemctl enable --now trailbuddy-backend.service trailbuddy-menu.service
sleep 4
echo
systemctl --no-pager --lines=0 status trailbuddy-backend.service trailbuddy-menu.service || true
echo
echo "Done. Both start automatically whenever the Pi is powered on."
echo "On a phone joined to the same hotspot, open the address shown under 'Phone link' on the Pi's screen."
echo "To run the program by hand instead, stop it first:  sudo systemctl stop trailbuddy-menu"