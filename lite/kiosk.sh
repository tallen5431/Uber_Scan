#!/usr/bin/env bash
# Open the lite card full screen on the attached display, once the server is up.
#
#   bash lite/kiosk.sh                      # what the kiosk entries run
#   URL=http://localhost:8080/ bash lite/kiosk.sh
#
# Started by lite/install.sh's kiosk entry: the desktop's autostart on Raspberry
# Pi OS with a desktop, or `cage` from a systemd unit on Raspberry Pi OS Lite.
# Both run this rather than chromium directly, for one reason each:
#
#   - the browser must not open before the server answers. The kiosk and the
#     service start together at boot, node takes a few seconds on a Pi, and a
#     browser that loaded first shows "This site can't be reached" for good —
#     it does not retry, and there is no keyboard in the car to press F5 with.
#     So the server is asked (/api/lite, which answers in either mode) until it
#     does, for up to WAIT seconds, and the browser is opened either way after
#     that, so a broken server still shows its error on the glass.
#   - the browser's name differs by release: `chromium-browser` on Bookworm,
#     `chromium` after it. Found here, once, rather than in two kiosk entries.
#
# The flags: --kiosk is full screen with no way out but the keyboard; the rest
# keep a cold boot from putting a prompt over the card — no "restore pages?"
# after a power cut (the car's normal way of shutting down), no first-run
# page, no keyring dialog, no translate bar, no update nag. --incognito so a
# power cut never leaves a profile Chromium thinks crashed.

set -u

URL="${URL:-http://localhost:8080/}"
WAIT="${WAIT:-120}"

# One card at a time. lite/install.sh writes the desktop's autostart in both
# forms Raspberry Pi OS has used (labwc's own file and the XDG one its sessions
# also run), because which one a given image honours has changed between
# releases — and a session that runs both would otherwise open two browsers,
# one over the other. The second start finds the lock held and leaves.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/uberscan-lite-kiosk.lock"
if command -v flock >/dev/null 2>&1 && ! flock -n 9; then
  exit 0
fi

BROWSER=""
for b in chromium-browser chromium; do
  if command -v "$b" >/dev/null 2>&1; then BROWSER="$b"; break; fi
done
if [ -z "$BROWSER" ]; then
  echo "no chromium on this machine — run lite/install.sh again" >&2
  exit 1
fi

# The server answers /api/lite in either mode; anything at all back is "up".
probe="${URL%/}/api/lite"
i=0
while [ "$i" -lt "$WAIT" ]; do
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -m 2 "$probe" >/dev/null 2>&1 && break
  else
    # No curl (a trimmed image): bash's own /dev/tcp, to the port in the URL.
    hostport="${URL#*://}"; hostport="${hostport%%/*}"
    host="${hostport%%:*}"; port="${hostport##*:}"
    [ "$port" = "$hostport" ] && port=80
    (exec 3<>"/dev/tcp/$host/$port") 2>/dev/null && break
  fi
  sleep 1
  i=$((i + 1))
done

exec "$BROWSER" --kiosk --incognito --noerrdialogs --disable-infobars \
  --no-first-run --disable-session-crashed-bubble --password-store=basic \
  --disable-translate --disable-features=Translate \
  --check-for-update-interval=31536000 --autoplay-policy=no-user-gesture-required \
  "$URL"
