#!/usr/bin/env bash
# Install the rig as a systemd service so it starts with the Pi.
#
#   sudo bash rpi/install-service.sh              # verdicts spoken aloud
#   sudo SPEAK=0 bash rpi/install-service.sh      # printed to the journal only
#   sudo ARGS="--keep-scans" bash rpi/install-service.sh   # flags for the scanner
#
# ...and on the machine at home that keeps the copy, which has no camera:
#
#   sudo COPY=/var/lib/uberscan/journal.jsonl bash rpi/install-service.sh
#
# The receiving end holds the only copy of the one artefact this project calls
# irreplaceable, and until now it was documented as a command typed into a
# terminal — "that is the whole install" — so it ended the moment the machine
# rebooted or the terminal closed. Every layer below is built to stay quiet
# about that: `far_end()` returns None on a refused connection and sync.py
# exits 0, because a car is offline most of the time and a timer that complains
# every ten minutes about a normal condition is a timer nobody reads. Correct
# for being out of range, and it means a backup that has simply stopped looks
# exactly the same from the car.
#
# `sudo SPEAK=0 bash`, not `SPEAK=0 sudo bash`: sudo resets the environment
# by default and the second form silently installed a speaking rig.
#
# The unit runs the web server, which spawns the scanner itself — the same
# thing `npm start` does. It used to run the scanner alone, and a rig booted
# that way had a driving screen that could never show a verdict: readings
# reach the panel only through the server that spawned the scanner, and the
# aim message on that screen told the driver to open it.
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
ARGS="${ARGS:-}"
# Where the copy is kept, and the flag that says this is the copy machine.
# A path rather than a boolean, because the path is the part that must not be
# left at its default: the journal would land in rpi/journal.jsonl inside the
# clone, which works and stands the only backup next to a `git clean`.
COPY="${COPY:-}"

# node, found the way the driver's own shell finds it — nvm installs live in
# the home directory and root's PATH does not see them.
NODE="$(command -v node || true)"
if [ -z "$NODE" ]; then
  NODE="$(sudo -u "$RUN_USER" -i sh -c 'command -v node' 2>/dev/null || true)"
fi
if [ -z "$NODE" ]; then
  echo "node is not installed, or not on the PATH of $RUN_USER. Install it (the" >&2
  echo "README says how), or run this again as: NODE=/path/to/node sudo -E bash $0" >&2
  exit 1
fi

# The copy machine has no camera and nothing to calibrate, so neither of the
# two checks below is about it: one warns that a missing config means the rig
# will aim itself, and the other is the aiming preview. Here the equivalent
# worry is the directory, which the server can only make where it is allowed
# to — and this script is already root, which is the one moment in the whole
# install where making it is free.
if [ -n "$COPY" ]; then
  case "$COPY" in
    /*) : ;;
    *) echo "COPY wants an absolute path for the journal, e.g." >&2
       echo "  sudo COPY=/var/lib/uberscan/journal.jsonl bash $0" >&2
       exit 1 ;;
  esac
  COPY_DIR="$(dirname "$COPY")"
  mkdir -p "$COPY_DIR"
  chown "$RUN_USER" "$COPY_DIR"
  echo "the copy will be kept in $COPY (owned by $RUN_USER)"
  echo
fi

if [ -z "$COPY" ] && [ ! -f "$PROJECT/rpi/config.json" ]; then
  echo "note: $PROJECT/rpi/config.json is missing, so the first start will aim"
  echo "      and calibrate itself. Watch it do that on /live.html, or with:"
  echo "         journalctl -u uberscan -f"
  echo
fi

# The unit runs the web server, which spawns autopilot.py — not scan_pi.py.
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
# The two machines run the SAME server and differ in three lines, so the unit
# is one template with those three substituted rather than two units that can
# drift. What differs, and why each one:
#
#   SCANNER=0     the copy machine has no picamera2, and without this the
#                 server starts the scanner, fails, and restart-loops every few
#                 seconds for ever — the exact failure the README warns about
#                 and the reason this script could not simply be reused there.
#   JOURNAL       where the copy is kept. Left at the default it lands inside
#                 the clone, beside a `git clean`.
#   audio video   speech needs the driver's audio devices. The copy machine
#                 says nothing and has no camera, so the grants are dropped
#                 rather than granted to something that cannot use them.
if [ -n "$COPY" ]; then
  DESCRIPTION="Uber Scan — the copy of the journal, and the pages that read it"
  UNIT_ENV="Environment=SCANNER=0
Environment=JOURNAL=$COPY"
  UNIT_GROUPS=""
else
  DESCRIPTION="Uber Scan — the panel, and the scanner that reads offers off the phone"
  UNIT_ENV="Environment=SCANNER_SPEAK=$SPEAK
Environment=\"SCANNER_ARGS=$ARGS\""
  UNIT_GROUPS="SupplementaryGroups=audio video"
fi

cat > /etc/systemd/system/uberscan.service <<UNIT
[Unit]
Description=$DESCRIPTION
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
# On the rig: aims, calibrates if it has to, then becomes the scanner — see the
# note above — and whether the verdicts are spoken, plus any flags, reach the
# autopilot through the server that spawns it. SCANNER_ARGS is quoted, because
# systemd reads Environment= as a space-separated list of assignments:
# unquoted, ARGS="--keep-scans --screen-fps 6" installs
# SCANNER_ARGS=--keep-scans and silently discards the rest, and a flag that
# takes a value loses its value — which is how "--screen-fps 6" becomes a
# scanner that exits on a missing argument and a unit that restarts for ever.
#
# On the copy machine: SCANNER=0 and where to keep the journal. See above.
$UNIT_ENV
ExecStart=$NODE $PROJECT/server.js
# The camera and calibration are not always ready the instant the Pi is, so let
# it retry rather than giving up after the default burst of fast restarts.
Restart=on-failure
RestartSec=5
$UNIT_GROUPS
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable uberscan.service
systemctl restart uberscan.service

if [ -n "$COPY" ]; then
cat <<DONE

Installed and started as user $RUN_USER, from $PROJECT
Keeping the copy of the journal in $COPY

  systemctl status uberscan      # is it running
  journalctl -u uberscan -f      # watch it take what the rig sends

It keeps serving whether or not the journal can be written, which is
deliberate — the pages are worth more than the write — so a running server is
not by itself evidence that anything is landing. The line that says which is
the last one printed at startup.

  then on the rig:  bash tools/install-sync.sh http://$(hostname):8080
DONE
else
cat <<DONE

Installed and started as user $RUN_USER, from $PROJECT

  systemctl status uberscan      # is it running
  journalctl -u uberscan -f      # watch it aim, calibrate and then read
  systemctl stop uberscan        # before running \`npm start\` or any of the
                                 # rpi/ scripts by hand — this IS the web
                                 # server, and it holds the camera
DONE
fi
