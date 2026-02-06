#!/usr/bin/env bash
set -euo pipefail

# Usage: ./deploy.sh [/Volumes/CIRCUITPY]
TARGET="${1:-/Volumes/CIRCUITPY}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() {
  printf "[deploy] %s\n" "$1"
}

progress_bar() {
  local current=$1
  local total=$2
  local start_ts=$3
  local width=30
  if [ "$total" -le 0 ]; then
    total=1
  fi
  local filled=$((current * width / total))
  local empty=$((width - filled))
  local percent=$((current * 100 / total))
  local elapsed=$(( $(date +%s) - start_ts ))
  printf "\r[deploy] ["
  printf "%0.s#" $(seq 1 "$filled")
  printf "%0.s-" $(seq 1 "$empty")
  printf "] %d/%d (%d%%) %ss" "$current" "$total" "$percent" "$elapsed"
}

copy_tree_with_progress() {
  local src=$1
  local dst=$2
  local files=()

  if [ ! -d "$src" ]; then
    log "Source not found: $src"
    return 1
  fi

  while IFS= read -r -d '' d; do
    mkdir -p "$dst/${d#$src/}"
  done < <(find "$src" -type d -print0)

  while IFS= read -r -d '' f; do
    files+=("$f")
  done < <(find "$src" -type f -print0)

  local total=${#files[@]}
  local count=0
  local start_ts
  start_ts=$(date +%s)
  printf "[deploy] Copying %s -> %s\n" "$src" "$dst"
  for f in "${files[@]}"; do
    local rel="${f#$src/}"
    local target="$dst/$rel"
    mkdir -p "$(dirname "$target")"
    cp "$f" "$target"
    count=$((count + 1))
    progress_bar "$count" "$total" "$start_ts"
  done
  printf "\n\n"
}

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

run_step() {
  local msg=$1
  shift
  "$@" &
  local pid=$!
  spinner "$pid" "$msg"
  wait "$pid"
}

if [ ! -d "$TARGET" ]; then
  log "Target not found: $TARGET"
  log "Pass the CIRCUITPY mount path as an argument, e.g.:"
  log "  ./deploy.sh /Volumes/CIRCUITPY"
  exit 1
fi

if [ -f "$TARGET/lib" ]; then
  log "Found lib file on target. Removing and recreating directory."
  rm -f "$TARGET/lib"
fi

run_step "Preparing target" rm -rf "$TARGET/lib"
run_step "Creating lib directory" mkdir -p "$TARGET/lib"

copy_tree_with_progress "$PROJECT_DIR/lib" "$TARGET/lib"
copy_tree_with_progress "$PROJECT_DIR/widgets" "$TARGET/widgets"
run_step "Copying config.json" cp "$PROJECT_DIR/config.json" "$TARGET/config.json"
run_step "Copying main.py -> code.py" cp "$PROJECT_DIR/main.py" "$TARGET/code.py"

log "Deploy complete: $TARGET"
