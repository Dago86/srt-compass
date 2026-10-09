#!/bin/zsh
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d "${TMPDIR:-/private/tmp}/srt-compass-build.XXXXXX")"
trap 'rm -rf "$BUILD_DIR"' EXIT
DIST_DIR="$BUILD_DIR/dist"
VERSION="${VERSION:-0.15.0}"
APP_PATH="$DIST_DIR/SRT Compass.app"
OUTPUT_DIR="$PROJECT_DIR/dist"
MAC_ARCH="${MAC_ARCH:-$(uname -m)}"
case "$MAC_ARCH" in
  arm64|aarch64) VENDOR_ARCH="macos-arm64" ;;
  x86_64|amd64) VENDOR_ARCH="macos-x86_64" ;;
  *) print -u2 "Architettura macOS non supportata: $MAC_ARCH"; exit 1 ;;
esac
VENDOR_DIR="$PROJECT_DIR/vendor/$VENDOR_ARCH"
YTDLP_PATH="$VENDOR_DIR/yt-dlp_macos"
DENO_PATH="$VENDOR_DIR/deno"
if [[ "$VENDOR_ARCH" == "macos-arm64" ]]; then
  "$PROJECT_DIR/scripts/prepare-vendor-macos.sh"
else
  "$PROJECT_DIR/scripts/prepare-vendor-macos-intel.sh"
fi
EXPECTED_YTDLP_SHA256="$(cat "$VENDOR_DIR/yt-dlp.sha256")"
EXPECTED_DENO_SHA256="$(cat "$VENDOR_DIR/deno.sha256")"
ACTUAL_YTDLP_SHA256="$(shasum -a 256 "$YTDLP_PATH" | awk '{print $1}')"
ACTUAL_DENO_SHA256="$(shasum -a 256 "$DENO_PATH" | awk '{print $1}')"
[[ "$ACTUAL_YTDLP_SHA256" == "$EXPECTED_YTDLP_SHA256" ]] || {
  print -u2 "Checksum yt-dlp non valido"
  exit 1
}
[[ "$ACTUAL_DENO_SHA256" == "$EXPECTED_DENO_SHA256" ]] || {
  print -u2 "Checksum Deno non valido"
  exit 1
}
export PYINSTALLER_CONFIG_DIR="$BUILD_DIR/pyinstaller-cache"
PYTHON_BIN="python3"
[[ -x "$PROJECT_DIR/.venv/bin/python" ]] && PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
"$PYTHON_BIN" -m PyInstaller --noconfirm --windowed --name "SRT Compass" \
  --osx-bundle-identifier "org.videosottotitoli.app" \
  --exclude-module tiktoken --exclude-module numpy --exclude-module scipy \
  --exclude-module pandas --exclude-module matplotlib --exclude-module PIL \
  --additional-hooks-dir "$PROJECT_DIR/packaging-hooks" \
  --add-binary "$YTDLP_PATH:bin" --add-binary "$DENO_PATH:bin" \
  --add-data "$PROJECT_DIR/vendor/licenses:licenses" \
  --paths "$PROJECT_DIR/src" --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR/work" --specpath "$BUILD_DIR/spec" \
  "$PROJECT_DIR/run.py"
PLIST="$APP_PATH/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" "$PLIST"
xattr -cr "$APP_PATH"
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"
mkdir -p "$OUTPUT_DIR"
hdiutil create -volname "SRT Compass $VERSION" \
  -srcfolder "$APP_PATH" -ov -format UDZO \
  "$BUILD_DIR/SRT Compass $VERSION $VENDOR_ARCH.dmg"
cp "$BUILD_DIR/SRT Compass $VERSION $VENDOR_ARCH.dmg" \
  "$OUTPUT_DIR/SRT Compass $VERSION $VENDOR_ARCH.dmg"
print "Build created in $OUTPUT_DIR"
