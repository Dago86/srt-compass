#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR_DIR="$PROJECT_DIR/vendor/linux-x86_64"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/srt-compass-vendor.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

YTDLP_VERSION="${YTDLP_VERSION:-2026.08.19}"
DENO_VERSION="${DENO_VERSION:-2.9.7}"
YTDLP_URL="https://github.com/yt-dlp/yt-dlp/releases/download/${YTDLP_VERSION}/yt-dlp_linux"
YTDLP_SUMS_URL="https://github.com/yt-dlp/yt-dlp/releases/download/${YTDLP_VERSION}/SHA2-256SUMS"
DENO_URL="https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip"

checksum() { sha256sum "$1" | awk '{print $1}'; }
mkdir -p "$VENDOR_DIR"
curl --fail --location --retry 3 "$YTDLP_URL" --output "$TMP_DIR/yt-dlp_linux"
curl --fail --location --retry 3 "$YTDLP_SUMS_URL" --output "$TMP_DIR/yt-dlp.sums"
curl --fail --location --retry 3 "$DENO_URL" --output "$TMP_DIR/deno.zip"
curl --fail --location --retry 3 "$DENO_URL.sha256sum" --output "$TMP_DIR/deno.sha256sum"

YTDLP_SHA256="$(awk '/[[:space:]]yt-dlp_linux$/{print $1; exit}' "$TMP_DIR/yt-dlp.sums")"
[[ -n "$YTDLP_SHA256" && "$YTDLP_SHA256" == "$(checksum "$TMP_DIR/yt-dlp_linux")" ]] || {
  echo "Checksum yt-dlp non valido" >&2; exit 1
}
DENO_ARCHIVE_SHA256="$(awk '{print $1}' "$TMP_DIR/deno.sha256sum")"
[[ "$DENO_ARCHIVE_SHA256" == "$(checksum "$TMP_DIR/deno.zip")" ]] || {
  echo "Checksum archivio Deno non valido" >&2; exit 1
}
unzip -q "$TMP_DIR/deno.zip" -d "$TMP_DIR/deno"
DENO_SHA256="$(checksum "$TMP_DIR/deno/deno")"
install -m 755 "$TMP_DIR/yt-dlp_linux" "$VENDOR_DIR/yt-dlp_linux"
install -m 755 "$TMP_DIR/deno/deno" "$VENDOR_DIR/deno"
printf '%s\n' "$YTDLP_SHA256" > "$VENDOR_DIR/yt-dlp.sha256"
printf '%s\n' "$DENO_SHA256" > "$VENDOR_DIR/deno.sha256"
echo "yt-dlp e Deno Linux x86_64 pronti e verificati."
