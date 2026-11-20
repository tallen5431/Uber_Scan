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
# 2b. Before the swap, the diagnostics: tools/report_check.js against the same
#    server and tools/twin_ids.py against the copy's journal, their output
#    (counts only: both are held to printing no place, id or payout) kept as
#    checks.txt and checks.html in the new build, which the report's header
#    links to. So the double-filed cards' breakdown is there every morning
#    without anybody running anything. Either failing is said on the page and
#    in the log and never fails the night: the report is the job, these ride
#    along.
#
# SETTINGS, from the environment or from a file of KEY=value lines (default
# ~/.config/uber-scan/places.env, or PLACES_ENV). The file holds this NucBox's
# own values — the rig's address among them — and is never committed.
#   RIG_HOST          ssh destination of the rig, e.g. pi@<rig-address>; unset: no copy;
#                     one starting with '-' is refused (ssh would read an option)
#   RIG_GPSLOG        the logs on the rig (default: gpslog/, under its home); a
#                     trailing slash is added, so the folder's logs land in
#                     PLACES_GPS itself, never in PLACES_GPS/gpslog/
#   RIG_SSH_KEY       a key file for ssh to the rig (default: ssh's own); one
#                     with no passphrase, since cron has nobody to type it
#   RIG_URL           the rig's own server, e.g. http://<rig-address>:8080; when
#                     set AND it answers, passed as --waits, so the report has
#                     the rig's store waits (the NucBox's copy of the journal
#                     carries none); unset: no waits from the rig
#   PLACES_SERVER     the server to read (default http://localhost:8082)
#   PLACES_RELAY      a server whose NucBox relay (search, router, street index)
#                     the report asks, passed as --relay (default: PLACES_SERVER's)
#   PLACES_NOMINATIM  the NucBox's Nominatim (default http://localhost:8088)
#   PLACES_GPS        the NucBox's GPS logs (default ~/gpslog)
#   PLACES_OUT        the report the server serves (default ~/places-report)
#   PLACES_LOG        this script's log (default ~/places-report.log)
#   PLACES_SINCE      YYYY-MM-DD, passed as --since (default: none)
#   PLACES_KEEP       builds kept beside the live one (default 2)
#   RSYNC_TIMEOUT     seconds (default 300); SSH_TIMEOUT seconds (default 10)
#   PLACES_NODE       the node to run (default node)
#   PLACES_TIMEOUT    seconds the report may run (default 10800, three hours):
#                     past it the run is stopped and fails, the old report kept.
#                     A lock older than this with its run still holding it is a
#                     wedged run, and the next night says so and exits non-zero
#   PLACES_CHECKS     1 (default): run the diagnostics (2b); 0: not
#   PLACES_JOURNAL    the journal twin_ids reads: the copy's file, the one the
#                     NucBox's server was given as JOURNAL (default: the
#                     checkout's rpi/journal.jsonl, the server's own default)
#   PLACES_PYTHON     the python to run (default python3)
#   CHECKS_TIMEOUT    seconds each diagnostic may run (default 900)
#
# The lock below is also tools/autoupdate.sh's on the NucBox (its installer
# points LOCK here), so a night's update can never restart the server or move
# the checkout under a report being built from them.
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
            RIG_HOST|RIG_GPSLOG|RIG_SSH_KEY|RIG_URL|PLACES_SERVER|PLACES_RELAY|PLACES_NOMINATIM|PLACES_GPS|PLACES_OUT|PLACES_LOG|PLACES_SINCE|PLACES_KEEP|RSYNC_TIMEOUT|SSH_TIMEOUT|PLACES_NODE|PLACES_TIMEOUT|PLACES_CHECKS|PLACES_JOURNAL|PLACES_PYTHON|CHECKS_TIMEOUT) ;;
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
RIG_GPSLOG="${RIG_GPSLOG%/}/"
RIG_SSH_KEY="${RIG_SSH_KEY:-}"
RIG_URL="${RIG_URL:-}"
PLACES_SERVER="${PLACES_SERVER:-http://localhost:8082}"
PLACES_RELAY="${PLACES_RELAY:-}"
PLACES_NOMINATIM="${PLACES_NOMINATIM:-http://localhost:8088}"
PLACES_GPS="${PLACES_GPS:-$HOME/gpslog}"
PLACES_OUT="${PLACES_OUT:-$HOME/places-report}"
PLACES_LOG="${PLACES_LOG:-$HOME/places-report.log}"
PLACES_SINCE="${PLACES_SINCE:-}"
PLACES_KEEP="${PLACES_KEEP:-2}"
RSYNC_TIMEOUT="${RSYNC_TIMEOUT:-300}"
SSH_TIMEOUT="${SSH_TIMEOUT:-10}"
PLACES_NODE="${PLACES_NODE:-node}"
PLACES_TIMEOUT="${PLACES_TIMEOUT:-10800}"
case "$PLACES_TIMEOUT" in ''|*[!0-9]*) PLACES_TIMEOUT=10800 ;; esac
PLACES_CHECKS="${PLACES_CHECKS:-1}"
PLACES_JOURNAL="${PLACES_JOURNAL:-$(dirname "$HERE")/rpi/journal.jsonl}"
PLACES_PYTHON="${PLACES_PYTHON:-python3}"
CHECKS_TIMEOUT="${CHECKS_TIMEOUT:-900}"
case "$CHECKS_TIMEOUT" in ''|*[!0-9]*) CHECKS_TIMEOUT=900 ;; esac

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$PLACES_LOG"; }

# One run at a time: a second, started while one is running, leaves. Opened
# to append, so a run that only looks does not touch it; the run that takes it
# stamps it, and a lock held past PLACES_TIMEOUT is a run wedged in something
# the timeout below does not cover: said, and non-zero, every night it stands
# (it used to say "another run holds" and exit 0 for ever).
LOCK="$PLACES_OUT.lock"
if command -v flock >/dev/null 2>&1; then
    exec 9>> "$LOCK"
    if ! flock -n 9; then
        held=$(( $(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || date +%s) ))
        if [ "$held" -gt "$PLACES_TIMEOUT" ]; then
            log "FAILED: a run has held $LOCK for ${held}s, past PLACES_TIMEOUT (${PLACES_TIMEOUT}s): it is stuck; the old report is untouched"
            exit 2
        fi
        log "another run holds $LOCK; leaving"
        exit 0
    fi
    touch "$LOCK"
fi

log "start: server $PLACES_SERVER, gps $PLACES_GPS, nominatim $PLACES_NOMINATIM"

# --- 1. the rig's GPS logs, when the rig is there ---------------------------
mkdir -p "$PLACES_GPS"
if [ "${RIG_HOST#-}" != "$RIG_HOST" ]; then
    log "WARNING: RIG_HOST starts with '-', which ssh would read as an option; no copy from the rig"
elif [ -n "$RIG_HOST" ]; then
    # An array, so a key path with a space is one word; rsync takes its ssh
    # as one string, each word quoted for it (printf %q).
    SSH=(ssh -o BatchMode=yes -o ConnectTimeout="$SSH_TIMEOUT")
    [ -n "$RIG_SSH_KEY" ] && SSH+=(-i "$RIG_SSH_KEY" -o IdentitiesOnly=yes)
    RSH="$(printf '%q ' "${SSH[@]}")"
    RSH="${RSH% }"
    if "${SSH[@]}" "$RIG_HOST" true >> "$PLACES_LOG" 2>&1; then
        if rsync -a --timeout="$RSYNC_TIMEOUT" -e "$RSH" "$RIG_HOST:$RIG_GPSLOG" "$PLACES_GPS/" >> "$PLACES_LOG" 2>&1; then
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
[ -n "$PLACES_RELAY" ] && ARGS+=(--relay "$PLACES_RELAY")
[ "$PLACES_CHECKS" = 1 ] && ARGS+=(--checks checks.html)
# The rig's store waits, when RIG_URL is set and the rig answers (a rig off or
# away is the ordinary case: the report is built without them).
if [ -n "$RIG_URL" ]; then
    if curl -fsS -m "$SSH_TIMEOUT" -o /dev/null "${RIG_URL%/}/api/journal?days=1&limit=1" >> "$PLACES_LOG" 2>&1; then
        ARGS+=(--waits "$RIG_URL")
        log "store waits from the rig ($RIG_URL)"
    else
        log "the rig's server did not answer; no store waits from it"
    fi
else
    log "RIG_URL not set; no store waits from the rig"
fi
# Under a time limit (PLACES_TIMEOUT): a run wedged on a server that stopped
# answering would hold the lock, and every night after it, for ever.
LIMIT=()
if command -v timeout >/dev/null 2>&1; then
    LIMIT=(timeout -k 60 "$PLACES_TIMEOUT")
else
    log "WARNING: no timeout command; the report runs with no time limit"
fi
# Stdin from /dev/null, never the terminal. The owner's run of 7 Nov, by hand
# from an ssh session: the report wrote its page ("Written: …/index.html") and
# then node itself aborted while exiting — node::ResetStdio()'s assertion, the
# Node 18 teardown restoring a terminal's settings and failing — so `timeout`
# said "dumped core", the status was not 0, and the finished build below was
# thrown away with the old report left up. The report never reads stdin; with
# no terminal on it there is nothing for node to restore at exit.
${LIMIT[@]+"${LIMIT[@]}"} "$PLACES_NODE" "${ARGS[@]}" < /dev/null >> "$PLACES_LOG" 2>&1
status=$?
if [ "$status" -ne 0 ]; then
    if [ "${#LIMIT[@]}" -gt 0 ] && { [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; }; then
        log "FAILED: the report ran past PLACES_TIMEOUT (${PLACES_TIMEOUT}s) and was stopped; the old report is untouched"
    else
        log "FAILED: the report did not build (status $status); the old report is untouched"
    fi
    rm -rf "$NEW"
    exit 1
fi
if [ ! -s "$NEW/index.html" ]; then
    log "FAILED: the run wrote no page; the old report is untouched"
    rm -rf "$NEW"
    exit 1
fi

# --- 2b. the diagnostics, beside the new page --------------------------------
# One tool's output into checks.txt under a heading, or why it gave none. Its
# stdout only: stderr, which may name the server's address or the journal's
# path, goes to the log, never onto a page the server hands out.
one_check() {
    local title="$1" rc
    shift
    printf '== %s\n' "$title" >> "$NEW/checks.txt"
    ${CHECK_LIMIT[@]+"${CHECK_LIMIT[@]}"} "$@" < /dev/null >> "$NEW/checks.txt" 2>> "$PLACES_LOG"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        printf '(it did not finish cleanly: status %s; places-report.log says why)\n' "$rc" >> "$NEW/checks.txt"
        log "WARNING: $title did not finish cleanly (status $rc); the report is built regardless"
    fi
    printf '\n' >> "$NEW/checks.txt"
}
if [ "$PLACES_CHECKS" = 1 ]; then
    CHECK_LIMIT=()
    command -v timeout >/dev/null 2>&1 && CHECK_LIMIT=(timeout -k 30 "$CHECKS_TIMEOUT")
    {
        printf 'Nightly checks, %s\n' "$(date '+%Y-%m-%d %H:%M')"
        printf 'Counts only: no place, id or payout. From tools/places_nightly.sh.\n\n'
    } > "$NEW/checks.txt" 2>> "$PLACES_LOG"
    one_check "report_check: the reports against the journal" \
        "$PLACES_NODE" "$HERE/report_check.js" "$PLACES_SERVER"
    one_check "twin_ids: why one card was filed under two ids" \
        "$PLACES_PYTHON" "$HERE/twin_ids.py" "$PLACES_JOURNAL"
    # The same, as a page beside index.html (the server serves .html and .csv
    # from the report folder, and nothing else). Escaped as text.
    {
        printf '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
        printf '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        printf '<title>Nightly checks</title>\n'
        printf '<style>body{font:14px/1.45 system-ui,sans-serif;margin:16px;color:#222;background:#fff}'
        printf 'pre{white-space:pre-wrap;font:13px/1.4 ui-monospace,monospace}'
        printf '@media (prefers-color-scheme: dark){body{color:#ddd;background:#111}a{color:#8cf}}</style>\n'
        printf '</head><body>\n<p><a href="index.html">&larr; the report</a></p>\n<pre>'
        sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' "$NEW/checks.txt"
        printf '</pre>\n</body></html>\n'
    } > "$NEW/checks.html" 2>> "$PLACES_LOG" || log "WARNING: could not write checks.html"
    log "checks written beside the report"
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
