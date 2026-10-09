#!/bin/zsh
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d "${TMPDIR:-/private/tmp}/srt-compass-build.XXXXXX")"
trap 'rm -rf "$BUILD_DIR"' EXIT
DIST_DIR="$BUILD_DIR/dist"
APP_PATH="$DIST_DIR/SRT Compass.app"
OUTPUT_DIR="$PROJECT_DIR/dist"
YTDLP_PATH="$PROJECT_DIR/vendor/macos-arm64/yt-dlp_macos"
DENO_PATH="$PROJECT_DIR/vendor/macos-arm64/deno"
"$PROJECT_DIR/scripts/prepare-vendor-macos.sh"
EXPECTED_YTDLP_SHA256="0f192b7ec147ab6288885d6351d9ab67367640029b4377576ef46dd79cf7b202"
EXPECTED_DENO_SHA256="$(cat "$PROJECT_DIR/vendor/macos-arm64/deno.sha256")"
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
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 0.14.1" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 0.14.1" "$PLIST"
xattr -cr "$APP_PATH"
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict "$APP_PATH"
mkdir -p "$OUTPUT_DIR"
hdiutil create -volname "SRT Compass 0.14.1" \
  -srcfolder "$APP_PATH" -ov -format UDZO \
  "$BUILD_DIR/SRT Compass 0.14.1.dmg"
cp "$BUILD_DIR/SRT Compass 0.14.1.dmg" \
  "$OUTPUT_DIR/SRT Compass 0.14.1.dmg"
print "Build created in $OUTPUT_DIR"
