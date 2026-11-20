#!/usr/bin/env bash
# The checkout brought up to date by itself, at night, or left exactly as it was.
#
#   bash tools/autoupdate.sh               (from uberscan-update.timer; see
#                                           tools/install-autoupdate.sh)
#   bash tools/autoupdate.sh --dry-run     every check and the fetch, then says
#                                          what it would do; changes nothing
#   bash tools/autoupdate.sh --status      the last outcome, in words
#
# Until this, every change reached the rig and the NucBox only when the owner
# remembered to `git pull` and restart each by hand (the owner's standing rule,
# CLAUDE.md "Hands free": a timer over a step somebody has to remember, and
# anything automatic fails safe). So this does that pull, and every way it can
# go wrong ends in one of four words, written to rpi/update-status.json and to
# the journal (journalctl -u uberscan-update):
#
#   updated      fetched BRANCH, fast-forwarded, restarted, and the server
#                answered as the new code
#   current      nothing new on BRANCH
#   skipped      and why: a shift (an order held, an offer or a reading in the
#                last QUIET_MIN minutes, the car moving), a server that did not
#                answer, local changes, a branch that cannot fast-forward, the
#                lock held, a dependency change, a commit rolled back before
#   rolled back  the new code did not answer (or its scanner fell over): the
#                checkout reset to the exact commit it was at, restarted again
#
# What it never does: stash, reset, clean or check out anything but a rollback
# of its own merge; install a package; switch branches; touch the phone. A tree
# with local changes is skipped and said, never tidied.
#
# When it runs is the timer's. The NucBox's is nightly: 04:20 plus up to ten
# minutes, just after the 4am driver-day turn and well clear of
# places_nightly.sh at 05:17, whose lock it also takes. The rig's is hourly,
# because a Pi in a car is off at 04:20 nearly every night: it takes its
# chance whenever it has been powered, quiet and still for the window — parked
# with the engine running, on a charger at home — inside UPDATE_HOURS, at most
# once a driver day. Each hour that is not such a time is a skip like any
# other; the two that are only the clock (outside UPDATE_HOURS, already updated
# today) go to the journal alone and leave the status file saying what last
# happened, rather than "not now" twenty-three times a day.
#
# SETTINGS, from the environment or from a file of KEY=value lines (default
# /etc/uberscan/autoupdate.env, which tools/install-autoupdate.sh writes, or
# AUTOUPDATE_ENV). The environment wins over the file.
#   ROLE            rig (default) or nucbox. The rig is asked whether a shift is
#                   on and restarts uberscan.service; the NucBox has no scanner,
#                   so it is asked only whether it answers, and runs RESTART_CMD
#   ENABLED         1 (default); 0 records "skipped: turned off" and does nothing
#   BRANCH          the branch followed, default main (the gated one); the
#                   checkout must already be on it. Only this branch is fetched
#   REMOTE          default origin
#   PORT            the server's port: 8080 on the rig, 8082 on the NucBox
#   RESTART_CMD     run with bash -c after the merge (and after a rollback). On
#                   the rig, unset: systemctl restart uberscan.service, and
#                   uberscan-kiosk.service too where lite/install.sh made one.
#                   On the NucBox it is required: the manager's own command
#   QUIET_MIN       minutes with no offer or reading before it counts as no
#                   shift (default 90). An hour is not enough: a driver online
#                   can wait longer than that between offers, phone in the
#                   mount and car parked. The server must also have been up
#                   that long, since it forgets every age across a restart
#   UPDATE_HOURS    the rig's hours it may update in, local clock, a list of
#                   hours and inclusive ranges that may wrap midnight (default
#                   22-10,14-16: everything but the lunch rush, 11:00-13:59,
#                   and the dinner rush, 17:00-21:59). Empty: any hour. Not
#                   asked on the NucBox, whose timer is its window
#   DAILY_CAP       1 (the rig's default): after an update, none until the next
#                   4am driver-day turn, so a rig on all afternoon restarts once
#                   in it, not every hour a new commit lands. NucBox default 0
#   BOOT_QUIET_MIN  on the rig, minutes since boot before it may act (default
#                   30): a Pi switched on is a shift starting, and its clock
#                   may only just have been set
#   HEALTH_TIMEOUT  seconds the server has to answer after a restart (default 90)
#   HEALTH_SETTLE   seconds it then has to stay up, its scanner too (rig 20,
#                   NucBox 0)
#   FETCH_TIMEOUT   seconds for the fetch (default 120)
#   VERIFY_SIGNED   1: take a new commit only when `git verify-commit` passes on
#                   it (needs git's signature checking set up for this account);
#                   default 0
#   LOCK            the lock file, default .git/uberscan-update.lock; on the
#                   NucBox the installer points it at places_nightly.sh's
#   STATUS_FILE     default rpi/update-status.json (gitignored, never committed);
#                   the server reads it there, or at its own UPDATE_STATUS
#   REPO            the checkout, default the one this script is in
#   SYNC_UNIT       the rig's sync, skipped round (default uberscan-sync.service)
#   SYSTEMCTL       default systemctl (the tests point it at a stand-in)
#   AUTOUPDATE_NOW  epoch seconds taken as now by the hour and the day gates
#                   and the status file's time (the tests' clock); environment
#                   only

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KEYS=" ROLE ENABLED BRANCH REMOTE PORT RESTART_CMD QUIET_MIN UPDATE_HOURS DAILY_CAP BOOT_QUIET_MIN HEALTH_TIMEOUT HEALTH_SETTLE FETCH_TIMEOUT VERIFY_SIGNED LOCK STATUS_FILE REPO SYNC_UNIT SYSTEMCTL "

load_env() {
    local file="${AUTOUPDATE_ENV:-/etc/uberscan/autoupdate.env}" line key val
    [ -f "$file" ] || return 0
    # KEY=value lines only, one level of quotes taken off; the environment
    # wins. One reader for the file, rather than systemd's EnvironmentFile=
    # beside this one: the two disagree about quotes and backslashes, and
    # RESTART_CMD is a command line full of both.
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in ''|'#'*) continue ;; esac
        key="${line%%=*}"
        val="${line#*=}"
        case "$KEYS" in *" $key "*) ;; *) continue ;; esac
        case "$val" in
            \"*\") val="${val#\"}"; val="${val%\"}" ;;
            \'*\') val="${val#\'}"; val="${val%\'}" ;;
        esac
        if [ -z "${!key+x}" ]; then
            export "$key=$val"
        fi
    done < "$file"
}

num() { case "$1" in ''|*[!0-9]*) echo "$2" ;; *) echo "$1" ;; esac; }

settings() {
    load_env
    REPO="${REPO:-$(cd "$HERE/.." && pwd)}"
    ROLE="${ROLE:-rig}"
    case "$ROLE" in rig|nucbox) ;; *) echo "autoupdate: ROLE is rig or nucbox (not '$ROLE')" >&2; exit 2 ;; esac
    ENABLED="${ENABLED:-1}"
    BRANCH="${BRANCH:-main}"
    REMOTE="${REMOTE:-origin}"
    if [ "$ROLE" = rig ]; then
        PORT="$(num "${PORT:-}" 8080)"
        BOOT_QUIET_MIN="$(num "${BOOT_QUIET_MIN:-}" 30)"
        HEALTH_SETTLE="$(num "${HEALTH_SETTLE:-}" 20)"
        UPDATE_HOURS="${UPDATE_HOURS-22-10,14-16}"
        DAILY_CAP="${DAILY_CAP:-1}"
    else
        PORT="$(num "${PORT:-}" 8082)"
        BOOT_QUIET_MIN="$(num "${BOOT_QUIET_MIN:-}" 0)"
        HEALTH_SETTLE="$(num "${HEALTH_SETTLE:-}" 0)"
        UPDATE_HOURS=""
        DAILY_CAP="${DAILY_CAP:-0}"
    fi
    NOW="$(num "${AUTOUPDATE_NOW:-}" "$(date +%s)")"
    RESTART_CMD="${RESTART_CMD:-}"
    QUIET_MIN="$(num "${QUIET_MIN:-}" 90)"
    HEALTH_TIMEOUT="$(num "${HEALTH_TIMEOUT:-}" 90)"
    FETCH_TIMEOUT="$(num "${FETCH_TIMEOUT:-}" 120)"
    VERIFY_SIGNED="${VERIFY_SIGNED:-0}"
    LOCK="${LOCK:-$REPO/.git/uberscan-update.lock}"
    STATUS_FILE="${STATUS_FILE:-$REPO/rpi/update-status.json}"
    SYNC_UNIT="${SYNC_UNIT-uberscan-sync.service}"
    SYSTEMCTL="${SYSTEMCTL:-systemctl}"
    BASE="http://127.0.0.1:$PORT"
    # git, and every file this writes in the checkout, as the account that owns
    # the checkout. The rig's unit runs as root, because restarting
    # uberscan.service needs it; a git run as root would leave root-owned
    # objects in .git and a status file the server cannot replace, and the
    # next `git pull` by hand would fail on permissions.
    OWNER="$(stat -c '%U' "$REPO" 2>/dev/null || echo root)"
}

say() { printf 'autoupdate: %s\n' "$*"; }

# Every child is started with the lock's descriptor closed (9>&-). A child
# that outlives this script — a server RESTART_CMD starts in the background, a
# `git gc --auto` that detaches — would otherwise hold the lock for as long as
# it runs, and the nightly report would find it held every night after.
as_owner() {
    if [ "$(id -u)" = 0 ] && [ "$OWNER" != root ]; then
        runuser -u "$OWNER" -- "$@" 9>&-
    else
        "$@" 9>&-
    fi
}

# No prompt ever: a timer has nobody to type a password, and a fetch waiting
# on one would hold the lock until FETCH_TIMEOUT.
g() { as_owner env GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false git -C "$REPO" "$@"; }

short() { printf '%s' "${1:0:7}"; }

# The status file: one JSON object, written whole through a temporary and a
# rename, so the server never reads half of one. The rollback's refused commit
# and the last real update are carried over from the file before, so a night
# of "current" does not forget either.
record() {
    local outcome="$1" why="$2" from="${3:-}" to="${4:-}" note="${5:-}" refused="${6:-}"
    say "$outcome${why:+: $why}${from:+ ($(short "$from")${to:+ -> $(short "$to")})}${note:+; $note}"
    [ "$DRY" = 1 ] && return 0
    as_owner mkdir -p "$(dirname "$STATUS_FILE")" 2>/dev/null
    OUTCOME="$outcome" WHY="$why" FROM="$from" TO="$to" NOTE="$note" REFUSED="$refused" \
    BRANCH="$BRANCH" ROLE="$ROLE" COUNT="${COUNT:-}" NOW_S="$NOW" \
    as_owner python3 - "$STATUS_FILE" <<'PY' || say "could not write the status file"
import json, os, sys, time
path = sys.argv[1]
e = os.environ
try:
    with open(path, encoding='utf-8') as f:
        before = json.load(f)
    if not isinstance(before, dict):
        before = {}
except (OSError, ValueError):
    before = {}
now = float(e['NOW_S'])
out = {
    'at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)),
    'atMs': int(now * 1000),
    'outcome': e['OUTCOME'],
    'why': e['WHY'] or None,
    'from': e['FROM'] or None,
    'to': e['TO'] or None,
    'branch': e['BRANCH'],
    'role': e['ROLE'],
    'note': e['NOTE'] or None,
}
# A few words for /api/status, the outcome first.
words = e['OUTCOME']
if e['OUTCOME'] == 'updated' and e['FROM'] and e['TO']:
    n = e.get('COUNT') or ''
    words = 'updated %s to %s' % (e['FROM'][:7], e['TO'][:7]) + (' (%s commits)' % n if n and n != '1' else '')
elif e['WHY']:
    words = '%s: %s' % (e['OUTCOME'], e['WHY'])
out['words'] = words[:120]
# The commit a rollback refused, until a newer one arrives on the branch.
refused = e['REFUSED'] or (before.get('refused') if e['OUTCOME'] != 'updated' else None)
out['refused'] = refused or None
if e['REFUSED']:
    out['refusedAt'] = out['at']
elif refused:
    out['refusedAt'] = before.get('refusedAt')
if e['OUTCOME'] == 'updated':
    out['lastUpdate'] = {'at': out['at'], 'atMs': out['atMs'], 'from': out['from'], 'to': out['to']}
elif isinstance(before.get('lastUpdate'), dict):
    out['lastUpdate'] = before['lastUpdate']
tmp = '%s.%d.part' % (path, os.getpid())
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(out, f, indent=1)
    f.write('\n')
os.chmod(tmp, 0o644)
os.replace(tmp, path)
PY
}

# GET a path of the local server, the body on stdout; non-zero when it did
# not answer 2xx inside the time given.
ask() { curl -fsS -m "${2:-10}" "$BASE$1" 2>/dev/null; }

# Is a shift on? The rig's own answers, read the way they are meant to be:
# ages rather than timestamps (statusNow's rule), and the journal's newest
# offer against this machine's own clock, which both came from. Prints
# "busy <why>" or "idle", then "scanner 1|0" (whether a scanner was running,
# which the health check later holds the new code to).
judge() {
    STATUS_JSON="$1" NEWEST_JSON="$2" QUIET_MS="$((QUIET_MIN * 60000))" python3 - <<'PY'
import json, os, time
e = os.environ
quiet = int(e['QUIET_MS'])
try:
    st = json.loads(e['STATUS_JSON'])
except ValueError:
    st = None
if not isinstance(st, dict):
    print('busy its status was not JSON')
    print('scanner 0')
    raise SystemExit
def mins(ms):
    return '%d min ago' % max(0, round(ms / 60000.0))
def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
why = None
sc = st.get('scanner') if isinstance(st.get('scanner'), dict) else {}
beat = st.get('beat') if isinstance(st.get('beat'), dict) else {}
gps = beat.get('gps') if isinstance(beat.get('gps'), dict) else {}
fix = gps.get('fix') if isinstance(gps.get('fix'), dict) else {}
if st.get('holding'):
    why = 'an order is held'
elif num(st.get('offerAgeMs')) is not None and st['offerAgeMs'] < quiet:
    why = 'an offer ' + mins(st['offerAgeMs'])
elif num(st.get('lastAgeMs')) is not None and st['lastAgeMs'] < quiet:
    why = 'a reading ' + mins(st['lastAgeMs'])
elif fix.get('driving') is True and (num(beat.get('ageMs')) or 0) < 5 * 60000:
    why = 'the car is moving'
elif num(st.get('upMs')) is not None and st['upMs'] < quiet:
    # The ages above are this process's memory: one up for less than the
    # window cannot say there was no reading in it. A rig booted for a shift
    # with no offer yet would otherwise look quiet.
    why = 'the server has been up only ' + mins(st['upMs']).replace(' ago', '') \
        + ', too short to vouch for the quiet window'
else:
    # The journal's newest offer: what offerAgeMs cannot say across a
    # restart of the server, which forgets it.
    try:
        nw = json.loads(e.get('NEWEST_JSON') or 'null')
    except ValueError:
        nw = None
    if isinstance(nw, dict) and num(nw.get('newest')):
        age = time.time() * 1000 - nw['newest']
        if -5 * 60000 < age < quiet:
            why = 'an offer in the journal ' + mins(age)
print('busy ' + why if why else 'idle')
print('scanner %d' % (1 if sc.get('enabled') and sc.get('running') else 0))
PY
}

# One look at the server after a restart: "ok", or why not. SINCE is when the
# restart was asked for (epoch seconds); MIN_UP the seconds the process must
# have been up (the settle's "it did not fall over meanwhile").
look() {
    local body
    body="$(ask /api/status 5)" || { echo "no answer"; return; }
    BODY="$body" SINCE="$1" MIN_UP="$2" WANT_SCANNER="$3" python3 - <<'PY'
import json, os, time
e = os.environ
try:
    st = json.loads(e['BODY'])
except ValueError:
    st = None
if not isinstance(st, dict):
    print('an answer that was not its status')
    raise SystemExit
up = st.get('upMs')
if isinstance(up, (int, float)):
    # The process answering must be one started by the restart: an old one
    # still answering while a slow manager gets round to it is not the new
    # code saying it is healthy.
    if up / 1000.0 > time.time() - float(e['SINCE']) + 5:
        print('the old process still answering')
        raise SystemExit
    if up / 1000.0 < float(e['MIN_UP']) - 1:
        print('the server restarted itself during the check')
        raise SystemExit
if e['WANT_SCANNER'] == '1':
    sc = st.get('scanner') if isinstance(st.get('scanner'), dict) else {}
    if (sc.get('fell') or 0) > 0 or not sc.get('running'):
        print('the scanner fell over after the restart')
        raise SystemExit
print('ok')
PY
}

# Healthy after a restart: answers as a new process within HEALTH_TIMEOUT,
# and after HEALTH_SETTLE more seconds is the same process, with its scanner
# up if one was up before. Prints why not, on failure.
healthy() {
    local since="$1" want_scanner="$2" deadline said
    deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
    while :; do
        said="$(look "$since" 0 0)"
        [ "$said" = ok ] && break
        if [ "$(date +%s)" -ge "$deadline" ]; then
            echo "$said after ${HEALTH_TIMEOUT}s"
            return 1
        fi
        sleep 2
    done
    if [ "$HEALTH_SETTLE" -gt 0 ] || [ "$want_scanner" = 1 ]; then
        sleep "$HEALTH_SETTLE"
        said="$(look "$since" "$HEALTH_SETTLE" "$want_scanner")"
        if [ "$said" != ok ]; then
            echo "$said"
            return 1
        fi
    fi
    return 0
}

restart() {
    if [ -n "$RESTART_CMD" ]; then
        bash -c "$RESTART_CMD" 9>&-
        return
    fi
    "$SYSTEMCTL" restart uberscan.service 9>&- || return
    # The lite kiosk (lite/install.sh, KIOSK=cage) holds a browser on the
    # card; restarted with the server so it opens on the new page.
    if "$SYSTEMCTL" is-enabled --quiet uberscan-kiosk.service 2>/dev/null; then
        "$SYSTEMCTL" restart uberscan-kiosk.service 9>&- || true
    fi
}

# A change the merge would bring that an update must not take by itself:
# packages to install. Prints the reason, or nothing.
needs_hands() {
    local from="$1" to="$2" files f
    files="$(g diff --name-only "$from" "$to")"
    while IFS= read -r f; do
        case "$f" in
            requirements*.txt|*/requirements*.txt|pyproject.toml|*/pyproject.toml|Pipfile|Pipfile.lock|setup.py|setup.cfg|package-lock.json|npm-shrinkwrap.json)
                echo "requirements changed ($f)"; return ;;
        esac
    done <<< "$files"
    # package.json carries no dependencies today (the server is zero-install);
    # the day it does, they are an `npm install`, which is a person's.
    if grep -qx 'package.json' <<< "$files"; then
        if [ "$(deps_of "$from" package.json)" != "$(deps_of "$to" package.json)" ]; then
            echo "requirements changed (package.json's dependencies)"; return
        fi
    fi
    # lite/install.sh's package list is the rig's requirements file in all but
    # name (lite/README.md: re-running it after a pull is how a lite rig
    # updates): a package added there is one the new code may need.
    if [ "$ROLE" = rig ] && grep -qx 'lite/install.sh' <<< "$files"; then
        if [ "$(pkgs_of "$from")" != "$(pkgs_of "$to")" ]; then
            echo "requirements changed (lite/install.sh's packages)"; return
        fi
    fi
}

deps_of() {
    g show "$1:$2" 2>/dev/null | python3 -c '
import json, sys
try:
    p = json.load(sys.stdin)
except ValueError:
    p = {}
print(json.dumps({k: p.get(k) for k in ("dependencies", "optionalDependencies", "peerDependencies")}, sort_keys=True))
' 2>/dev/null
}

pkgs_of() {
    g show "$1:lite/install.sh" 2>/dev/null \
        | grep -E 'pkgs(\+)?=|^[[:space:]]+python3-|apt-get install|pip3? install' || true
}

uptime_min() {
    local up
    up="$(cut -d. -f1 /proc/uptime 2>/dev/null)"
    echo $(( $(num "$up" 999999) / 60 ))
}

# Is HOUR (0-23) inside SPEC ("22-10,14-16": hours and inclusive ranges, a
# range may wrap midnight)? Prints yes, no, or bad for a spec it cannot read,
# which the caller takes as a skip: a gate nobody can read is not open.
in_hours() {
    local spec="$1" h="$2" part a b found=no
    local -a parts
    IFS=, read -r -a parts <<< "$spec"
    [ "${#parts[@]}" -gt 0 ] || { echo bad; return; }
    for part in "${parts[@]}"; do
        part="${part// /}"
        case "$part" in
            *-*) a="${part%-*}"; b="${part#*-}" ;;
            *) a="$part"; b="$part" ;;
        esac
        case "$a$b" in ''|*[!0-9]*) echo bad; return ;; esac
        a=$((10#$a)); b=$((10#$b))
        if [ "$a" -gt 23 ] || [ "$b" -gt 23 ]; then echo bad; return; fi
        if [ "$a" -le "$b" ]; then
            [ "$h" -ge "$a" ] && [ "$h" -le "$b" ] && found=yes
        else
            { [ "$h" -ge "$a" ] || [ "$h" -le "$b" ]; } && found=yes
        fi
    done
    echo "$found"
}

# The time of the last update when it was in the current driver day, or
# nothing. The day turns at 4am by the clock, as advice.js dayKeyOf turns it
# (clock time, not four hours of real time, so a clock change does not move
# the boundary): 03:50 belongs to the day before.
updated_today() {
    NOW_S="$NOW" python3 - "$STATUS_FILE" <<'PY' 2>/dev/null
import datetime, json, os, sys
try:
    lu = json.load(open(sys.argv[1], encoding='utf-8')).get('lastUpdate') or {}
except (OSError, ValueError, AttributeError):
    lu = {}
at = lu.get('atMs') if isinstance(lu, dict) else None
if isinstance(at, (int, float)) and not isinstance(at, bool):
    def day(t):
        d = datetime.datetime.fromtimestamp(t)
        return d.date() - datetime.timedelta(days=1) if d.hour < 4 else d.date()
    if day(at / 1000.0) == day(float(os.environ['NOW_S'])):
        print(datetime.datetime.fromtimestamp(at / 1000.0).strftime('%H:%M'))
PY
}

show_status() {
    local file="${STATUS_FILE}"
    if [ ! -f "$file" ]; then
        echo "no update has run yet ($file is not there)"
        return 0
    fi
    python3 - "$file" <<'PY'
import json, sys
s = json.load(open(sys.argv[1], encoding='utf-8'))
print('%s  %s' % (s.get('at'), s.get('words') or s.get('outcome')))
if s.get('note'):
    print('note: ' + s['note'])
if s.get('refused'):
    print('refused (rolled back): %s, %s' % (s['refused'][:7], s.get('refusedAt')))
lu = s.get('lastUpdate')
if isinstance(lu, dict):
    print('last updated %s: %s -> %s' % (lu.get('at'), (lu.get('from') or '')[:7], (lu.get('to') or '')[:7]))
PY
}

main() {
    DRY=0
    case "${1:-}" in
        --dry-run) DRY=1 ;;
        --status) settings; show_status; return ;;
        -h|--help) sed -n '2,12p' "$0"; return 0 ;;
        '') ;;
        *) echo "usage: bash tools/autoupdate.sh [--dry-run|--status]" >&2; return 2 ;;
    esac
    settings

    if [ "$ENABLED" != 1 ]; then
        record skipped "turned off (ENABLED=$ENABLED)"
        return 0
    fi
    local tool
    for tool in curl python3 flock timeout git; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            record skipped "no $tool on this machine"
            return 1
        fi
    done

    # --- the clock's two gates, the rig's hourly runs. Said in the journal
    # only: the status file keeps what last happened.
    if [ -n "$UPDATE_HOURS" ]; then
        local hour
        hour="$(date -d "@$NOW" +%H)"
        case "$(in_hours "$UPDATE_HOURS" "$((10#$hour))")" in
            yes) ;;
            no) say "skipped: $hour:00 is outside UPDATE_HOURS ($UPDATE_HOURS)"; return 0 ;;
            *) record skipped "UPDATE_HOURS is not understood ('$UPDATE_HOURS'): hours 0-23, ranges like 22-10, commas between"
               return 0 ;;
        esac
    fi
    if [ "$DAILY_CAP" = 1 ]; then
        local today
        today="$(updated_today)"
        if [ -n "$today" ]; then
            say "skipped: already updated this driver day (at $today); the next after the 4am turn"
            return 0
        fi
    fi

    # --- the lock: one of us at a time, and never beside the nightly report.
    # Opened to append, as places_nightly.sh opens it, and never touched: that
    # script reads the lock's mtime to tell a wedged run from a running one.
    # Made by the owner when it is not there, so a root-made lock cannot shut
    # the owner's cron job out of its own file.
    [ -e "$LOCK" ] || as_owner touch "$LOCK" 2>/dev/null
    if ! exec 9>> "$LOCK"; then
        record skipped "cannot open the lock ($LOCK)"
        return 1
    fi
    if ! flock -n 9; then
        record skipped "the lock is held (an update, a sync or the nightly report is running)"
        return 0
    fi

    if [ "$ROLE" = rig ]; then
        if [ -n "$SYNC_UNIT" ] \
           && [ "$("$SYSTEMCTL" show -p ActiveState --value "$SYNC_UNIT" 2>/dev/null)" = activating ]; then
            record skipped "a sync is running"
            return 0
        fi
        local up
        up="$(uptime_min)"
        if [ "$up" -lt "$BOOT_QUIET_MIN" ]; then
            record skipped "booted $up min ago (a shift starting, not ending)"
            return 0
        fi
    fi

    # --- the checkout: on BRANCH, with nothing of anybody's in it.
    if ! g rev-parse --git-dir >/dev/null 2>&1; then
        record skipped "$REPO is not a git checkout"
        return 1
    fi
    local on from to count
    on="$(g symbolic-ref --quiet --short HEAD 2>/dev/null)"
    if [ "$on" != "$BRANCH" ]; then
        record skipped "the checkout is on ${on:-a detached HEAD}, not $BRANCH (check it out once by hand, or set BRANCH)"
        return 0
    fi
    # Tracked changes, staged or not. Untracked files are not counted: the
    # rig writes its own (all gitignored), and an untracked file the merge
    # would overwrite makes git refuse the fast-forward, which is said below.
    if [ -n "$(g status --porcelain --untracked-files=no 2>/dev/null)" ] \
       || ! g diff --quiet HEAD -- 2>/dev/null; then
        record skipped "local changes in the checkout (nothing touched; commit or undo them by hand)"
        return 0
    fi

    # --- a shift? Asked of the server itself. Unanswered on the rig is the
    # cautious side: a rig whose server is down at 4am is in no state to be
    # updated, and a server that cannot say "no shift" has not said it.
    local status newest verdict scanner_was
    if ! status="$(ask /api/status 10)"; then
        record skipped "the server on port $PORT did not answer"
        return 0
    fi
    scanner_was=0
    if [ "$ROLE" = rig ]; then
        newest="$(ask /api/journal/newest 30 || true)"
        verdict="$(judge "$status" "$newest")"
        case "$verdict" in
            busy*) record skipped "a shift: $(sed -n '1s/^busy //p' <<< "$verdict")"; return 0 ;;
            # Only a plain "idle" is no shift. A judge that could not run
            # (no python3, say) said nothing, and silence is not an answer.
            idle*) ;;
            *) record skipped "could not tell whether a shift is on"; return 0 ;;
        esac
        grep -qx 'scanner 1' <<< "$verdict" && scanner_was=1
    fi

    # --- what is new on BRANCH. Only that branch is fetched.
    if ! fetch_branch; then
        record skipped "could not fetch $BRANCH from $REMOTE ($FETCH_FAILED)"
        return 0
    fi
    from="$(g rev-parse HEAD)"
    to="$(g rev-parse --verify --quiet "refs/remotes/$REMOTE/$BRANCH")"
    if [ -z "$to" ]; then
        record skipped "no $REMOTE/$BRANCH after the fetch" "$from"
        return 0
    fi
    if [ "$from" = "$to" ]; then
        record current "" "$from"
        return 0
    fi
    if ! g merge-base --is-ancestor "$from" "$to"; then
        if g merge-base --is-ancestor "$to" "$from"; then
            record skipped "the checkout is ahead of $REMOTE/$BRANCH: nothing to take" "$from" "$to"
        else
            record skipped "$BRANCH has diverged from $REMOTE/$BRANCH: cannot fast-forward" "$from" "$to"
        fi
        return 0
    fi
    local refused
    refused="$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("refused") or "")
except Exception: print("")' "$STATUS_FILE" 2>/dev/null)"
    if [ -n "$refused" ] && [ "$refused" = "$to" ]; then
        record skipped "$(short "$to") was rolled back before; waiting for a newer commit" "$from" "$to"
        return 0
    fi
    local hands
    hands="$(needs_hands "$from" "$to")"
    if [ -n "$hands" ]; then
        record skipped "needs a manual update: $hands" "$from" "$to"
        return 0
    fi
    if [ "$VERIFY_SIGNED" = 1 ] && ! g verify-commit "$to" >/dev/null 2>&1; then
        record skipped "$(short "$to") is not signed by a key this account trusts (VERIFY_SIGNED=1)" "$from" "$to"
        return 0
    fi
    count="$(g rev-list --count "$from..$to")"
    COUNT="$count"
    if [ "$DRY" = 1 ]; then
        say "would update $(short "$from") -> $(short "$to") ($count commit(s)) and restart; nothing changed (--dry-run)"
        return 0
    fi

    # A note, not a skip: the units the installers write are not rewritten by
    # a pull, and a changed installer is the owner's to re-run when convenient.
    local note="" changed
    changed="$(g diff --name-only "$from" "$to")"
    for f in rpi/install-service.sh lite/install.sh tools/install-sync.sh tools/install-autoupdate.sh; do
        if grep -qx "$f" <<< "$changed"; then
            note="${note:+$note, }$f changed (re-run it by hand to rewrite its unit)"
        fi
    done

    # --- the update itself.
    local said
    if ! said="$(g merge --ff-only --quiet "$to" 2>&1)"; then
        # A refused fast-forward moves nothing (git checks before it writes),
        # so there is nothing of ours to undo, and nothing else is ours to.
        record skipped "the fast-forward was refused: $(head -n 1 <<< "$said")" "$from" "$to"
        return 0
    fi
    local since why
    since="$(date +%s)"
    if ! restart > /dev/null 2>&1; then
        why="the restart command failed"
    elif ! why="$(healthy "$since" "$scanner_was")"; then
        :
    else
        record updated "" "$from" "$to" "$note"
        return 0
    fi

    # --- the rollback: its own merge and nothing else, to the exact commit.
    g reset --quiet --hard "$from"
    since="$(date +%s)"
    local after=""
    if ! restart > /dev/null 2>&1; then
        after="; the restart after the rollback failed too"
    elif ! after="$(healthy "$since" 0)"; then
        after="; and after the rollback: $after"
    else
        after=""
    fi
    record "rolled back" "$why$after" "$from" "$to" "$note" "$to"
    return 3
}

# BRANCH alone, under FETCH_TIMEOUT, saying why it failed in FETCH_FAILED.
fetch_branch() {
    local rc
    as_owner env GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false SSH_ASKPASS=/bin/false \
        timeout "$FETCH_TIMEOUT" git -C "$REPO" fetch --quiet --no-tags "$REMOTE" \
        "+refs/heads/$BRANCH:refs/remotes/$REMOTE/$BRANCH" >/dev/null 2>&1 < /dev/null
    rc=$?
    case "$rc" in
        0) return 0 ;;
        124) FETCH_FAILED="no answer in ${FETCH_TIMEOUT}s" ;;
        *) FETCH_FAILED="git said no: the network, the credentials, or no such branch" ;;
    esac
    return 1
}

# All of the above is read before any of it runs, and nothing after this line
# is: the merge rewrites this very file, and bash reads a script as it goes.
main "$@"; exit $?
