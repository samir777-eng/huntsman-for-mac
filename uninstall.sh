#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
# Removes the app (which holds its own code, Python environment and the Huntsman Lighting service app) and the
# lighting service's login item (plus the apply-saved login item of earlier versions). The installer's copy in
# /Applications (the .pkg; the app's own Keyboard > Uninstall… does the same) is removed too, with sudo.
# Settings, presets and typing counts in ~/Library/Application Support/Huntsman for Mac and the log are
# kept unless you pass --all.
# Stopping the lighting service puts the keyboard's own lighting back; nothing else on the keyboard changes.
# Use "Restore factory depth" in the app first if you want that.
set -euo pipefail
LABEL="io.github.huntsman-for-mac.lighting"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
OLD_AGENT="$HOME/Library/LaunchAgents/io.github.huntsman-for-mac.apply-saved.plist"
APP="$HOME/Applications/Huntsman for Mac.app"
PKG_APP="/Applications/Huntsman for Mac.app"
DATA="$HOME/Library/Application Support/Huntsman for Mac"
LOG="$HOME/Library/Logs/Huntsman for Mac.log"

if pgrep -u "$(id -u)" -f "Contents/Resources/code/app.py" >/dev/null 2>&1 \
   || pgrep -u "$(id -u)" -x HuntsmanForMac >/dev/null 2>&1; then
  echo "Error: Huntsman for Mac is running. Quit it first (Cmd-Q), then run ./uninstall.sh again." >&2
  exit 1
fi

# The service restores the keyboard's lighting when launchd stops it (SIGTERM).
launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootout "gui/$(id -u)" "$OLD_AGENT" 2>/dev/null || true
/bin/rm -f "$AGENT" "$OLD_AGENT"
if [ -d "$APP" ]; then /bin/rm -r "$APP"; fi
if [ -d "$PKG_APP" ]; then
  echo "Removing $PKG_APP (macOS asks for your password)"
  sudo /bin/rm -rf "$PKG_APP"
  sudo /usr/sbin/pkgutil --forget io.github.huntsman-for-mac.pkg >/dev/null 2>&1 || true
fi
if [ "${1:-}" = "--all" ]; then
  if [ -d "$DATA" ]; then /bin/rm -r "$DATA"; fi
  if [ -f "$LOG" ]; then /bin/rm "$LOG"; fi
fi
echo "Removed."
