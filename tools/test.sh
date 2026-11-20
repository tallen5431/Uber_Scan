#!/usr/bin/env bash
# Every check in the repository, in one command.
#
# There was no such command. `npm test` ran the three JavaScript suites and the
# ten Python ones could only be run by knowing to loop over rpi/test_*.py, so
# the 800-odd checks that cover the camera, the reader, the tracker and the
# money were in practice run only by whoever happened to remember them.
#
# Exits non-zero if anything fails, so it is usable from a hook or CI.
#
#   bash tools/test.sh               everything
#   bash tools/test.sh --quick       skip the two that run tesseract (~2 min)
#   TEST_JOBS=1 bash tools/test.sh   one suite at a time, as it always was
#   TEST_JOBS=6 bash tools/test.sh   six at once in the pool (see JOBS below)
set -u

cd "$(dirname "$0")/.." || exit 1

# Two tesseract instances fight over a Pi's four cores without this, and one
# paired read then takes 87 seconds instead of 350ms. scan_pi sets it for the
# real rig; the tests need it for the same reason.
export OMP_THREAD_LIMIT=1

# The clock the rig lives on, unless the caller names another.
#
# Half a dozen suites read the local clock — blockOf buckets by hour, the 4am day
# boundary, every "took 3 for $48" day header — and none of them said which zone
# they wanted. So they answered in whatever zone the machine happened to be in,
# and the machine was UTC while the driver is at UTC-4. Measured the day this was
# added: `TZ=America/New_York node tests/advice.test.js` gave 409 passed and one
# FAILED, on an assertion that wanted UTC's answer to a local-clock question,
# while the same file in the container said all 410 passed. Every "the suite is
# green" statement this project has ever made was made in a zone the rig does not
# run in.
#
# `${TZ:-...}` rather than a bare assignment, so a caller who wants to prove a
# suite is zone-independent can still say so — which is how the one failure above
# was found.
export TZ="${TZ:-America/New_York}"

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

# The two that render cards and run the OCR engine. Worth the wait — they are
# the only ones that check a picture comes out as the right dollar figure — but
# they are minutes rather than seconds.
SLOW="test_money.py test_scan_pi.py"

# How many suites run at once.
#
# The gate took an hour on a four-core machine with the load average under one:
# test_server, test_loop and test_dashboard alone are half of it, and they spend
# it waiting — on a server to answer, a browser to draw, a scanner's clock to run
# out — not computing. One at a time, every one of those waits was the whole
# machine's wait. So by default the suites that only wait run in a pool, as many
# at once as the machine has cores; TEST_JOBS=1 is the old runner exactly, one
# after another in the order below, and TEST_JOBS=N sets the pool's size.
#
# The cores counted without the OMP_THREAD_LIMIT=1 exported above, and without
# a caller's OMP_NUM_THREADS: GNU nproc answers those before the machine, so a
# bare `nproc` here said 1 and the first default run went one at a time.
JOBS="${TEST_JOBS:-$(env -u OMP_THREAD_LIMIT -u OMP_NUM_THREADS nproc 2>/dev/null || echo 1)}"
case "$JOBS" in
    '' | *[!0-9]* | 0)
        echo "TEST_JOBS is how many suites run at once: 1 or more (got '$JOBS')" >&2
        exit 2 ;;
esac

# ...and the suites that never share the machine, even when the pool is on.
# They run first, one after another, before anything else starts.
#
# A suite is here when its verdict depends on having the machine to itself:
#   - the OCR suites, which are CPU-bound and time their reads — test_money,
#     test_tesseract, test_pipeline (a stuck read given up on in under 4 s) and
#     test_scan_pi (closing waits for the read in flight, but under 3.5 s);
#   - a budget on wall time for work this process does: test_cardfind (a look
#     under 100 ms), test_accumulate (an add under 2 ms), test_parser.py and
#     parser.test.js (a 4 kB letter run under 50 ms), test_gps (a quiet session
#     stopped in under 0.5 s), trends.test.js (12,500 offers summed in 3 s);
#   - a suite that reads the whole tree while it runs: test_pi_bench holds
#     every file under the repository to the size and mtime it had before the
#     bench (a worktree made mid-run once failed it), and test_lint reads every
#     source file and lists the root, so a suite writing beside them at the same
#     moment is a failure neither of them caused.
# First rather than last so they get the quiet machine the one-at-a-time runner
# gave them, not one a pool suite might have left a straggler running on.
ALONE="test_accumulate.py test_cardfind.py test_gps.py test_lint.py test_money.py
       test_parser.py test_pipeline.py test_scan_pi.py test_tesseract.py
       test_pi_bench.py parser.test.js trends.test.js"

# The pool starts its longest suites first: the pool is done when its last
# suite is, so test_server begun last would be a quarter of an hour run alone at
# the end. Seconds measured on this machine, one at a time, are in AUDITS.md;
# a suite not named here starts after these, in the order below.
LONGEST="test_server.py test_loop.py test_dashboard.py test_layout.py
         test_offerspage.py test_map.py test_scanjs.py test_keypad.py
         test_stacking.py test_lite.py"

# The suites, in the order they have always been run, and are printed in.
names=()
cmds=()
for f in rpi/test_*.py; do
    names+=("$(basename "$f")"); cmds+=("python3 '$f'")
done
# ...and the tools' own, which live beside what they test. gpslog_tidy.py
# deletes files on the rig, unattended, from Start.sh; shift_report.py reads
# the journal and the GPS logs after a shift and must never print a place.
for f in tools/test_*.py; do
    names+=("$(basename "$f")"); cmds+=("python3 '$f'")
done
for f in tests/*.test.js; do
    names+=("$(basename "$f")"); cmds+=("node '$f'")
done

named() { printf ' %s ' $2 | grep -qF " $1 "; }

# Under /tmp itself when there is one, not under a caller's long TMPDIR: each
# suite's temporary directory is made inside this one, and a browser puts a
# socket in it, whose whole path has to fit in 108 bytes.
RUNDIR=$(mktemp -d /tmp/uberscan-test.XXXXXX 2>/dev/null || mktemp -d) || exit 1
trap 'rm -rf "$RUNDIR"' EXIT

# Stopped part way, it stops everything it started, not only its own subshells.
# A Ctrl-C reaches every process in the terminal's group and needs none of
# this; a SIGTERM — a `timeout`, a hook giving up — reaches this shell alone.
# Measured with four suites that each start a child and sleep: `kill` of the
# jobs ended the four subshells and left all four suites and their four
# children running, with nobody to read them. Gathered whole before any is
# killed, since a killed parent hands its children to init, where they can no
# longer be found by asking for its children. And a suite run one at a time is
# still started with `&` and waited for, because bash holds a trap until a
# foreground command ends, and test_scan_pi is four minutes of foreground.
tree() { local c; for c in $(pgrep -P "$1"); do echo "$c"; tree "$c"; done; }
trap 'kill $(tree $$) 2>/dev/null; exit 130' INT TERM

# One suite, its output kept whole in $RUNDIR/<name>.out and its exit status and
# seconds in <name>.done, written last so its being there means "finished".
#
# Each suite gets a handoff directory of its own (handoff.ENV_DIR). Only
# test_server and test_stacking named one; every other suite that starts a
# scanner or a server, or calls the request readers, read and wrote the
# machine's shared /dev/shm files — each other's, and a real rig's on the same
# machine. test_handoff is the exception: it is the suite that checks the
# default rule itself (/dev/shm, the uberscan- names), and sets the variable
# where it needs one.
#
# ...and a temporary directory of its own (TMPDIR, which Python's tempfile,
# Node's os.tmpdir() and the browsers all follow), for the same reason once
# suites share the machine: test_server holds that a gold screenshot leaves no
# uberscan-gold-* file in the temporary folder, which another suite's server
# could have written in the same second, and test_pipeline writes a frame
# under one fixed name there. Removed after, with whatever the suite left.
#
# And each suite's seconds, because "the gate takes an hour and a half" was
# known only as a total: which suites spend it was measured by hand each time
# anybody asked.
run_suite() {
    local name="$1" cmd="$2" dir="$RUNDIR/$1" began=$SECONDS status
    mkdir -p "$dir/tmp"
    (
        export TMPDIR="$dir/tmp"
        if [ "$name" != "test_handoff.py" ]; then
            mkdir -p "$dir/handoff"
            export UBERSCAN_HANDOFF_DIR="$dir/handoff"
        fi
        eval "$cmd"
    ) > "$dir.out" 2>&1 < /dev/null
    status=$?
    rm -rf "$dir"
    printf '%s %s\n' "$status" "$((SECONDS - began))" > "$dir.part"
    mv "$dir.part" "$dir.done"
}

pass=0
fail=0
failed_names=""
# Every suite started, and the ones that left no result. The verdict below is
# over what was SCHEDULED, not over what got printed: a runner killed with -9
# (the OOM killer, a stray kill) writes no .done, and the printer used to stop
# at it for good, so every suite after it went unsaid and the count covered
# only what came before. Measured on stub suites: one runner killed, "all 1
# suites passed", exit 0.
scheduled=0
missing_names=""

# A finished suite's line: its seconds and its last word, or FAILED and the
# lines that say why; or, with no .done, that it left no result.
report() {
    local name="$1" out="$RUNDIR/$1.out" status took last
    if ! read -r status took < "$RUNDIR/$name.done" 2>/dev/null; then
        missing_names="$missing_names $name"
        printf '%5s  NO RESULT (its runner ended without writing one)\n' '-'
        return
    fi
    last=$(grep -E 'passed|FAILED|skipping' "$out" | tail -1)
    if [ "$status" -eq 0 ]; then
        pass=$((pass + 1))
        printf '%5ds  %s\n' "$took" "${last:-ok}"
    else
        fail=$((fail + 1))
        failed_names="$failed_names $name"
        printf '%5ds  FAILED\n' "$took"
        grep -E '^FAIL|Error|Traceback' "$out" | head -8 | sed 's/^/      /'
    fi
}

skipped() {
    if [ $QUICK -eq 1 ] && named "$1" "$SLOW"; then
        printf '  %-26s skipped (--quick)\n' "$1"
        return 0
    fi
    return 1
}

began_all=$SECONDS

if [ "$JOBS" -eq 1 ]; then
    section=""
    for i in "${!names[@]}"; do
        name="${names[$i]}"
        case "$name" in *.js) here=node ;; *) here=python ;; esac
        if [ "$here" != "$section" ]; then echo "$here"; section="$here"; fi
        skipped "$name" && continue
        scheduled=$((scheduled + 1))
        printf '  %-26s ' "$name"
        run_suite "$name" "${cmds[$i]}" & wait $!
        report "$name"
    done
else
    echo "alone, one at a time"
    pool=()
    for i in "${!names[@]}"; do
        name="${names[$i]}"
        skipped "$name" && continue
        scheduled=$((scheduled + 1))
        if ! named "$name" "$ALONE"; then pool+=("$i"); continue; fi
        printf '  %-26s ' "$name"
        run_suite "$name" "${cmds[$i]}" & wait $!
        report "$name"
    done

    echo "together, up to $JOBS at once"
    order=()
    for long in $LONGEST; do
        for i in "${pool[@]}"; do
            [ "${names[$i]}" = "$long" ] && order+=("$i")
        done
    done
    for i in "${pool[@]}"; do
        named "${names[$i]}" "$LONGEST" || order+=("$i")
    done

    # Printed in the order above, not the order they finish in, so two runs'
    # output can be read side by side: a suite's line waits for every suite
    # before it, and comes out whole the moment they are all done.
    # `flush all`, once every runner has ended, waits for nothing: a suite
    # with no .done by then never will have one, and is said as such and
    # passed over, so it cannot hold up the suites after it.
    next=0
    flush() {
        while [ $next -lt ${#pool[@]} ] \
              && { [ "${1:-}" = all ] || [ -e "$RUNDIR/${names[${pool[$next]}]}.done" ]; }; do
            printf '  %-26s ' "${names[${pool[$next]}]}"
            report "${names[${pool[$next]}]}"
            next=$((next + 1))
        done
    }
    for i in "${order[@]}"; do
        while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; flush; done
        run_suite "${names[$i]}" "${cmds[$i]}" &
    done
    while [ "$(jobs -rp | wc -l)" -gt 0 ]; do wait -n; flush; done
    wait
    flush all
fi

echo
echo "took $((SECONDS - began_all))s, $JOBS at once"
if [ $((pass + fail)) -lt $scheduled ]; then
    echo "$((scheduled - pass - fail)) of $scheduled suites gave no result:${missing_names:- (unnamed)}"
    [ $fail -gt 0 ] && echo "$fail FAILED:$failed_names"
    exit 1
fi
if [ $fail -eq 0 ]; then
    echo "all $pass suites passed"
    exit 0
fi
echo "$fail of $((pass + fail)) suites FAILED:$failed_names"
exit 1
