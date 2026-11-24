#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
# Builds the Mac installer, dist/Huntsman-for-Mac-<version>.pkg (Apple silicon, macOS 14.0 or later):
#   1. PyInstaller (packaging/mac/huntsman-mac.spec): "Huntsman for Mac.app" and "Huntsman Lighting.app";
#   2. nests a full copy of the second at Contents/Library/LoginItems of the first (no symlinks: they break strict
#      signature checks);
#   3. signs every library, then the inner app, then the outer one, with HUNTSMAN_SIGN_IDENTITY (a certificate in
#      a keychain, e.g. the self-signed one CI imports) or ad hoc ("-") when it isn't set, and verifies both;
#   4. runs both frozen executables' --version / --self-test (no keyboard, no window);
#   5. pkgbuild (payload /Applications/Huntsman for Mac.app, not relocatable, packaging/mac/pkg/scripts) and
#      productbuild (packaging/mac/pkg/distribution.xml, welcome, the GPL, conclusion).
# Needs: Python 3.13 on Apple silicon with requirements-mac-build.txt installed (PYTHON, default python3).
# Usage, from anywhere:  PYTHON=.venv-build/bin/python tools/build_mac_pkg.sh [all|build|package]
#   build    steps 1-2 only (no signing identity involved: CI runs it before the key is imported)
#   package  steps 3-5 on what "build" left in build/mac
#   all      both (the default)
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="${PYTHON:-python3}"
IDENTITY="${HUNTSMAN_SIGN_IDENTITY:--}"
BUILD="$ROOT/build/mac"
OUT="$ROOT/dist"
APP="$BUILD/dist/Huntsman for Mac.app"
LIGHT="$APP/Contents/Library/LoginItems/Huntsman Lighting.app"

say() { printf '==> %s\n' "$*"; }
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || fail "this builds the Mac app; run it on a Mac."
[[ "$(uname -m)" == "arm64" ]] || fail "the installer is for Apple silicon (arm64); Intel Macs use install.sh."
"$PYTHON" -c 'import PyInstaller, libusb_package' 2>/dev/null \
  || fail "$PYTHON lacks the build tools: $PYTHON -m pip install -r requirements-mac-build.txt"
VERSION="$(cd "$ROOT" && "$PYTHON" -c 'import huntsman_core; print(huntsman_core.__version__)')"
[[ "$VERSION" =~ ^[0-9]+(\.[0-9]+)*$ ]] || fail "unexpected version: $VERSION"
PKG="$OUT/Huntsman-for-Mac-$VERSION.pkg"

do_build() {
  say "Building Huntsman for Mac $VERSION"
  rm -rf "$BUILD"
  mkdir -p "$BUILD" "$OUT"
  (cd "$ROOT" && "$PYTHON" -m PyInstaller --noconfirm --clean --log-level WARN \
    --distpath "$BUILD/dist" --workpath "$BUILD/work" packaging/mac/huntsman-mac.spec)

  say "Nesting Huntsman Lighting.app"
  mkdir -p "$APP/Contents/Library/LoginItems"
  ditto "$BUILD/dist/Huntsman Lighting.app" "$LIGHT"
}

do_package() {
  [[ -x "$APP/Contents/MacOS/HuntsmanForMac" && -d "$LIGHT" ]] || fail "nothing built in $BUILD: run the build phase first"
  mkdir -p "$OUT"
  # sign_bundle BUNDLE: every Mach-O file in its Frameworks and Resources (not in nested apps), then the bundle
  sign_bundle() {
    local b="$1" f
    while IFS= read -r -d '' f; do
      if file -b "$f" | grep -q 'Mach-O'; then
        codesign --force --sign "$IDENTITY" --timestamp=none "$f" >/dev/null 2>&1 || fail "couldn't sign $f"
      fi
    done < <(find "$b/Contents/Frameworks" "$b/Contents/Resources" -type f -print0 2>/dev/null)
    codesign --force --sign "$IDENTITY" --timestamp=none "$b"
  }

  say "Signing ($([[ "$IDENTITY" == "-" ]] && printf 'ad hoc' || printf 'identity %s' "$IDENTITY"))"
  xattr -cr "$APP"
  sign_bundle "$LIGHT"
  sign_bundle "$APP"
  codesign --verify --deep --strict "$LIGHT"
  codesign --verify --deep --strict "$APP"

  say "Smoke-testing the frozen executables"
  smoke() {
    local exe="$1" out
    out="$("$exe" --version)" || fail "$exe --version failed"
    [[ "$out" == "Huntsman for Mac $VERSION" ]] || fail "$exe --version said: $out"
    out="$("$exe" --self-test)" || { printf '%s\n' "$out"; fail "$exe --self-test failed"; }
    grep -q "self-test passed" <<<"$out" || { printf '%s\n' "$out"; fail "$exe --self-test didn't pass"; }
    printf '%s\n' "$out" | tail -1
  }
  smoke "$APP/Contents/MacOS/HuntsmanForMac"
  smoke "$LIGHT/Contents/MacOS/HuntsmanLighting"

  say "Packaging $PKG"
  WORK="$(mktemp -d)"
  trap 'rm -rf -- "$WORK"' EXIT
  mkdir -p "$WORK/root/Applications" "$WORK/resources" "$WORK/packages"
  ditto "$APP" "$WORK/root/Applications/Huntsman for Mac.app"
  pkgbuild --analyze --root "$WORK/root" "$WORK/component.plist" >/dev/null
  # Never "relocate" the install into another copy with the same bundle id (install.sh's ~/Applications app).
  i=0
  while /usr/libexec/PlistBuddy -c "Print :$i" "$WORK/component.plist" >/dev/null 2>&1; do
    /usr/libexec/PlistBuddy -c "Delete :$i:BundleIsRelocatable" "$WORK/component.plist" >/dev/null 2>&1 || true
    /usr/libexec/PlistBuddy -c "Add :$i:BundleIsRelocatable bool false" "$WORK/component.plist"
    i=$((i + 1))
  done
  [[ "$i" -ge 1 ]] || fail "pkgbuild found no bundle to install"
  pkgbuild --quiet --root "$WORK/root" --component-plist "$WORK/component.plist" --identifier io.github.huntsman-for-mac.pkg \
    --version "$VERSION" --install-location / --scripts "$ROOT/packaging/mac/pkg/scripts" "$WORK/packages/app.pkg"
  cp "$ROOT/packaging/mac/pkg/resources/"*.html "$WORK/resources/"
  cp "$ROOT/LICENSE" "$WORK/resources/LICENSE.txt"
  sed "s/@VERSION@/$VERSION/g" "$ROOT/packaging/mac/pkg/distribution.xml" > "$WORK/distribution.xml"
  rm -f "$PKG"
  productbuild --quiet --distribution "$WORK/distribution.xml" --resources "$WORK/resources" \
    --package-path "$WORK/packages" "$PKG"
  say "Done: $PKG ($(du -h "$PKG" | cut -f1 | tr -d ' '))"
}

case "${1:-all}" in
  build) do_build ;;
  package) do_package ;;
  all) do_build; do_package ;;
  *) fail "usage: $0 [all|build|package]" ;;
esac
