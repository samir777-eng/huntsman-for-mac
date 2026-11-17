#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
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

# xml TEXT: TEXT escaped for an XML (plist) string
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g' -e "s/'/\&apos;/g"; }

if pgrep -u "$(id -u)" -f "Contents/Resources/code/app.py" >/dev/null 2>&1; then
  fail "Huntsman for Mac is running. Quit it first (Cmd-Q), then run ./install.sh again."
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
}
trap finish EXIT
if [ -d "$APP" ]; then
  STASH="$(mktemp -d "$HOME/Applications/.huntsman-for-mac-previous.XXXXXX")"
  mv "$APP" "$STASH/"
  OLD="$STASH"   # only now is there something to put back
fi
mkdir -p "$APP/Contents/MacOS" "$CODE/ui"
cp "$DIR"/huntsman_core.py "$DIR"/depth_stream.py "$DIR"/app.py "$DIR"/huntsman.py "$DIR"/layout.json "$DIR"/keymap.json "$CODE/"
cp "$DIR"/ui/index.html "$DIR"/ui/style.css "$DIR"/ui/app.js "$CODE/ui/"
cp "$DIR/packaging/Info.plist" "$APP/Contents/Info.plist"
cp "$DIR/packaging/icon.icns" "$RES/icon.icns"

say "Setting up Python ($PY)"
"$PY" -m venv --copies "$RES/venv"   # copies, not symlinks out of the bundle, so it can be signed
"$RES/venv/bin/pip" install --quiet --upgrade pip
"$RES/venv/bin/pip" install --quiet -r "$DIR/requirements.txt"

# printf %q quotes each path for the shell, whatever characters the home folder name has.
# -B: no __pycache__ inside the signed bundle.
{ printf '#!/bin/bash\nexec '; printf '%q ' "$PYBIN" -I -B "$CODE/app.py"; printf '>>%q 2>&1\n' "$LOG"; } > "$APP/Contents/MacOS/HuntsmanForMac"
chmod +x "$APP/Contents/MacOS/HuntsmanForMac"
touch "$APP"

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

say "Adding the login item"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>io.github.huntsman-for-mac.apply-saved</string>
  <key>ProgramArguments</key><array>
    <string>$(xml "$PYBIN")</string><string>-I</string><string>-B</string><string>$(xml "$CODE/huntsman.py")</string><string>apply-saved</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$(xml "$LOG")</string>
  <key>StandardErrorPath</key><string>$(xml "$LOG")</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT" || say "Note: the login item starts working after you log out and back in."

say ""
say "Done. Open \"Huntsman for Mac\" from ~/Applications or Spotlight."
say "The key tester needs Input Monitoring permission; macOS asks the first time you use it."
