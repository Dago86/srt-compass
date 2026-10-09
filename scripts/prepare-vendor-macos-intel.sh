#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR_DIR="$PROJECT_DIR/vendor/macos-x86_64"
TMP_DIR="$(mktemp -d "${TMPDIR:-/private/tmp}/srt-compass-vendor.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

YTDLP_VERSION="2026.08.19"
DENO_VERSION="2.9.7"
YTDLP_URL="https://github.com/yt-dlp/yt-dlp/releases/download/${YTDLP_VERSION}/yt-dlp_macos"
DENO_URL="https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-apple-darwin.zip"

checksum() { shasum -a 256 "$1" | awk '{print $1}'; }
mkdir -p "$VENDOR_DIR"

curl --fail --location --retry 3 "$YTDLP_URL" --output "$TMP_DIR/yt-dlp_macos"
curl --fail --location --retry 3 "$DENO_URL" --output "$TMP_DIR/deno.zip"
curl --fail --location --retry 3 "$DENO_URL.sha256sum" --output "$TMP_DIR/deno.sha256sum"

YTDLP_SHA256="$(checksum "$TMP_DIR/yt-dlp_macos")"
DENO_ARCHIVE_SHA256="$(awk '{print $1}' "$TMP_DIR/deno.sha256sum")"
[[ "$DENO_ARCHIVE_SHA256" == "$(checksum "$TMP_DIR/deno.zip")" ]] || {
  print -u2 "Checksum archivio Deno non valido"; exit 1
}
ditto -x -k "$TMP_DIR/deno.zip" "$TMP_DIR/deno"
DENO_SHA256="$(checksum "$TMP_DIR/deno/deno")"
install -m 755 "$TMP_DIR/yt-dlp_macos" "$VENDOR_DIR/yt-dlp_macos"
install -m 755 "$TMP_DIR/deno/deno" "$VENDOR_DIR/deno"
print "$YTDLP_SHA256" > "$VENDOR_DIR/yt-dlp.sha256"
print "$DENO_SHA256" > "$VENDOR_DIR/deno.sha256"
print "yt-dlp e Deno Intel pronti e verificati."
