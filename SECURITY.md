# Security

## Reporting a problem

Please report security problems privately, not in a public issue: email **TODO-security@example.com** (TODO: replace with a real address before publishing). Include what you found, how to reproduce it, and which version (`huntsman.py --version`).

You should get a reply within a week. Once a fix is out, we'll credit you unless you'd rather not be named.

## Scope

In scope:
- `install.sh` and `uninstall.sh`, including the login item they create.
- The app and the command line: anything that could let another program or web content make the app send commands to the keyboard, read or change files outside its own folders, or run code.
- Writes to the keyboard that could leave it unusable.

Out of scope:
- The keyboard's firmware itself, and Razer's software.
- Problems that need someone to already control your user account.
- macOS permission prompts (Input Monitoring, Gatekeeper) working as macOS intends.

## How the app is built

- The window loads only local files from the app bundle; it doesn't fetch anything from the internet.
- Everything the window sends is checked in `app.py` (key IDs, colours, ranges) before it reaches the keyboard.
- Settings live in `~/Library/Application Support/Huntsman for Mac/` and the log in `~/Library/Logs/Huntsman for Mac.log`.
