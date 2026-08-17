#!/usr/bin/env bash
# Install the timer that copies this rig's offers to a machine outside the car.
#
#   bash tools/install-sync.sh http://nuc.lan:8081
#
# Everything the unit needs is discovered rather than assumed. The first version
# of this shipped units with `User=pi` and `/home/pi/Uber_Scan` written into
# them, which is the default on a fresh Raspberry Pi OS image and is wrong the
# moment anybody names their account something else — and it fails at
# `systemctl enable` time with a message about a unit file, which does not point
# at the actual problem.
set -eu

usage() {
    cat <<'EOF'
usage: bash tools/install-sync.sh <url-of-the-machine-keeping-the-copy> [token]

  bash tools/install-sync.sh http://nuc.lan:8081
  bash tools/install-sync.sh https://nuc.example.net secret-token

Use the address that works from the *road*, not just the driveway. A Tailscale
or WireGuard name syncs from anywhere the rig has a signal; a 192.168.x.x
address only syncs when it is parked at home, which is the one time the data
was never really at risk.
EOF
}

if [ "$#" -lt 1 ] || [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 1
fi

SYNC_TO="$1"
SYNC_TOKEN="${2:-}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# The account that owns the checkout, not whoever ran sudo. Getting this wrong
# gives a timer that runs as root and writes root-owned files into a home
# directory, which then breaks the scanner rather than the sync.
RUN_AS="$(stat -c '%U' "$REPO")"
PYTHON="$(command -v python3 || true)"

if [ -z "$PYTHON" ]; then
    echo "no python3 on PATH — the sync needs it" >&2
    exit 1
fi
if [ ! -f "$REPO/rpi/sync.py" ]; then
    echo "$REPO does not look like the Uber Scan checkout (no rpi/sync.py)." >&2
    echo "Run this from inside the repository, and 'git pull' first if it is old." >&2
    exit 1
fi

echo "repository : $REPO"
echo "running as : $RUN_AS"
echo "python     : $PYTHON"
echo "sending to : $SYNC_TO"
echo

# Check it actually works before installing a timer that will do it every ten
# minutes. A timer that has never succeeded once is a timer that fails quietly.
echo "trying it once..."
if ! sudo -u "$RUN_AS" "$PYTHON" "$REPO/rpi/sync.py" --to "$SYNC_TO" \
        ${SYNC_TOKEN:+--token "$SYNC_TOKEN"}; then
    echo
    echo "That did not work, so the timer is not being installed — fix the above"
    echo "first. If it says the far end did not answer, check that the machine"
    echo "keeping the copy is running with SCANNER=0 and is reachable at"
    echo "$SYNC_TO from this Pi." >&2
    exit 1
fi
echo

UNIT=/etc/systemd/system/uberscan-sync.service
TIMER=/etc/systemd/system/uberscan-sync.timer

sudo tee "$UNIT" >/dev/null <<EOF
# Written by tools/install-sync.sh. Re-run that rather than editing this.
[Unit]
Description=Copy this rig's offers to the machine that keeps them
# No network dependency on purpose: being out of range is the normal state in a
# car, and sync.py treats it as such — it says so and exits 0.
After=network.target

[Service]
Type=oneshot
User=$RUN_AS
WorkingDirectory=$REPO
Environment=SYNC_TO=$SYNC_TO
${SYNC_TOKEN:+Environment=SYNC_TOKEN=$SYNC_TOKEN}
# Sends the offers and, alongside them, the 400-byte calibration.
# Add --no-config if you would rather that stayed in the car.
ExecStart=$PYTHON $REPO/rpi/sync.py --quiet

# It reads one file and writes nothing locally.
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$REPO/rpi

[Install]
WantedBy=multi-user.target
EOF

sudo tee "$TIMER" >/dev/null <<'EOF'
# Written by tools/install-sync.sh. Re-run that rather than editing this.
[Unit]
Description=Copy this rig's offers to the machine that keeps them, regularly

[Timer]
# The interval is not a throughput decision — a shift's offers are about 50kB —
# it is how long the newest offer can be missing from the copy if the card dies
# at the worst moment.
OnBootSec=2min
OnUnitActiveSec=10min
# So a run missed while the car was parked and the Pi powered down happens once
# at the next boot rather than being skipped in silence.
Persistent=true
RandomizedDelaySec=60s

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now uberscan-sync.timer

echo
echo "installed. it will run every ten minutes."
echo
echo "  systemctl list-timers uberscan-sync.timer    # when it next runs"
echo "  systemctl start uberscan-sync.service        # run it now"
echo "  journalctl -u uberscan-sync.service -n 20    # what it said"
