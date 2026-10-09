#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR_DIR="$PROJECT_DIR/vendor/macos-arm64"
TMP_DIR="$(mktemp -d "${TMPDIR:-/private/tmp}/srt-compass-vendor.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

YTDLP_VERSION="2026.08.19"
YTDLP_SHA256="0f192b7ec147ab6288885d6351d9ab67367640029b4377576ef46dd79cf7b202"
DENO_VERSION="2.9.7"
DENO_ARCHIVE_SHA256="5cd46d6268f6f78f5d88bdc7159d20bd44cdaa4b3303474839f87ec6fe7ae25c"
DENO_BINARY_SHA256="b73737579d5a84c160e3316487594783fa5c15f4e13252a6a07050b755317f1a"

checksum_matches() {
  local expected="$1"
  local file_path="$2"
  local actual
  actual="$(shasum -a 256 "$file_path" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]]
}

verify() {
  local file_path="$2"
  if ! checksum_matches "$1" "$2"; then
    print -u2 "Checksum non valido per $(basename "$file_path")"
    exit 1
  fi
}

mkdir -p "$VENDOR_DIR"

if [[ ! -x "$VENDOR_DIR/yt-dlp_macos" ]] || \
   ! checksum_matches "$YTDLP_SHA256" "$VENDOR_DIR/yt-dlp_macos" 2>/dev/null; then
  rm -f "$VENDOR_DIR/yt-dlp_macos"
  curl --fail --location --retry 3 \
    "https://github.com/yt-dlp/yt-dlp/releases/download/${YTDLP_VERSION}/yt-dlp_macos" \
    --output "$TMP_DIR/yt-dlp_macos"
  verify "$YTDLP_SHA256" "$TMP_DIR/yt-dlp_macos"
  install -m 755 "$TMP_DIR/yt-dlp_macos" "$VENDOR_DIR/yt-dlp_macos"
fi

if [[ ! -x "$VENDOR_DIR/deno" ]] || \
   ! checksum_matches "$DENO_BINARY_SHA256" "$VENDOR_DIR/deno" 2>/dev/null; then
  rm -f "$VENDOR_DIR/deno"
  curl --fail --location --retry 3 \
    "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-aarch64-apple-darwin.zip" \
    --output "$TMP_DIR/deno.zip"
  verify "$DENO_ARCHIVE_SHA256" "$TMP_DIR/deno.zip"
  ditto -x -k "$TMP_DIR/deno.zip" "$TMP_DIR/deno"
  verify "$DENO_BINARY_SHA256" "$TMP_DIR/deno/deno"
  install -m 755 "$TMP_DIR/deno/deno" "$VENDOR_DIR/deno"
fi

verify "$YTDLP_SHA256" "$VENDOR_DIR/yt-dlp_macos"
verify "$DENO_BINARY_SHA256" "$VENDOR_DIR/deno"
print "$YTDLP_SHA256" > "$VENDOR_DIR/yt-dlp.sha256"
print "yt-dlp e Deno sono pronti e verificati."
