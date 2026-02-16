#!/usr/bin/env bash
set -euo pipefail

# Usage: ./deploy.sh [--force] [--skip-spotify-auth] [--spotify-config path] [--start-imgproxy] [/Volumes/CIRCUITPY]
# Spotify auth runs by default; use --skip-spotify-auth to bypass.
TARGET="/Volumes/CIRCUITPY"
FORCE=0
SKIP_SPOTIFY_AUTH=0
SPOTIFY_CONFIG=""
START_IMGPROXY=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --force)
      FORCE=1
      shift
      ;;
    --skip-spotify-auth)
      SKIP_SPOTIFY_AUTH=1
      shift
      ;;
    --spotify-config)
      SPOTIFY_CONFIG="$2"
      shift 2
      ;;
    --start-imgproxy)
      START_IMGPROXY=1
      shift
      ;;
    *)
      TARGET="$1"
      shift
      ;;
  esac
done
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI_DIR="$PROJECT_DIR/pi_files"
if [ -z "$SPOTIFY_CONFIG" ]; then
  SPOTIFY_CONFIG="$PI_DIR/config.json"
fi
GIF_DIR_DEFAULT="$PI_DIR/images"
GIF_DIR_ALT="$PI_DIR/images/gif"
GIF_DIR_ALT2="$PI_DIR/images/gifs"
IMAGE_STAMP_FILE="$PROJECT_DIR/.deploy_images_stamp"

# log: consistent, prefixed output so deploy progress is easy to scan.
log() {
  printf "[deploy] %s\n" "$1"
}

# ensure_target_writable: verify CIRCUITPY is mounted and writeable.
# CircuitPython mounts read-only when the USB drive is visible, so we prompt
# for an eject/power-cycle to regain write access before copying files.
ensure_target_writable() {
  local attempts=0
  while true; do
    if [ ! -d "$TARGET" ]; then
      log "Target not found: $TARGET"
      log "If boot.py disables USB storage, temporarily enable it and reboot."
      log "Then re-run deploy or press Enter to retry."
    else
      if touch "$TARGET/.deploy_write_test" 2>/dev/null; then
        rm -f "$TARGET/.deploy_write_test"
        log "Target is mounted read-write: $TARGET"
        return 0
      fi
      log "Target is mounted read-only: $TARGET"
      if command -v diskutil >/dev/null 2>&1; then
        log "Attempting to unmount via diskutil..."
        diskutil unmount "$TARGET" >/dev/null 2>&1 || true
      fi
      log "Please recycle the Pico while holding the main control button, then press Enter to retry."
    fi
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 5 ]; then
      log "Giving up after $attempts attempts."
      exit 1
    fi
    read -r -p "[deploy] Press Enter to retry (attempt $attempts/5)..." _resp
  done
}

# detect_lan_ip: best-effort host LAN IP detection (macOS first, then Linux).
# Used to rewrite spotify_image_proxy so the Pico can reach the host via LAN.
detect_lan_ip() {
  local ip=""
  if command -v ipconfig >/dev/null 2>&1; then
    local iface
    iface=$(route get default 2>/dev/null | awk '/interface:/{print $2}' | head -n 1)
    if [ -n "$iface" ]; then
      ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
    fi
    if [ -z "$ip" ]; then
      for candidate in en0 en1; do
        ip=$(ipconfig getifaddr "$candidate" 2>/dev/null || true)
        if [ -n "$ip" ]; then
          break
        fi
      done
    fi
  fi
  if [ -z "$ip" ] && command -v hostname >/dev/null 2>&1; then
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  fi
  if [ -z "$ip" ] && command -v ip >/dev/null 2>&1; then
    ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++){if($i=="src"){print $(i+1); exit}}}')
  fi
  if [ -n "$ip" ]; then
    printf "%s" "$ip"
    return 0
  fi
  return 1
}

# update_proxy_url: rewrite spotify_image_proxy if it points to loopback.
# Pico can't reach localhost/127.0.0.1 on the host, so we swap in LAN IP.
update_proxy_url() {
  local config_path="$PI_DIR/config.json"
  if [ ! -f "$config_path" ]; then
    return 0
  fi
  local ip
  ip=$(detect_lan_ip) || {
    log "Could not detect LAN IP; leaving spotify_image_proxy unchanged."
    return 0
  }
  python3 - "$config_path" "$ip" <<'PY'
import json
import sys
from urllib.parse import urlparse, urlunparse

path = sys.argv[1]
ip = sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)

url = (data.get("spotify_image_proxy") or "").strip()
if not url:
    sys.exit(0)

parsed = urlparse(url)
host = parsed.hostname or ""
if host in ("localhost", "127.0.0.1", "::1"):
    netloc = ip
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    new_url = urlunparse(parsed._replace(netloc=netloc))
    data["spotify_image_proxy"] = new_url
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    print(f"[deploy] Updated spotify_image_proxy -> {new_url}")
PY
}

# check_image_proxy: verify spotify_image_proxy is reachable.
check_image_proxy() {
  ensure_tool python3
  if [ ! -f "$SPOTIFY_CONFIG" ]; then
    log "Config not found: $SPOTIFY_CONFIG (skipping image proxy check)"
    return 0
  fi
  local proxy_url
  proxy_url="$(python3 - "$SPOTIFY_CONFIG" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    data = {}

value = (data.get("spotify_image_proxy") or "").strip()
print(value)
PY
)"
  if [ -z "$proxy_url" ]; then
    log "spotify_image_proxy not set; skipping image proxy check."
    return 0
  fi
  python3 - "$proxy_url" <<'PY'
import socket
import sys
from urllib.parse import urlparse

url = sys.argv[1]
parsed = urlparse(url)
host = parsed.hostname or ""
if not host:
    print("[deploy] Could not parse spotify_image_proxy host; skipping check.")
    sys.exit(0)
port = parsed.port
if port is None:
    port = 443 if parsed.scheme == "https" else 80

sock = socket.socket()
sock.settimeout(2.0)
try:
    sock.connect((host, port))
    print(f"[deploy] Image proxy is up and running at {host}:{port}")
except Exception as exc:
    print(f"[deploy] Image proxy not reachable at {host}:{port} ({exc.__class__.__name__})")
finally:
    try:
        sock.close()
    except Exception:
        pass
PY
}

# start_imgproxy: optionally run imgproxy for local album art resizing.
start_imgproxy() {
  if [ "$START_IMGPROXY" -ne 1 ]; then
    return 0
  fi
  log "Starting imgproxy on http://127.0.0.1:8080 (ctrl+c to stop)."
  docker run -p 8080:8080 -it ghcr.io/imgproxy/imgproxy:latest
}

start_imgproxy

# file_size: return file size in bytes (macOS/Linux compatible).
file_size() {
  stat -f%z "$1" 2>/dev/null || stat -c%s "$1"
}

# format_bytes: human-readable byte formatting for progress logs.
format_bytes() {
  local bytes=$1
  local units=(B KB MB GB)
  local i=0
  local value=$bytes
  while [ "$value" -ge 1024 ] && [ "$i" -lt 3 ]; do
    value=$((value / 1024))
    i=$((i + 1))
  done
  printf "%s%s" "$value" "${units[$i]}"
}

# progress_bar: prints a simple inline progress indicator for sync operations.
progress_bar() {
  local current=$1
  local total=$2
  local start_ts=$3
  local bytes_current=${4:-}
  local bytes_total=${5:-}
  local width=30
  if [ "$total" -le 0 ]; then
    total=1
  fi
  local filled=$((current * width / total))
  local empty=$((width - filled))
  local percent=$((current * 100 / total))
  local elapsed=$(( $(date +%s) - start_ts ))
  local bytes_info=""
  if [ -n "$bytes_current" ] && [ -n "$bytes_total" ]; then
    bytes_info=" $(format_bytes "$bytes_current")/$(format_bytes "$bytes_total")"
  fi
  printf "\r[deploy] ["
  printf "%0.s#" $(seq 1 "$filled")
  printf "%0.s-" $(seq 1 "$empty")
  printf "] %d/%d (%d%%)%s %ss" "$current" "$total" "$percent" "$bytes_info" "$elapsed"
}

# files_need_copy: detects whether a file should be copied (size/contents/force).
files_need_copy() {
  local src=$1
  local dst=$2
  if [ "$FORCE" -eq 1 ]; then
    return 0
  fi
  if [ ! -f "$dst" ]; then
    return 0
  fi
  if command -v cmp >/dev/null 2>&1; then
    if cmp -s "$src" "$dst"; then
      return 1
    fi
    return 0
  fi
  local src_size dst_size
  src_size=$(file_size "$src")
  dst_size=$(file_size "$dst")
  if [ "$src_size" -ne "$dst_size" ]; then
    return 0
  fi
  return 1
}

# copy_file_if_changed: copy a single file only when content differs.
copy_file_if_changed() {
  local src=$1
  local dst=$2
  local label=${3:-$dst}
  if [ ! -f "$src" ]; then
    log "Source not found: $src"
    return 1
  fi
  if files_need_copy "$src" "$dst"; then
    log "Copying $label"
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
  else
    log "Up to date: $label"
  fi
}

# sync_tree_with_progress: sync a directory tree with deletes + progress.
sync_tree_with_progress() {
  local src=$1
  local dst=$2
  local files=()
  local files_to_copy=()
  local files_to_delete=()

  if [ ! -d "$src" ]; then
    log "Source not found: $src"
    return 1
  fi

  while IFS= read -r -d '' f; do
    files+=("$f")
  done < <(find "$src" -type f -print0)

  local total_bytes=0
  local copied_bytes=0

  mkdir -p "$dst"

  if [ -d "$dst" ]; then
    while IFS= read -r -d '' f; do
      local rel="${f#$dst/}"
      if [ ! -f "$src/$rel" ]; then
        files_to_delete+=("$f")
      fi
    done < <(find "$dst" -type f -print0)
  fi

  for f in "${files[@]}"; do
    local rel="${f#$src/}"
    local target="$dst/$rel"
    if files_need_copy "$f" "$target"; then
      files_to_copy+=("$f")
      local size
      size=$(file_size "$f")
      total_bytes=$((total_bytes + size))
    fi
  done

  if [ "${#files_to_delete[@]}" -gt 0 ]; then
    log "Removing ${#files_to_delete[@]} stale files from $dst"
    for f in "${files_to_delete[@]}"; do
      rm -f "$f"
    done
    find "$dst" -type d -empty -delete 2>/dev/null || true
  fi

  local total=${#files_to_copy[@]}
  if [ "$total" -eq 0 ]; then
    log "Up to date: $src"
    printf "\n"
    return 0
  fi

  local count=0
  local start_ts
  start_ts=$(date +%s)
  printf "[deploy] Syncing %s -> %s\n" "$src" "$dst"
  for f in "${files_to_copy[@]}"; do
    local rel="${f#$src/}"
    local target="$dst/$rel"
    local size
    size=$(file_size "$f")
    mkdir -p "$(dirname "$target")"
    cp "$f" "$target"
    count=$((count + 1))
    copied_bytes=$((copied_bytes + size))
    progress_bar "$count" "$total" "$start_ts" "$copied_bytes" "$total_bytes"
  done
  progress_bar "$total" "$total" "$start_ts" "$total_bytes" "$total_bytes"
  printf "\n\n"
}

# spinner: show a spinner for long-running steps.
spinner() {
  local pid=$1
  local msg=$2
  local spin='|/-\\'
  local i=0
  printf "[deploy] %s " "$msg"
  while kill -0 "$pid" 2>/dev/null; do
    printf "\b%s" "${spin:i%4:1}"
    i=$((i+1))
    sleep 0.1
  done
  printf "\b✓\n\n"
}

# run_step: execute a command with a spinner + label.
run_step() {
  local msg=$1
  shift
  "$@" &
  local pid=$!
  spinner "$pid" "$msg"
  wait "$pid"
}

# ensure_tool: verify an external tool exists before running conversions.
ensure_tool() {
  local tool=$1
  if ! command -v "$tool" >/dev/null 2>&1; then
    log "Missing required tool: $tool"
    exit 1
  fi
}

# detect_gif_dir: find GIF directory within images (supports legacy paths).
detect_gif_dir() {
  if [ -d "$GIF_DIR_ALT" ]; then
    printf "%s" "$GIF_DIR_ALT"
    return
  fi
  if [ -d "$GIF_DIR_ALT2" ]; then
    printf "%s" "$GIF_DIR_ALT2"
    return
  fi
  printf "%s" "$GIF_DIR_DEFAULT"
}

# images_fingerprint: hash GIF names/sizes/mtimes to detect changes quickly.
images_fingerprint() {
  local src_dir=$1
  if ! command -v python3 >/dev/null 2>&1; then
    return 0
  fi
  python3 - "$src_dir" <<'PY'
import hashlib
import os
import sys

root = sys.argv[1]
if not os.path.isdir(root):
    sys.exit(0)

paths = []
for base, _, files in os.walk(root):
    for name in files:
        if name.lower().endswith(".gif"):
            paths.append(os.path.join(base, name))

paths.sort()
if not paths:
    sys.exit(0)

h = hashlib.sha1()
for path in paths:
    try:
        st = os.stat(path)
    except Exception:
        continue
    rel = os.path.relpath(path, root)
    h.update(rel.encode())
    h.update(str(st.st_size).encode())
    h.update(str(int(st.st_mtime)).encode())

print(h.hexdigest())
PY
}

# target_images_missing: returns 0 if images folder is missing or empty.
target_images_missing() {
  if [ ! -d "$TARGET/images" ]; then
    return 0
  fi
  if find "$TARGET/images" -type f -name "*.bmp" -print -quit | grep -q .; then
    return 1
  fi
  return 0
}

# count_gif_frames: count frames so we can report conversion progress.
count_gif_frames() {
  local gif=$1
  local frames=""
  frames=$(ffprobe -v error -count_frames -select_streams v:0 \
    -show_entries stream=nb_read_frames \
    -of default=nokey=1:noprint_wrappers=1 "$gif" 2>/dev/null || true)
  if [ -z "$frames" ] || [ "$frames" = "N/A" ]; then
    frames=$(ffprobe -v error -select_streams v:0 \
      -show_entries stream=nb_frames \
      -of default=nokey=1:noprint_wrappers=1 "$gif" 2>/dev/null || true)
  fi
  if ! [[ "$frames" =~ ^[0-9]+$ ]] || [ "$frames" -le 0 ]; then
    frames=1
  fi
  printf "%s" "$frames"
}

# convert_gifs_to_bmp: convert GIF animations to BMP frames for displayio.
convert_gifs_to_bmp() {
  local src_dir=$1
  local out_dir=$2
  local converted=0
  local found=0
  mkdir -p "$out_dir"

  while IFS= read -r -d '' gif; do
    found=$((found + 1))
    local base
    base=$(basename "$gif")
    local name="${base%.*}"
    local out="$out_dir/$name.bmp"

    if [ "$FORCE" -eq 0 ] && [ -f "$out" ] && [ "$out" -nt "$gif" ]; then
      log "Up to date: $base"
      continue
    fi

    local frames
    frames=$(count_gif_frames "$gif")
    log "Converting $base -> $name.bmp (frames: $frames)"

    ffmpeg -hide_banner -loglevel error -i "$gif" \
      -vf "scale=64:64:flags=lanczos:force_original_aspect_ratio=decrease,\
pad=64:64:(ow-iw)/2:(oh-ih)/2:color=black,\
tile=1x${frames}" \
      -frames:v 1 -pix_fmt bgr24 "$out"
    converted=$((converted + 1))
  done < <(find "$src_dir" -type f -name "*.gif" -print0)

  if [ "$found" -eq 0 ]; then
    log "No GIFs found in $src_dir"
  else
    log "Converted $converted GIF(s) to BMP spritesheets."
  fi
}

# run_spotify_auth: perform OAuth flow to refresh the Spotify token.
run_spotify_auth() {
  if [ "$SKIP_SPOTIFY_AUTH" -eq 1 ]; then
    return 0
  fi
  ensure_tool python3
  if [ ! -f "$SPOTIFY_CONFIG" ]; then
    log "Config not found: $SPOTIFY_CONFIG"
    exit 1
  fi

  local client_id
  local client_secret
  client_id="$(python3 - "$SPOTIFY_CONFIG" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    data = {}

value = (data.get("spotify_client_id") or "").strip()
print(value)
PY
)"
  client_secret="$(python3 - "$SPOTIFY_CONFIG" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    data = {}

value = (data.get("spotify_client_secret") or "").strip()
print(value)
PY
)"

  if [ -z "$client_id" ] || [ -z "$client_secret" ] \
     || [ "$client_id" = "YOUR_SPOTIFY_CLIENT_ID" ] \
     || [ "$client_secret" = "YOUR_SPOTIFY_CLIENT_SECRET" ]; then
    log "Missing spotify_client_id or spotify_client_secret in $SPOTIFY_CONFIG"
    exit 1
  fi

  local redirect="${SPOTIFY_REDIRECT_URI:-http://127.0.0.1:15298/callback}"
  local scopes="${SPOTIFY_SCOPES:-user-read-currently-playing}"
  local timeout="${SPOTIFY_TIMEOUT:-180}"
  log "Running Spotify auth flow (open the printed URL to authorize)"
  python3 "$PROJECT_DIR/tools/spotify_auth.py" \
    --client-id "$client_id" \
    --client-secret "$client_secret" \
    --redirect-uri "$redirect" \
    --scopes "$scopes" \
    --timeout "$timeout" \
    --write-config \
    --config-path "$SPOTIFY_CONFIG"
}

ensure_target_writable

if [ -f "$TARGET/error.log" ]; then
  log "Removing $TARGET/error.log"
  rm -f "$TARGET/error.log"
fi

check_image_proxy

run_spotify_auth

update_proxy_url

sync_tree_with_progress "$PI_DIR/lib" "$TARGET/lib"
sync_tree_with_progress "$PI_DIR/api" "$TARGET/api"
sync_tree_with_progress "$PI_DIR/local" "$TARGET/local"
sync_tree_with_progress "$PI_DIR/widgets" "$TARGET/widgets"
if [ -d "$PI_DIR/announcements" ]; then
  sync_tree_with_progress "$PI_DIR/announcements" "$TARGET/announcements"
fi
if [ -d "$PI_DIR/images" ]; then
  GIF_DIR="$(detect_gif_dir)"
  image_stamp="$(images_fingerprint "$GIF_DIR" || true)"
  if [ -z "$image_stamp" ]; then
    log "No GIFs found in $GIF_DIR"
  elif [ "$FORCE" -eq 0 ] && [ -f "$IMAGE_STAMP_FILE" ] \
      && [ "$(cat "$IMAGE_STAMP_FILE")" = "$image_stamp" ] \
      && ! target_images_missing; then
    log "Images unchanged; skipping GIF conversion + sync."
  else
    ensure_tool ffmpeg
    ensure_tool ffprobe
    TMP_BMP_DIR="$(mktemp -d "/tmp/ledmatrix_bmp.XXXXXX")"
    log "Converting GIFs in $GIF_DIR"
    convert_gifs_to_bmp "$GIF_DIR" "$TMP_BMP_DIR"
    if find "$TMP_BMP_DIR" -type f -name "*.bmp" -print -quit | grep -q .; then
      sync_tree_with_progress "$TMP_BMP_DIR" "$TARGET/images"
    else
      log "No BMPs generated; skipping image sync."
    fi
    rm -rf "$TMP_BMP_DIR"
    echo "$image_stamp" > "$IMAGE_STAMP_FILE"
  fi
fi
copy_file_if_changed "$PI_DIR/config.json" "$TARGET/config.json" "config.json"
if [ -f "$PI_DIR/boot.py" ]; then
  copy_file_if_changed "$PI_DIR/boot.py" "$TARGET/boot.py" "boot.py"
fi
copy_file_if_changed "$PI_DIR/main.py" "$TARGET/code.py" "main.py -> code.py"

log "Deploy complete: $TARGET"
printf "\n"
