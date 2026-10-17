#!/usr/bin/env bash
# Install the Raspberry Pi OS dependencies used by the camera/OCR rig.
#
#   bash rpi/install-deps.sh              # camera + OCR + spoken verdicts
#   bash rpi/install-deps.sh --gps        # plus gpsd for the USB GPS path
#   bash rpi/install-deps.sh --snap       # plus Wayland/X11 screenshot tools
#   bash rpi/install-deps.sh --all        # both optional groups
#   bash rpi/install-deps.sh --check      # install nothing; verify the core rig
#
# Camera-facing packages deliberately come from Raspberry Pi OS, not pip.
# picamera2/libcamera and the distro OpenCV/NumPy stack are built to work
# together; replacing one piece with a generic wheel is not a reproducible Pi
# install even when pip happens to accept it.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$HERE/apt-packages.txt"
GPS="$HERE/apt-packages-gps.txt"
SNAP="$HERE/apt-packages-snap.txt"
PIP_REQ="$HERE/requirements.txt"

want_gps=0
want_snap=0
check_only=0

usage() {
  cat <<'EOF'
usage: bash rpi/install-deps.sh [--gps] [--snap] [--all] [--check]

Installs the Raspberry Pi scanner's documented camera/OCR dependencies.
Optional groups:
  --gps    gpsd + client tools for a USB GPS receiver
  --snap   grim + scrot for the Snap screenshot feature
  --all    both optional groups
  --check  install nothing; verify the selected runtime pieces instead

Node is intentionally not installed here. The scanner itself does not need it,
and replacing an existing Node installed by nvm/NodeSource with the distro
package would be surprising. The web service requires Node 18 or newer.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --gps) want_gps=1 ;;
    --snap) want_snap=1 ;;
    --all) want_gps=1; want_snap=1 ;;
    --check) check_only=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

for f in "$CORE" "$PIP_REQ"; do
  if [ ! -f "$f" ]; then
    echo "missing dependency manifest: $f" >&2
    exit 1
  fi
done

packages_from() {
  # Package manifests are one package per line; comments and whitespace are
  # documentation, not shell. Printing one name per line keeps this usable as
  # an argv source rather than an eval-able command string.
  sed -e 's/[[:space:]]*#.*$//' -e '/^[[:space:]]*$/d' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$1"
}

if [ "$check_only" -eq 1 ]; then
  python3 - <<'PY'
import importlib
import shutil
import sys

missing = []
for module in ('cv2', 'numpy', 'pytesseract', 'picamera2'):
    try:
        importlib.import_module(module)
    except Exception as exc:
        missing.append('%s (%s)' % (module, exc))
for command in ('tesseract', 'espeak-ng'):
    if not shutil.which(command):
        missing.append(command)

if missing:
    print('missing core rig dependencies: ' + '; '.join(missing), file=sys.stderr)
    raise SystemExit(1)
print('core camera/OCR dependencies are available')
PY

  if [ "$want_gps" -eq 1 ]; then
    command -v gpsd >/dev/null || { echo "missing optional GPS dependency: gpsd" >&2; exit 1; }
    command -v gpspipe >/dev/null || { echo "missing optional GPS client tools (gpspipe)" >&2; exit 1; }
    echo "GPS dependencies are available"
  fi

  if [ "$want_snap" -eq 1 ]; then
    # The active desktop decides which one the server uses, so a machine that
    # can boot into either session should have both as the manifest specifies.
    command -v grim >/dev/null || { echo "missing optional Wayland screenshot tool: grim" >&2; exit 1; }
    command -v scrot >/dev/null || { echo "missing optional X11 screenshot tool: scrot" >&2; exit 1; }
    echo "screenshot dependencies are available"
  fi

  if command -v node >/dev/null; then
    major="$(node -p 'Number(process.versions.node.split(".")[0])')"
    if [ "$major" -lt 18 ]; then
      echo "Node $major is installed; the web service requires Node 18 or newer" >&2
      exit 1
    fi
    echo "Node $(node --version) is suitable for the web service"
  else
    echo "note: Node is not installed; only the web server/service needs Node 18+"
  fi
  exit 0
fi

if ! command -v apt-get >/dev/null; then
  echo "apt-get is unavailable; this installer is for Raspberry Pi OS/Debian" >&2
  exit 1
fi
if ! command -v python3 >/dev/null; then
  echo "python3 is unavailable" >&2
  exit 1
fi

apt=( )
while IFS= read -r pkg; do apt+=("$pkg"); done < <(packages_from "$CORE")
if [ "$want_gps" -eq 1 ]; then
  [ -f "$GPS" ] || { echo "missing dependency manifest: $GPS" >&2; exit 1; }
  while IFS= read -r pkg; do apt+=("$pkg"); done < <(packages_from "$GPS")
fi
if [ "$want_snap" -eq 1 ]; then
  [ -f "$SNAP" ] || { echo "missing dependency manifest: $SNAP" >&2; exit 1; }
  while IFS= read -r pkg; do apt+=("$pkg"); done < <(packages_from "$SNAP")
fi

if [ "${#apt[@]}" -eq 0 ]; then
  echo "no apt packages were listed" >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y "${apt[@]}"

# Raspberry Pi OS Bookworm marks the system interpreter externally managed.
# pytesseract is the one project dependency intentionally installed by pip;
# the hardware-facing packages above stay with apt.
python3 -m pip install --break-system-packages -r "$PIP_REQ"

echo
echo "installed the core camera/OCR dependencies"
if [ "$want_gps" -eq 1 ]; then echo "  + gpsd USB-GPS tools"; fi
if [ "$want_snap" -eq 1 ]; then echo "  + Snap screenshot tools"; fi
if command -v node >/dev/null; then
  major="$(node -p 'Number(process.versions.node.split(".")[0])')"
  if [ "$major" -ge 18 ]; then
    echo "Node $(node --version) is already suitable for the web service"
  else
    echo "warning: Node $(node --version) is installed; the web service requires Node 18+" >&2
  fi
else
  echo "note: install Node 18+ separately if this Pi will run server.js / the systemd service"
fi

verify="bash rpi/install-deps.sh --check"
if [ "$want_gps" -eq 1 ]; then verify="$verify --gps"; fi
if [ "$want_snap" -eq 1 ]; then verify="$verify --snap"; fi
echo "verify with: $verify"
