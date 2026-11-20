#!/usr/bin/env bash
# Install the update (tools/autoupdate.sh) as a systemd timer: hourly on the
# rig, which is on only while driving, and nightly at 04:20 on the NucBox.
#
#   sudo bash tools/install-autoupdate.sh rig                     # the Pi in the car
#   sudo bash tools/install-autoupdate.sh nucbox --restart-cmd 'COMMAND'
#   sudo bash tools/install-autoupdate.sh off                     # stop it
#
# Options, either role:
#   --branch NAME      the branch followed (default main, the gated one; a lite
#                      rig may follow lite once that branch exists)
#   --port N           the server's port (rig: uberscan.service's PORT, else
#                      8080; NucBox: 8082)
#   --quiet-min N      rig: minutes with no offer or reading that count as no
#                      shift (default 90)
#   --hours LIST       rig: the hours it may update in (default 22-10,14-16:
#                      not in the lunch or dinner rush; '' for any hour)
#   --verify-signed    take a commit only when `git verify-commit` passes
#   --lock PATH        the lock (NucBox default: places_nightly.sh's own)
#   --root             NucBox only: run as root, for a RESTART_CMD that needs it
#                      (git still runs as the checkout's owner)
#
# Writes /etc/uberscan/autoupdate.env (the settings, rewritten whole on every
# run; edit and the next night reads it), and uberscan-update.service and
# uberscan-update.timer. Then runs the update once with --dry-run, so the
# owner sees the fetch work before trusting a timer with it — a timer whose job
# has never succeeded once fails quietly (tools/install-sync.sh's rule).
#
# Paths and the account are found, not assumed, as the other installers do.
set -euo pipefail

usage() { sed -n '2,/^# Paths and the account/p' "$0" | sed '$d; s/^# \{0,1\}//'; }

# Where the units go; the tests point both into a temp dir.
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
ENV_DIR="${ENV_DIR:-/etc/uberscan}"
ENV_FILE="$ENV_DIR/autoupdate.env"

ROLE="${1:-}"
case "$ROLE" in
    rig|nucbox|off) shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 1 ;;
esac

if [ "$(id -u)" -ne 0 ]; then
    echo "run with sudo: sudo bash $0 $ROLE ..." >&2
    exit 1
fi

if [ "$ROLE" = off ]; then
    systemctl disable --now uberscan-update.timer 2>/dev/null || true
    if [ -f "$ENV_FILE" ]; then
        grep -v '^ENABLED=' "$ENV_FILE" > "$ENV_FILE.tmp" || true
        echo 'ENABLED=0' >> "$ENV_FILE.tmp"
        mv "$ENV_FILE.tmp" "$ENV_FILE"
    fi
    echo "the nightly update is off (timer disabled, ENABLED=0)."
    echo "back on: sudo bash $0 rig   (or nucbox, with its --restart-cmd)"
    exit 0
fi

BRANCH=main
PORT=""
QUIET_MIN=90
UPDATE_HOURS="22-10,14-16"
VERIFY_SIGNED=0
LOCK=""
RESTART_CMD=""
AS_ROOT=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --branch) BRANCH="${2:?--branch needs a name}"; shift 2 ;;
        --port) PORT="${2:?--port needs a number}"; shift 2 ;;
        --quiet-min) QUIET_MIN="${2:?--quiet-min needs minutes}"; shift 2 ;;
        --hours) UPDATE_HOURS="${2?--hours needs hours, e.g. 22-10,14-16}"; shift 2 ;;
        --verify-signed) VERIFY_SIGNED=1; shift ;;
        --lock) LOCK="${2:?--lock needs a path}"; shift 2 ;;
        --restart-cmd) RESTART_CMD="${2:?--restart-cmd needs a command}"; shift 2 ;;
        --root) AS_ROOT=1; shift ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done
case "$PORT" in *[!0-9]*) echo "--port is a number" >&2; exit 1 ;; esac
case "$QUIET_MIN" in ''|*[!0-9]*) echo "--quiet-min is minutes" >&2; exit 1 ;; esac
case "$UPDATE_HOURS" in *[!0-9,\ -]*) echo "--hours: hours and ranges, e.g. 22-10,14-16" >&2; exit 1 ;; esac
case "$BRANCH" in ''|-*|*[!A-Za-z0-9._/-]*) echo "--branch: a branch name, not '$BRANCH'" >&2; exit 1 ;; esac

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNER="$(stat -c '%U' "$REPO")"
OWNER_HOME="$(getent passwd "$OWNER" | cut -d: -f6)"
OWNER_HOME="${OWNER_HOME:-/home/$OWNER}"

if [ ! -f "$REPO/tools/autoupdate.sh" ] || ! git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
    echo "$REPO does not look like the Uber Scan checkout (no tools/autoupdate.sh, or not git)." >&2
    exit 1
fi
ON="$(runuser -u "$OWNER" -- git -C "$REPO" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
if [ "$ON" != "$BRANCH" ]; then
    cat >&2 <<EOF
The checkout is on ${ON:-a detached HEAD}, and the update follows $BRANCH. It
never switches branches by itself, so switch once, by hand:

  cd "$REPO" && git checkout $BRANCH

($BRANCH is the gated branch: the test gate moves it only when every suite
passed. To keep following ${ON:-what you follow now} as you do by hand today,
run this again with --branch ${ON:-NAME}.)
EOF
    exit 1
fi

if [ "$ROLE" = rig ]; then
    if [ -z "$PORT" ]; then
        # uberscan.service sets no PORT unless somebody added one, and the
        # server's default is 8080 (server.js PORT).
        PORT="$(systemctl show -p Environment --value uberscan.service 2>/dev/null \
                | tr ' ' '\n' | sed -n 's/^PORT=\([0-9][0-9]*\)$/\1/p' | head -n 1 || true)"
        PORT="${PORT:-8080}"
    fi
    if [ ! -f "$UNIT_DIR/uberscan.service" ]; then
        echo "note: no uberscan.service here yet. The update restarts it, so install it"
        echo "      first: sudo bash rpi/install-service.sh (or lite/install.sh)."
        echo
    fi
    RUN_AS=root
    RESTART_CMD=""      # the script's own: uberscan.service, and the lite kiosk
else
    PORT="${PORT:-8082}"
    if [ -z "$RESTART_CMD" ]; then
        cat <<'EOF'
The NucBox's Uber Scan is restarted by its manager app ("Restart Uber Scan"),
and this needs the command that button runs. To find it:

  - the manager's own settings or config file for Uber Scan: a start or
    restart command is usually written there;
  - or press the button and look at who started node:
        ps -eo pid,ppid,lstart,args --forest | grep -B3 'server.js'
    (a pm2 or systemd or docker parent names the command: pm2 restart NAME,
     systemctl --user restart NAME, docker restart NAME, ...)
  - then try it by hand, as the account that owns the checkout, and check the
    server answers again:
        bash -c 'THE COMMAND' && sleep 5 && curl -s http://127.0.0.1:8082/api/status | head -c 80

EOF
        if [ -t 0 ]; then
            read -r -p "restart command: " RESTART_CMD
        fi
        if [ -z "$RESTART_CMD" ]; then
            echo "no restart command: nothing installed. Run again with --restart-cmd 'COMMAND'." >&2
            exit 1
        fi
    fi
    case "$RESTART_CMD" in *$'\n'*) echo "the restart command is one line" >&2; exit 1 ;; esac
    if [ -z "$LOCK" ]; then
        # places_nightly.sh's lock is "$PLACES_OUT.lock", PLACES_OUT from its
        # own settings file or ~/places-report. The same file, so an update
        # can never restart the server under a report being built from it.
        # (|| true: no settings file is the ordinary case, and under pipefail
        # sed's complaint about it ended the install with nothing said.)
        out="$(sed -n 's/^PLACES_OUT=//p' "$OWNER_HOME/.config/uber-scan/places.env" 2>/dev/null | tail -n 1 || true)"
        out="${out%\"}"; out="${out#\"}"; out="${out%\'}"; out="${out#\'}"
        out="${out/#\~/$OWNER_HOME}"
        LOCK="${out:-$OWNER_HOME/places-report}.lock"
    fi
    if [ "$AS_ROOT" = 1 ]; then RUN_AS=root; else RUN_AS="$OWNER"; fi
fi

mkdir -p "$ENV_DIR"
# Quoted for tools/autoupdate.sh's own reader: one level of double quotes
# taken off, nothing expanded. The restart command can hold any character,
# so it is written exactly as given between them.
{
    echo "# Written by tools/install-autoupdate.sh; edit, and the next night reads it."
    echo "# ENABLED=0 turns the update off without removing anything."
    echo "ROLE=$ROLE"
    echo "ENABLED=1"
    echo "REPO=\"$REPO\""
    echo "BRANCH=$BRANCH"
    echo "PORT=$PORT"
    echo "QUIET_MIN=$QUIET_MIN"
    if [ "$ROLE" = rig ]; then
        echo "# The hours it may update in (local clock; empty: any) and once a driver day."
        echo "UPDATE_HOURS=\"$UPDATE_HOURS\""
        echo "DAILY_CAP=1"
    fi
    echo "VERIFY_SIGNED=$VERIFY_SIGNED"
    [ -n "$LOCK" ] && echo "LOCK=\"$LOCK\""
    [ -n "$RESTART_CMD" ] && echo "RESTART_CMD=\"$RESTART_CMD\""
} > "$ENV_FILE.tmp"
chmod 644 "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE"

# One word of a command line for systemd: quoted, \ and " escaped, % and $
# doubled (rpi/install-service.sh's word(), for the same checkout-with-a-space).
word() {
    local s="${1//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//%/%%}"
    s="${s//\$/\$\$}"
    printf '"%s"' "$s"
}

cat > "$UNIT_DIR/uberscan-update.service" <<UNIT
# Written by tools/install-autoupdate.sh. Re-run that rather than editing this.
[Unit]
Description=Uber Scan: take the new commits on $BRANCH, restart, check, or roll back
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$RUN_AS
Environment=$(word "AUTOUPDATE_ENV=$ENV_FILE")
ExecStart=/bin/bash $(word "$REPO/tools/autoupdate.sh")
# The fetch, two restarts and two health checks, with room: past this the
# run is stopped rather than left holding the lock into the nightly report.
TimeoutStartSec=20min
# Out of the way of anything that is not waiting for it.
Nice=10
IOSchedulingClass=idle
UNIT

# Persistent= is left off on purpose, for both. A missed run caught up at the
# next boot is, on the rig, an update at the start of a shift: the Pi is
# switched on with the car. On the NucBox it is a boot that may land beside
# the nightly report. A run missed is missed; the next takes the same commits.
if [ "$ROLE" = rig ]; then
    # Hourly: a Pi in a car is off at 04:20 nearly every night, and a nightly
    # timer there would almost never fire. The script's own gates decide each
    # hour — quiet for QUIET_MIN, still, inside UPDATE_HOURS, once a day.
    cat > "$UNIT_DIR/uberscan-update.timer" <<'UNIT'
# Written by tools/install-autoupdate.sh. Re-run that rather than editing this.
[Unit]
Description=Uber Scan: the rig's update, tried every hour it is on

[Timer]
# Every hour at a random minute in its first twenty, so the next hour's run
# never meets this one (TimeoutStartSec caps a run at twenty minutes).
OnCalendar=hourly
RandomizedDelaySec=20min
AccuracySec=1min

[Install]
WantedBy=timers.target
UNIT
else
    cat > "$UNIT_DIR/uberscan-update.timer" <<'UNIT'
# Written by tools/install-autoupdate.sh. Re-run that rather than editing this.
[Unit]
Description=Uber Scan: the nightly update, just after the 4am driver-day turn

[Timer]
# 04:20 to 04:30: after the day turns at 4am (advice.js DAY_STARTS_AT), when a
# shift is least likely, and done long before places_nightly.sh at 05:17 —
# TimeoutStartSec in the service caps a run at twenty minutes.
OnCalendar=*-*-* 04:20:00
RandomizedDelaySec=10min
AccuracySec=1min

[Install]
WantedBy=timers.target
UNIT
fi

if command -v systemd-analyze >/dev/null 2>&1 && [ "$UNIT_DIR" = /etc/systemd/system ]; then
    systemd-analyze verify "$UNIT_DIR/uberscan-update.service" "$UNIT_DIR/uberscan-update.timer" || true
fi
systemctl daemon-reload
systemctl enable --now uberscan-update.timer

echo
echo "installed: $ROLE, following $BRANCH, the server on port $PORT, running as $RUN_AS"
echo "settings:  $ENV_FILE"
echo
echo "trying it once (--dry-run: every check and the fetch, nothing changed)..."
if [ "$RUN_AS" = root ]; then
    AUTOUPDATE_ENV="$ENV_FILE" bash "$REPO/tools/autoupdate.sh" --dry-run || true
else
    runuser -u "$RUN_AS" -- env AUTOUPDATE_ENV="$ENV_FILE" bash "$REPO/tools/autoupdate.sh" --dry-run || true
fi
cat <<EOF

A "skipped: could not fetch" above means this account cannot fetch without a
password from cron: give it a key with no passphrase (or a credential helper)
for the remote, and try again with:
  sudo systemctl start uberscan-update.service

  systemctl list-timers uberscan-update.timer   # when it next runs
  bash tools/autoupdate.sh --status             # what the last run did
  journalctl -u uberscan-update -n 30           # what it said
  sudo bash tools/install-autoupdate.sh off     # stop it
EOF
