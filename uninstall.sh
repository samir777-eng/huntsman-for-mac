#!/bin/bash
# Removes the app (which holds its own code and Python environment) and the login item.
# Settings in ~/Library/Application Support/Huntsman for Mac are kept unless you pass --all.
# Nothing on the keyboard changes; use "Restore factory depth" in the app first if you want that.
set -euo pipefail
AGENT="$HOME/Library/LaunchAgents/io.github.huntsman-for-mac.apply-saved.plist"
APP="$HOME/Applications/Huntsman for Mac.app"
DATA="$HOME/Library/Application Support/Huntsman for Mac"

launchctl bootout "gui/$(id -u)" "$AGENT" 2>/dev/null || true
if [ -f "$AGENT" ]; then /bin/rm "$AGENT"; fi
if [ -d "$APP" ]; then /bin/rm -r "$APP"; fi
if [ "${1:-}" = "--all" ] && [ -d "$DATA" ]; then /bin/rm -r "$DATA"; fi
echo "Removed."
