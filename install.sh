#!/bin/bash
# Installs Huntsman for Mac:
#   - "Huntsman for Mac.app" in ~/Applications, carrying its own copy of the code and Python environment
#     (so it never reads from Downloads/Documents/Desktop, which macOS blocks for unsigned apps)
#   - a login item that re-sends per-key colours, Rapid Trigger and Snap Tap after login
# Run it again after updating the code. Remove everything with ./uninstall.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/Huntsman for Mac.app"
RES="$APP/Contents/Resources"
CODE="$RES/code"
PYBIN="$RES/venv/bin/python"
LOG="$HOME/Library/Logs/Huntsman for Mac.log"
AGENT="$HOME/Library/LaunchAgents/io.github.huntsman-for-mac.apply-saved.plist"

say() { printf '%s\n' "$*"; }
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || fail "this only runs on macOS."

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PY="$(command -v "$c")"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.10 or newer is needed. Install it with: brew install python"

if [ ! -e /opt/homebrew/lib/libusb-1.0.dylib ] && [ ! -e /usr/local/lib/libusb-1.0.dylib ]; then
  command -v brew >/dev/null 2>&1 || fail "libusb is needed. Install Homebrew (https://brew.sh), then run: brew install libusb"
  say "Installing libusb with Homebrew"
  brew install libusb
fi

say "Building $APP"
[ -d "$CODE" ] && /bin/rm -r "$CODE"   # fresh copy, so renamed or deleted files never linger
mkdir -p "$APP/Contents/MacOS" "$CODE/ui"
cp "$DIR"/huntsman_core.py "$DIR"/depth_stream.py "$DIR"/app.py "$DIR"/huntsman.py "$DIR"/layout.json "$DIR"/keymap.json "$CODE/"
cp "$DIR"/ui/index.html "$DIR"/ui/style.css "$DIR"/ui/app.js "$CODE/ui/"
cp "$DIR/packaging/Info.plist" "$APP/Contents/Info.plist"
cp "$DIR/packaging/icon.icns" "$RES/icon.icns"

say "Setting up Python ($PY)"
"$PY" -m venv --clear "$RES/venv"
"$RES/venv/bin/pip" install --quiet --upgrade pip
"$RES/venv/bin/pip" install --quiet -r "$DIR/requirements.txt"

printf '#!/bin/bash\nexec "%s" -I "%s/app.py" >>"%s" 2>&1\n' "$PYBIN" "$CODE" "$LOG" > "$APP/Contents/MacOS/HuntsmanForMac"
chmod +x "$APP/Contents/MacOS/HuntsmanForMac"
touch "$APP"

say "Adding the login item"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.github.huntsman-for-mac.apply-saved</string>
  <key>ProgramArguments</key><array>
    <string>$PYBIN</string><string>-I</string><string>$CODE/huntsman.py</string><string>apply-saved</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT" || say "Note: the login item starts working after you log out and back in."

say ""
say "Done. Open \"Huntsman for Mac\" from ~/Applications or Spotlight."
say "The key tester needs Input Monitoring permission; macOS asks the first time you use it."
