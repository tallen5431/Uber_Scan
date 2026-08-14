#!/usr/bin/env bash
# Install the scanner as a systemd service so it starts with the Pi.
#
#   sudo bash rpi/install-service.sh          # verdicts spoken aloud
#   SPEAK=0 sudo bash rpi/install-service.sh  # printed to the journal only
#
# Paths and the user are baked in from wherever this is run, so a clone in a
# home directory works without editing anything.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo" >&2
  exit 1
fi

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(logname 2>/dev/null || echo pi)}"
SPEAK="${SPEAK:-1}"
ARGS=""
[ "$SPEAK" = "1" ] && ARGS="--speak"

if [ ! -f "$PROJECT/rpi/config.json" ]; then
  echo "warning: $PROJECT/rpi/config.json is missing — the service will fail"
  echo "         until you run: python3 rpi/calibrate.py"
  echo
fi

cat > /etc/systemd/system/uberscan.service <<UNIT
[Unit]
Description=Uber Scan — reads ride offers from the phone screen
After=multi-user.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT
ExecStart=/usr/bin/python3 $PROJECT/rpi/scan_pi.py $ARGS
# The camera and calibration are not always ready the instant the Pi is, so let
# it retry rather than giving up after the default burst of fast restarts.
Restart=on-failure
RestartSec=5
StartLimitIntervalSec=0
# Speech needs the user's audio devices.
SupplementaryGroups=audio video
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable uberscan.service
systemctl restart uberscan.service

cat <<DONE

Installed and started as user $RUN_USER, from $PROJECT

  systemctl status uberscan      # is it running
  journalctl -u uberscan -f      # watch reads as they happen
  systemctl stop uberscan        # while calibrating, so the camera is free
DONE
