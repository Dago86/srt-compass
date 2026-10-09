#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${VERSION:-0.15.0}"
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/srt-compass-build.XXXXXX")"
trap 'rm -rf "$BUILD_DIR"' EXIT
DIST_DIR="$BUILD_DIR/dist"
APP_DIR="$BUILD_DIR/SRT Compass.AppDir"
VENDOR_DIR="$PROJECT_DIR/vendor/linux-x86_64"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PROJECT_DIR/scripts/prepare-vendor-linux.sh"
export PYINSTALLER_CONFIG_DIR="$BUILD_DIR/pyinstaller-cache"
"$PYTHON_BIN" -m PyInstaller --noconfirm --windowed --name "SRT Compass" \
  --exclude-module tiktoken --exclude-module numpy --exclude-module scipy \
  --exclude-module pandas --exclude-module matplotlib --exclude-module PIL \
  --additional-hooks-dir "$PROJECT_DIR/packaging-hooks" \
  --add-binary "$VENDOR_DIR/yt-dlp_linux:bin" \
  --add-binary "$VENDOR_DIR/deno:bin" \
  --add-data "$PROJECT_DIR/vendor/licenses:licenses" \
  --paths "$PROJECT_DIR/src" --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR/work" --specpath "$BUILD_DIR/spec" \
  "$PROJECT_DIR/run.py"

mkdir -p "$APP_DIR/usr/lib/srt-compass" "$APP_DIR/usr/share/applications" "$APP_DIR/usr/share/icons/hicolor/scalable/apps"
cp -R "$DIST_DIR/SRT Compass/." "$APP_DIR/usr/lib/srt-compass/"
cp "$PROJECT_DIR/packaging/srt-compass.svg" "$APP_DIR/srt-compass.svg"
cp "$PROJECT_DIR/packaging/srt-compass.svg" "$APP_DIR/usr/share/icons/hicolor/scalable/apps/srt-compass.svg"
cat > "$APP_DIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$HERE/usr/lib/srt-compass/SRT Compass" "$@"
EOF
chmod +x "$APP_DIR/AppRun"
cat > "$APP_DIR/usr/share/applications/srt-compass.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=SRT Compass
Comment=Transcribe, translate and improve subtitles
Exec=srt-compass
Icon=srt-compass
Categories=AudioVideo;
Terminal=false
EOF
cp "$APP_DIR/usr/share/applications/srt-compass.desktop" "$APP_DIR/srt-compass.desktop"
if command -v appimagetool >/dev/null 2>&1; then
  mkdir -p "$PROJECT_DIR/dist"
  APPIMAGE_EXTRACT_AND_RUN=1 appimagetool "$APP_DIR" \
    "$PROJECT_DIR/dist/SRT Compass $VERSION linux-x86_64.AppImage"
else
  echo "appimagetool non disponibile: installalo per creare l'AppImage." >&2
  exit 1
fi
echo "Build Linux creata in $PROJECT_DIR/dist"
