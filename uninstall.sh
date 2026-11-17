#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
# Removes the app (which holds its own code and Python environment) and the login item.
# Settings, presets and typing counts in ~/Library/Application Support/Huntsman for Mac and the log are
# kept unless you pass --all.
# Nothing on the keyboard changes; use "Restore factory depth" in the app first if you want that.
set -euo pipefail
AGENT="$HOME/Library/LaunchAgents/io.github.huntsman-for-mac.apply-saved.plist"
APP="$HOME/Applications/Huntsman for Mac.app"
DATA="$HOME/Library/Application Support/Huntsman for Mac"
LOG="$HOME/Library/Logs/Huntsman for Mac.log"

if pgrep -u "$(id -u)" -f "Contents/Resources/code/app.py" >/dev/null 2>&1; then
  echo "Error: Huntsman for Mac is running. Quit it first (menu bar icon > Quit, or Cmd-Q when Studio is off), then run ./uninstall.sh again." >&2
  exit 1
fi

launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
if [ -f "$AGENT" ]; then /bin/rm "$AGENT"; fi
if [ -d "$APP" ]; then /bin/rm -r "$APP"; fi
if [ "${1:-}" = "--all" ]; then
  if [ -d "$DATA" ]; then /bin/rm -r "$DATA"; fi
  if [ -f "$LOG" ]; then /bin/rm "$LOG"; fi
fi
echo "Removed."
