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
#   bash tools/test.sh            everything
#   bash tools/test.sh --quick    skip the two that run tesseract (~2 min)
set -u

cd "$(dirname "$0")/.." || exit 1

# Two tesseract instances fight over a Pi's four cores without this, and one
# paired read then takes 87 seconds instead of 350ms. scan_pi sets it for the
# real rig; the tests need it for the same reason.
export OMP_THREAD_LIMIT=1

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

# The two that render cards and run the OCR engine. Worth the wait — they are
# the only ones that check a picture comes out as the right dollar figure — but
# they are minutes rather than seconds.
SLOW="test_money.py test_scan_pi.py"

pass=0
fail=0
failed_names=""

run() {
    local name="$1" cmd="$2"
    printf '  %-26s ' "$name"
    local out status
    out=$(eval "$cmd" 2>&1)
    status=$?
    local last
    last=$(printf '%s\n' "$out" | grep -E 'passed|FAILED|skipping' | tail -1)
    if [ $status -eq 0 ]; then
        pass=$((pass + 1))
        printf '%s\n' "${last:-ok}"
    else
        fail=$((fail + 1))
        failed_names="$failed_names $name"
        printf 'FAILED\n'
        printf '%s\n' "$out" | grep -E '^FAIL|Error|Traceback' | head -8 | sed 's/^/      /'
    fi
}

echo "python"
for f in rpi/test_*.py; do
    base=$(basename "$f")
    if [ $QUICK -eq 1 ] && printf '%s' "$SLOW" | grep -qw "$base"; then
        printf '  %-26s skipped (--quick)\n' "$base"
        continue
    fi
    run "$base" "python3 '$f'"
done

echo "node"
for f in tests/*.test.js; do
    run "$(basename "$f")" "node '$f'"
done

echo
if [ $fail -eq 0 ]; then
    echo "all $pass suites passed"
    exit 0
fi
echo "$fail of $((pass + fail)) suites FAILED:$failed_names"
exit 1
