#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
# Installs Huntsman for Mac:
#   - "Huntsman for Mac.app" in ~/Applications, carrying its own copy of the code and Python environment
#     (so it never reads from Downloads/Documents/Desktop, which macOS blocks for unsigned apps)
#   - "Huntsman Lighting.app" inside it (Contents/Library/LoginItems), the background lighting service: menu bar
#     icon, Lighting Studio, typing and sound reactions. macOS shows its permission prompts as "Huntsman Lighting".
#   - a LaunchAgent (io.github.huntsman-for-mac.lighting) that starts the service at login and now, and restarts
#     it if it crashes (not after "Quit lighting service"). At start it re-sends per-key colours, Rapid Trigger
#     and Snap Tap, and runs Lighting Studio if it was on. It replaces the old apply-saved login item.
# Run it again after updating the code. Remove everything with ./uninstall.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/Huntsman for Mac.app"
RES="$APP/Contents/Resources"
CODE="$RES/code"
PYBIN="$RES/venv/bin/python"
LOG="$HOME/Library/Logs/Huntsman for Mac.log"
LIGHT="$APP/Contents/Library/LoginItems/Huntsman Lighting.app"
LABEL="io.github.huntsman-for-mac.lighting"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
OLD_AGENT="$HOME/Library/LaunchAgents/io.github.huntsman-for-mac.apply-saved.plist"

say() { printf '%s\n' "$*"; }
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || fail "this only runs on macOS."

# xml TEXT: TEXT escaped for an XML (plist) string
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g' -e "s/'/\&apos;/g"; }

if pgrep -u "$(id -u)" -f "Contents/Resources/code/app.py" >/dev/null 2>&1; then
  fail "Huntsman for Mac is running. Quit it (Cmd-Q), then run ./install.sh again."
fi

# Newest tested Python first (3.13 down to 3.11), then whatever python3 is. 3.11 is the oldest the pinned
# packages support (pyobjc 13).
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$(command -v "$c")"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.11 or newer is needed. Install it with: brew install python (or from python.org)"
if "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)'; then
  say "Note: $("$PY" --version) is newer than the versions this was tested with (3.11 to 3.13). It will probably work."
fi

if [ ! -e /opt/homebrew/lib/libusb-1.0.dylib ] && [ ! -e /usr/local/lib/libusb-1.0.dylib ]; then
  command -v brew >/dev/null 2>&1 || fail "libusb is needed. Install Homebrew (https://brew.sh), then run: brew install libusb"
  say "Installing libusb with Homebrew"
  brew install libusb
fi

# Stop the lighting service (it runs from the bundle about to be replaced; launchd restores the keyboard's lighting
# through its SIGTERM handler) and remove the old apply-saved login item from earlier versions.
STOPPED=0
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  say "Stopping the lighting service"
  launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  STOPPED=1
fi
launchctl bootout "gui/$(id -u)" "$OLD_AGENT" 2>/dev/null || true
/bin/rm -f "$OLD_AGENT"

say "Building $APP"
# Build a fresh bundle (so renamed or deleted files never linger) at its final path, because the venv
# records absolute paths. The previous app is moved aside first and put back if the build fails.
mkdir -p "$HOME/Applications"
OLD=""
BUILT=0
finish() {
  if [ -n "$OLD" ] && [ "$BUILT" != 1 ]; then
    /bin/rm -rf "$APP"
    mv "$OLD/Huntsman for Mac.app" "$APP" && rmdir "$OLD"
    printf 'The install failed; the previous app was put back.\n' >&2
  fi
  if [ "$BUILT" != 1 ] && [ "$STOPPED" = 1 ] && [ -f "$AGENT" ]; then
    launchctl bootstrap "gui/$(id -u)" "$AGENT" 2>/dev/null || true   # the previous service again
  fi
}
trap finish EXIT
if [ -d "$APP" ]; then
  STASH="$(mktemp -d "$HOME/Applications/.huntsman-for-mac-previous.XXXXXX")"
  mv "$APP" "$STASH/"
  OLD="$STASH"   # only now is there something to put back
fi
mkdir -p "$APP/Contents/MacOS" "$CODE/ui"
cp "$DIR"/huntsman_core.py "$DIR"/depth_stream.py "$DIR"/app.py "$DIR"/studio.py "$DIR"/menubar.py "$DIR"/huntsman.py \
   "$DIR"/service.py "$DIR"/ipc.py "$DIR"/models.py \
   "$DIR"/layout.json "$DIR"/keymap.json "$CODE/"
# whole packages, without bytecode caches (they would break the signature)
rsync -a --exclude '__pycache__' --exclude '*.pyc' "$DIR/lighting" "$DIR/inputs" "$DIR/layouts" "$CODE/"
cp "$DIR"/ui/index.html "$DIR"/ui/style.css "$DIR"/ui/app.js "$DIR"/ui/studio.js "$CODE/ui/"
cp "$DIR/packaging/Info.plist" "$APP/Contents/Info.plist"
cp "$DIR/packaging/icon.icns" "$RES/icon.icns"

say "Setting up Python ($PY)"
"$PY" -m venv --copies "$RES/venv"   # copies, not symlinks out of the bundle, so it can be signed
"$RES/venv/bin/pip" install --quiet --upgrade pip
"$RES/venv/bin/pip" install --quiet -r "$DIR/requirements.txt"

# printf %q quotes each path for the shell, whatever characters the home folder name has.
# -B: no __pycache__ inside the signed bundle.
{ printf '#!/bin/bash\nexec '; printf '%q ' "$PYBIN" -I -B "$CODE/app.py"; printf '"$@" >>%q 2>&1\n' "$LOG"; } > "$APP/Contents/MacOS/HuntsmanForMac"
chmod +x "$APP/Contents/MacOS/HuntsmanForMac"

# The lighting service's own small bundle (menu bar agent, its own name in permission prompts), running the
# outer bundle's Python and code. launchd writes its output to the log (see the agent below).
mkdir -p "$LIGHT/Contents/MacOS" "$LIGHT/Contents/Resources"
cp "$DIR/packaging/Lighting-Info.plist" "$LIGHT/Contents/Info.plist"
cp "$DIR/packaging/icon.icns" "$LIGHT/Contents/Resources/icon.icns"
{ printf '#!/bin/bash\nexec '; printf '%q ' "$PYBIN" -I -B "$CODE/service.py"; printf '"$@"\n'; } > "$LIGHT/Contents/MacOS/HuntsmanLighting"
chmod +x "$LIGHT/Contents/MacOS/HuntsmanLighting"
touch "$LIGHT" "$APP"

# Files copied from a downloaded zip can carry the quarantine flag; Gatekeeper would then refuse the app.
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
# An ad-hoc signature (no developer account) keeps macOS from treating the bundle as damaged on Apple silicon.
if ! command -v codesign >/dev/null 2>&1; then
  say "Warning: codesign wasn't found, so the app is left unsigned. If macOS refuses to open it, see Troubleshooting in README.md."
elif ! { codesign --force --deep -s - "$APP" && codesign --verify --deep --strict "$APP"; } >/dev/null 2>&1; then
  say "Warning: couldn't sign the app ad hoc. It should still open; if macOS refuses, see Troubleshooting in README.md."
fi

BUILT=1
if [ -n "$OLD" ]; then /bin/rm -rf "$OLD"; OLD=""; fi

say "Starting the lighting service (and at every login)"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$(xml "$LIGHT/Contents/MacOS/HuntsmanLighting")</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>ProcessType</key><string>Interactive</string>
  <key>StandardOutPath</key><string>$(xml "$LOG")</string>
  <key>StandardErrorPath</key><string>$(xml "$LOG")</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
STARTED=0
for _ in 1 2 3; do   # right after a bootout launchd may still be unloading the old job
  if launchctl bootstrap "gui/$(id -u)" "$AGENT" 2>/dev/null; then STARTED=1; break; fi
  sleep 1
done
[ "$STARTED" = 1 ] || say "Couldn't start the lighting service now; it starts at the next login."

say ""
say "Done. Opening \"Huntsman for Mac\" (later: ~/Applications or Spotlight). Lighting keeps running after you quit it;"
say "quit the lighting service from its menu bar icon (Quit lighting service)."
open "$APP" || say "Couldn't open it automatically; open \"Huntsman for Mac\" from ~/Applications."
say "The key tester needs Input Monitoring for Huntsman for Mac; typing reactions need it for Huntsman Lighting,"
say "and sound-reactive lighting needs Microphone for Huntsman Lighting."
say "macOS asks the first time you use them."
