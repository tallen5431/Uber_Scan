#!/usr/bin/env bash
# Install the timer that copies this rig's offers to a machine outside the car.
#
#   bash tools/install-sync.sh http://nuc.lan:8080
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

  bash tools/install-sync.sh http://nuc.lan:8080
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

# Check the destination answers at all, before anything else.
#
# The "try it once" run below cannot do this on its own, and that is deliberate
# on sync.py's side rather than a bug: a car is out of range most of the time,
# so a failure to connect is normal and exits 0. Which means this gate — whose
# whole purpose is "do not install a timer that has never worked" — passed
# happily on an address nothing was listening on, and the driver got a timer
# quietly syncing to nowhere. Ask the question sync.py refuses to fail on, using
# sync's own far_end so the check that a router login page is not the far end
# stays in one place.
echo "checking $SYNC_TO answers..."
if ! sudo -u "$RUN_AS" "$PYTHON" -c "
import sys
sys.path.insert(0, '$REPO/rpi')
import sync
sys.exit(0 if isinstance(sync.far_end('$SYNC_TO'), dict) else 1)
"; then
    cat >&2 <<EOF

Nothing answered at $SYNC_TO, so the timer is not being installed.

The machine keeping the copy runs the same server as this one, with SCANNER=0
so it does not try to open a camera it has not got. It listens on 8080 unless
PORT says otherwise — 8081 is this Pi's aiming preview, which is a different
thing and cannot receive a journal.

  on the copy machine:  SCANNER=0 npm start
  then from here:       curl $SYNC_TO/api/journal/newest
EOF
    exit 1
fi

# ...and then that a real send gets through: the far end may answer and still
# refuse, for reasons worth naming separately below.
echo "trying it once..."
if ! sudo -u "$RUN_AS" "$PYTHON" "$REPO/rpi/sync.py" --to "$SYNC_TO" \
        ${SYNC_TOKEN:+--token "$SYNC_TOKEN"}; then
    echo
    cat >&2 <<EOF
That did not work, so the timer is not being installed — a timer whose job has
never succeeded once is a timer that fails quietly. Fix the above first.

  could not create ...    JOURNAL there points somewhere that account cannot
                          write. Either give it the directory, or point JOURNAL
                          inside its home, where it will make it itself
  older build             it has its own checkout: git pull and restart it there
EOF
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
