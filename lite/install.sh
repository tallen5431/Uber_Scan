#!/usr/bin/env bash
# Install the lite edition on a Raspberry Pi: it boots straight to the offer card.
#
#   sudo bash lite/install.sh                  # verdicts spoken aloud too
#   sudo SPEAK=0 bash lite/install.sh          # the card only, nothing said
#   sudo KIOSK=none bash lite/install.sh       # no browser on this Pi's display
#                                              # (a phone or tablet shows the card)
#   sudo KIOSK=cage bash lite/install.sh       # force the no-desktop kiosk
#
# For a fresh Raspberry Pi OS Bookworm, Lite or with Desktop. Safe to run again:
# every step either installs what is missing or rewrites a file this script
# owns, and the desktop entries it adds are found by a marker and replaced, not
# appended twice. Running it again after `git pull` is how a lite rig updates
# (lite/README.md).
#
# What it does, in order:
#   1. the packages: the camera (python3-picamera2), the picture work
#      (python3-opencv), the reader (tesseract-ocr, pytesseract), the server
#      (nodejs), curl for the kiosk's wait, espeak-ng unless SPEAK=0, and the
#      browser and, on Lite, cage. --no-install-recommends, because
#      picamera2's recommends pull a Qt desktop onto a Lite image and a Zero
#      2 W has 512 MB to hold node, python and tesseract in (lite/README.md).
#   2. the service: rpi/install-service.sh with LITE=1 — the same unit the
#      full rig runs, with one more line. Not a second unit, so a fix to how
#      the rig starts (StartLimitIntervalSec, the autopilot, the audio
#      groups) reaches lite the day it is made.
#   3. the kiosk: lite/kiosk.sh at boot, which waits for the server and opens
#      the card full screen. With a desktop, from its autostart, with
#      autologin turned on and screen blanking off; without one, `cage` (a
#      one-window Wayland compositor) on tty1 from a systemd unit.
#
# Not here yet, and said in lite/README.md as coming: the read-only
# filesystem with a watchdog, and the first-boot setup page behind a QR code.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "run with sudo: sudo bash $0" >&2
  exit 1
fi

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-$(logname 2>/dev/null || echo pi)}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
RUN_HOME="${RUN_HOME:-/home/$RUN_USER}"
SPEAK="${SPEAK:-1}"
KIOSK="${KIOSK:-auto}"
# APT=0 skips the packages, for a re-run with no network (the car's usual
# state) when only the kiosk or the unit needs rewriting.
APT="${APT:-1}"
# The marker the desktop entries carry, so a re-run replaces its own line.
MARK="# uberscan-lite"

case "$KIOSK" in
  auto|desktop|cage|none) : ;;
  *) echo "KIOSK is auto, desktop, cage or none (not '$KIOSK')" >&2; exit 1 ;;
esac

# Desktop or not, judged by what is installed rather than what is running: the
# script is usually run over ssh, where no session is.
has_desktop() {
  command -v labwc >/dev/null 2>&1 || command -v wayfire >/dev/null 2>&1 \
    || command -v startlxde-pi >/dev/null 2>&1 || [ -d /etc/xdg/lxsession ]
}
if [ "$KIOSK" = "auto" ]; then
  if has_desktop; then KIOSK=desktop; else KIOSK=cage; fi
fi

echo "lite edition: installing for $RUN_USER from $PROJECT (kiosk: $KIOSK)"

# --- 1. packages -------------------------------------------------------------
if [ "$APT" = "1" ]; then
  pkgs=(python3-picamera2 python3-opencv python3-numpy tesseract-ocr
        python3-pytesseract nodejs curl)
  [ "$SPEAK" = "1" ] && pkgs+=(espeak-ng)
  [ "$KIOSK" = "cage" ] && pkgs+=(cage)
  apt-get update
  apt-get install -y --no-install-recommends "${pkgs[@]}"
  if [ "$KIOSK" != "none" ]; then
    # The browser's package was renamed after Bookworm; whichever exists.
    apt-get install -y --no-install-recommends chromium-browser \
      || apt-get install -y --no-install-recommends chromium
  fi
  # pytesseract is a Debian package on Bookworm; on an image without it, the
  # route the full rig's README gives.
  if ! python3 -c 'import pytesseract' >/dev/null 2>&1; then
    pip3 install pytesseract --break-system-packages
  fi
fi

# --- 2. the service, as the full rig's, with LITE=1 --------------------------
LITE=1 SPEAK="$SPEAK" SUDO_USER="$RUN_USER" bash "$PROJECT/rpi/install-service.sh"

# --- 3. the kiosk -------------------------------------------------------------
KIOSK_CMD="bash $PROJECT/lite/kiosk.sh"

# A line in a file this script does not own, replaced by its marker.
put_line() {
  local file="$1" line="$2"
  mkdir -p "$(dirname "$file")"
  touch "$file"
  grep -vF "$MARK" "$file" > "$file.lite-tmp" || true
  printf '%s %s\n' "$line" "$MARK" >> "$file.lite-tmp"
  mv "$file.lite-tmp" "$file"
  chown -R "$RUN_USER": "$(dirname "$file")"
}

if [ "$KIOSK" = "desktop" ]; then
  # labwc (Bookworm's desktop since late 2024) runs its own autostart file...
  put_line "$RUN_HOME/.config/labwc/autostart" "$KIOSK_CMD &"
  # ...and the XDG autostart, which the LXDE (X11) and wayfire sessions run
  # too. Both are written; kiosk.sh's lock keeps it to one browser.
  mkdir -p "$RUN_HOME/.config/autostart"
  cat > "$RUN_HOME/.config/autostart/uberscan-lite.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Uber Scan lite card
Comment=The offer card, full screen (lite/kiosk.sh)
Exec=$KIOSK_CMD
X-GNOME-Autostart-enabled=true
DESKTOP
  chown -R "$RUN_USER": "$RUN_HOME/.config/autostart"
  # Log in by itself and never blank: a car has no keyboard to log in with,
  # and a screen that sleeps mid-shift looks exactly like a dead rig.
  if command -v raspi-config >/dev/null 2>&1; then
    raspi-config nonint do_boot_behaviour B4 || true
    raspi-config nonint do_blanking 1 || true
  else
    echo "note: no raspi-config — turn on desktop autologin and turn off screen"
    echo "      blanking yourself, or the card will wait behind a login screen."
  fi
  # A cage unit from an earlier KIOSK=cage run would fight the desktop for tty1.
  if [ -f /etc/systemd/system/uberscan-kiosk.service ]; then
    systemctl disable --now uberscan-kiosk.service || true
    rm -f /etc/systemd/system/uberscan-kiosk.service
    systemctl enable getty@tty1.service || true
  fi
elif [ "$KIOSK" = "cage" ]; then
  # No desktop: cage runs one fullscreen app as the user on tty1, with a
  # login session from PAM so it gets the display and input devices. The
  # pattern cage's own docs give for a kiosk; getty is moved off tty1 for it.
  usermod -aG video,render,input "$RUN_USER" 2>/dev/null || true
  cat > /etc/systemd/system/uberscan-kiosk.service <<UNIT
[Unit]
Description=Uber Scan lite — the offer card on the attached display
After=uberscan.service systemd-user-sessions.service plymouth-quit-wait.service
Wants=uberscan.service
Conflicts=getty@tty1.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=$RUN_USER
PAMName=login
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
StandardInput=tty
UtmpIdentifier=tty1
UtmpMode=user
ExecStart=/usr/bin/cage -s -- $KIOSK_CMD
# The browser is the only thing on the glass: if it dies, start it again.
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl disable getty@tty1.service || true
  systemctl enable uberscan-kiosk.service
  systemctl restart uberscan-kiosk.service || true
  # ...and a desktop entry from an earlier KIOSK=desktop run, gone.
  rm -f "$RUN_HOME/.config/autostart/uberscan-lite.desktop"
fi

cat <<DONE

The lite edition is installed and started, as $RUN_USER, from $PROJECT.

  The card:        http://localhost:8080/   (opens on this Pi's display at boot)
  From a phone:    http://<this-pi>:8080/live.html   for ▣ Set box
                   http://<this-pi>:8080/index.html  for the target and cost per mile
  The log:         journalctl -u uberscan -f

The first start aims and calibrates itself: put the phone in the mount with
an offer or any screen up, and watch the card's bottom line. Reboot once to
see it come up on its own.
DONE
