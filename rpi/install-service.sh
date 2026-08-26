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
  echo "note: $PROJECT/rpi/config.json is missing, so the first start will aim"
  echo "      and calibrate itself. Watch it do that on /live.html, or with:"
  echo "         journalctl -u uberscan -f"
  echo
fi

# The unit runs autopilot.py, not scan_pi.py.
#
# scan_pi.py is the scanner and nothing else: it reads rpi/config.json and
# starts reading offers. On a rig that has never been calibrated there is no
# config to read, so it exits immediately — and the unit restarts on failure,
# which made a service that respawned every five seconds forever while the
# driver watched a blank live view. The check above printed a warning about
# that instead of avoiding it.
#
# autopilot.py is the entry point everything else already uses: the web server
# spawns exactly this, and the README documents it as the one command that
# takes the rig from nothing to scanning. It checks the camera, serves the
# aiming preview until the mount is good, calibrates the moment the frame holds
# steady, then execs scan_pi.py in its own place — so there is still one
# process for systemd to stop. Already calibrated it goes straight to scanning,
# and this costs nothing.
cat > /etc/systemd/system/uberscan.service <<UNIT
[Unit]
Description=Uber Scan — reads ride offers from the phone screen
After=multi-user.target
# [Unit], not [Service]. systemd moved these two out of [Service] in v230 and
# does not error on the old placement — it logs "Unknown key name" and carries
# on with the default, so the intent below was being silently dropped: five
# starts inside ten seconds and the unit would give up for good. The camera and
# the calibration are not always ready the instant the Pi is, and a rig that
# stops trying is a shift that does not happen.
StartLimitIntervalSec=0

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT
# Aims, calibrates if it has to, then becomes the scanner. See the note above.
ExecStart=/usr/bin/python3 $PROJECT/rpi/autopilot.py $ARGS
# The camera and calibration are not always ready the instant the Pi is, so let
# it retry rather than giving up after the default burst of fast restarts.
Restart=on-failure
RestartSec=5
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
  journalctl -u uberscan -f      # watch it aim, calibrate and then read
  systemctl stop uberscan        # before running anything else that wants the
                                 # camera — including \`npm start\`, which spawns
                                 # its own copy of the autopilot
DONE
