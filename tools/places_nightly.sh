#!/usr/bin/env bash
# The places report, rebuilt every night on the NucBox.
#
#   bash tools/places_nightly.sh            (from cron; see README, "Every night")
#
# 1. If RIG_HOST is set and answers ssh, copies the rig's GPS logs into the
#    NucBox's own (rsync -a, a timeout, never --delete: a log the rig has
#    tidied away stays here). A rig that is off or away is the ordinary case
#    and is logged, not a failure: the report is built from what is here.
# 2. Runs tools/places_report.js against the NucBox's own server, its GPS logs
#    and its Nominatim, into a NEW folder beside the report.
# 3. Only when that run succeeded and wrote a page, swaps it in: the report
#    folder is a symlink to the newest build and is replaced by one rename,
#    so the page the server shows is never half written. A failed run leaves
#    the old report exactly as it was and exits non-zero.
#
# SETTINGS, from the environment or from a file of KEY=value lines (default
# ~/.config/uber-scan/places.env, or PLACES_ENV). The file holds this NucBox's
# own values — the rig's address among them — and is never committed.
#   RIG_HOST          ssh destination of the rig, e.g. pi@<rig-address>; unset: no copy
#   RIG_GPSLOG        the logs on the rig (default: gpslog/, under its home)
#   RIG_SSH_KEY       a key file for ssh to the rig (default: ssh's own); one
#                     with no passphrase, since cron has nobody to type it
#   PLACES_SERVER     the server to read (default http://localhost:8082)
#   PLACES_NOMINATIM  the NucBox's Nominatim (default http://localhost:8088)
#   PLACES_GPS        the NucBox's GPS logs (default ~/gpslog)
#   PLACES_OUT        the report the server serves (default ~/places-report)
#   PLACES_LOG        this script's log (default ~/places-report.log)
#   PLACES_SINCE      YYYY-MM-DD, passed as --since (default: none)
#   PLACES_KEEP       builds kept beside the live one (default 2)
#   RSYNC_TIMEOUT     seconds (default 300); SSH_TIMEOUT seconds (default 10)
#   PLACES_NODE       the node to run (default node)
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${PLACES_ENV:-$HOME/.config/uber-scan/places.env}"
if [ -f "$ENV_FILE" ]; then
    # KEY=value lines only; the environment wins over the file.
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in ''|'#'*) continue ;; esac
        key="${line%%=*}"
        val="${line#*=}"
        case "$key" in
            RIG_HOST|RIG_GPSLOG|RIG_SSH_KEY|PLACES_SERVER|PLACES_NOMINATIM|PLACES_GPS|PLACES_OUT|PLACES_LOG|PLACES_SINCE|PLACES_KEEP|RSYNC_TIMEOUT|SSH_TIMEOUT|PLACES_NODE) ;;
            *) continue ;;
        esac
        val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
        if [ -z "${!key+x}" ]; then
            val="${val/#\~/$HOME}"
            export "$key=$val"
        fi
    done < "$ENV_FILE"
fi

RIG_HOST="${RIG_HOST:-}"
RIG_GPSLOG="${RIG_GPSLOG:-gpslog/}"
RIG_SSH_KEY="${RIG_SSH_KEY:-}"
PLACES_SERVER="${PLACES_SERVER:-http://localhost:8082}"
PLACES_NOMINATIM="${PLACES_NOMINATIM:-http://localhost:8088}"
PLACES_GPS="${PLACES_GPS:-$HOME/gpslog}"
PLACES_OUT="${PLACES_OUT:-$HOME/places-report}"
PLACES_LOG="${PLACES_LOG:-$HOME/places-report.log}"
PLACES_SINCE="${PLACES_SINCE:-}"
PLACES_KEEP="${PLACES_KEEP:-2}"
RSYNC_TIMEOUT="${RSYNC_TIMEOUT:-300}"
SSH_TIMEOUT="${SSH_TIMEOUT:-10}"
PLACES_NODE="${PLACES_NODE:-node}"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$PLACES_LOG"; }

# One run at a time: a second, started while one is running, leaves.
LOCK="$PLACES_OUT.lock"
if command -v flock >/dev/null 2>&1; then
    exec 9> "$LOCK"
    if ! flock -n 9; then log "another run holds $LOCK; leaving"; exit 0; fi
fi

log "start: server $PLACES_SERVER, gps $PLACES_GPS, nominatim $PLACES_NOMINATIM"

# --- 1. the rig's GPS logs, when the rig is there ---------------------------
mkdir -p "$PLACES_GPS"
if [ -n "$RIG_HOST" ]; then
    SSH="ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT"
    [ -n "$RIG_SSH_KEY" ] && SSH="$SSH -i $RIG_SSH_KEY -o IdentitiesOnly=yes"
    if $SSH "$RIG_HOST" true >> "$PLACES_LOG" 2>&1; then
        if rsync -a --timeout="$RSYNC_TIMEOUT" -e "$SSH" "$RIG_HOST:$RIG_GPSLOG" "$PLACES_GPS/" >> "$PLACES_LOG" 2>&1; then
            log "gps logs copied from the rig"
        else
            log "WARNING: rsync from the rig failed (status $?); building from the logs already here"
        fi
    else
        log "the rig did not answer ssh; building from the logs already here"
    fi
else
    log "RIG_HOST not set; no copy from the rig"
fi

# --- 2. the report, into a new folder ---------------------------------------
BUILDS="$PLACES_OUT.d"
mkdir -p "$BUILDS"
STAMP="$(date '+%Y%m%d-%H%M%S')-$$"
NEW="$BUILDS/$STAMP"
ARGS=("$HERE/places_report.js" "$PLACES_SERVER" --out "$NEW" --gps "$PLACES_GPS" --nominatim "$PLACES_NOMINATIM")
[ -n "$PLACES_SINCE" ] && ARGS+=(--since "$PLACES_SINCE")
if ! "$PLACES_NODE" "${ARGS[@]}" >> "$PLACES_LOG" 2>&1; then
    log "FAILED: the report did not build; the old report is untouched"
    rm -rf "$NEW"
    exit 1
fi
if [ ! -s "$NEW/index.html" ]; then
    log "FAILED: the run wrote no page; the old report is untouched"
    rm -rf "$NEW"
    exit 1
fi

# --- 3. the swap: one rename of a symlink -----------------------------------
if [ -e "$PLACES_OUT" ] && [ ! -L "$PLACES_OUT" ]; then
    # A report folder from before this script: kept as a build, once.
    mv "$PLACES_OUT" "$BUILDS/before-nightly-$STAMP" || { log "FAILED: could not move the old folder aside"; rm -rf "$NEW"; exit 1; }
fi
LINK="$PLACES_OUT.link-$$"
ln -s "$NEW" "$LINK" && mv -T "$LINK" "$PLACES_OUT" || {
    log "FAILED: could not swap the new report in"; rm -f "$LINK"; rm -rf "$NEW"; exit 1; }
log "done: $PLACES_OUT -> $NEW"

# Old builds, the newest PLACES_KEEP beside the live one.
# Newest first by time, so the folder kept from before this script ages out too.
ls -1dt "$BUILDS"/*/ 2>/dev/null | sed 's:/$::' | grep -vxF "$NEW" | tail -n +"$((PLACES_KEEP + 1))" |
    while IFS= read -r old; do rm -rf "$old"; done
exit 0
