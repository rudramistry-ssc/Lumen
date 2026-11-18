#!/usr/bin/env bash
# Start Lumen with Docker. Uses a GPU when one is actually usable, else the CPU.
#
#   ./start.sh              detect the accelerator, set up models, start the app
#   ./start.sh --offline    restart from existing images and models, no network
#   ./start.sh --cpu        skip GPU detection and use the CPU
#
# Optional environment (remembered in .env for later runs):
#   LUMEN_ACCELERATOR=auto|cpu|nvidia|intel|intel-wsl|vulkan   (default auto)
#   LUMEN_MODEL_SIZE=2B|8B   vision model size (default 2B; 8B is slower, better)
#   APP_PORT=8000            browser port on localhost
set -euo pipefail
cd "$(dirname "$0")"

offline=0
for arg in "$@"; do
  case "$arg" in
    --offline) offline=1 ;;
    --cpu) LUMEN_ACCELERATOR=cpu ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (see ./start.sh --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mWarning:\033[0m %s\n' "$*" >&2; }

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running or not accessible. Start Docker (or log in again after" >&2
  echo "being added to the 'docker' group) and retry." >&2
  exit 1
fi

# Read a key from .env (used to remember earlier choices).
env_get() { [ -f .env ] && sed -n "s/^$1=//p" .env | tail -n 1 || true; }
# Write or replace one key in .env, keeping every other line.
env_set() {
  touch .env
  grep -v "^$1=" .env > .env.tmp || true
  printf '%s=%s\n' "$1" "$2" >> .env.tmp
  mv .env.tmp .env
}

LUMEN_MODEL_SIZE=$(echo "${LUMEN_MODEL_SIZE:-$(env_get LUMEN_MODEL_SIZE)}" | tr '[:lower:]' '[:upper:]')
LUMEN_MODEL_SIZE=${LUMEN_MODEL_SIZE:-2B}
case "$LUMEN_MODEL_SIZE" in 2B|8B) ;; *) echo "LUMEN_MODEL_SIZE must be 2B or 8B." >&2; exit 2 ;; esac
export LUMEN_MODEL_SIZE
env_set LUMEN_MODEL_SIZE "$LUMEN_MODEL_SIZE"
requested=${LUMEN_ACCELERATOR:-auto}

compose_files() {  # accelerator -> COMPOSE_FILE value
  case "$1" in
    cpu) echo "compose.yaml" ;;
    *) echo "compose.yaml:compose.gpu-$1.yaml" ;;
  esac
}

# Ask llama.cpp itself, inside the exact service definition, which devices it can
# use. A GPU counts only if it is listed (e.g. "SYCL0: Intel(R) Iris(R) Xe ...").
probe() {
  local output
  output=$(COMPOSE_FILE=$(compose_files "$1") docker compose run --rm --no-deps -T \
             --entrypoint /app/llama-server qwen --list-devices 2>&1) || true
  probe_device=$(printf '%s\n' "$output" | grep -E '^[[:space:]]*(CUDA|SYCL|Vulkan|ROCm|MUSA)[0-9]+:' | head -n 1 | sed 's/^[[:space:]]*//')
  [ -n "$probe_device" ]
}

candidates() {  # GPU backends worth probing on this machine, best first
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then echo nvidia; fi
  if [ -e /dev/dxg ]; then echo intel-wsl; fi  # Windows GPU through WSL2
  local node vendor
  for node in /sys/class/drm/renderD*/device/vendor; do
    [ -r "$node" ] || continue
    vendor=$(cat "$node")
    if [ "$vendor" = "0x8086" ]; then echo intel; else echo vulkan; fi
  done
}

accelerator=cpu
probe_device=""
if [ "$requested" = auto ] && [ "$offline" = 1 ] && [ -n "$(env_get LUMEN_ACCELERATOR)" ]; then
  requested=$(env_get LUMEN_ACCELERATOR)  # offline restart: reuse the last proven choice
fi
if [ "$requested" = cpu ]; then
  say "Using the CPU (requested)."
elif [ "$requested" != auto ]; then
  [ -f "compose.gpu-$requested.yaml" ] || { echo "Unknown accelerator: $requested" >&2; exit 2; }
  say "Checking the requested accelerator: $requested"
  if probe "$requested"; then
    accelerator=$requested
  else
    warn "No usable $requested GPU found inside Docker; using the CPU instead."
  fi
else
  say "Looking for a usable GPU..."
  for candidate in $(candidates | awk '!seen[$0]++'); do
    echo "    trying $candidate (the first try downloads its runtime image)..."
    if probe "$candidate"; then accelerator=$candidate; break; fi
    echo "    $candidate: no usable device"
  done
  [ "$accelerator" = cpu ] && say "No usable GPU found; the vision model will run on the CPU."
fi
[ -n "$probe_device" ] && say "GPU: $probe_device"

env_set LUMEN_ACCELERATOR "$accelerator"
COMPOSE_FILE=$(compose_files "$accelerator")
env_set COMPOSE_FILE "$COMPOSE_FILE"
export COMPOSE_FILE

memory_gb=$(awk '/MemTotal/ {printf "%d", $2 / 1048576}' /proc/meminfo 2>/dev/null || echo 0)
if [ "$LUMEN_MODEL_SIZE" = 8B ] && [ "$memory_gb" -lt 11 ]; then
  warn "Docker has ${memory_gb} GB of memory; Qwen3-VL-8B needs about 11 GB."
  warn "Raise the WSL memory limit (see README) or use LUMEN_MODEL_SIZE=2B."
fi

if [ "$offline" = 1 ]; then
  say "Starting from existing images and models (offline)..."
  docker compose up --detach --wait --pull never --no-build
else
  say "Building the app image (first run takes a few minutes)..."
  docker compose build models
  say "Checking/downloading Qwen3-VL-$LUMEN_MODEL_SIZE and speech models..."
  docker compose run --rm models
  say "Starting Lumen..."
  docker compose up --detach --wait
fi

port=$(env_get APP_PORT); port=${APP_PORT:-${port:-8000}}
offload=$(docker compose logs qwen 2>/dev/null | grep -Eo 'offloaded [0-9]+/[0-9]+ layers to GPU' | tail -n 1 || true)
echo
say "Lumen is ready: http://localhost:$port"
echo "    Vision model: Qwen3-VL-$LUMEN_MODEL_SIZE on ${probe_device:-the CPU}${offload:+ ($offload)}"
echo "    Logs: docker compose logs -f     Stop: docker compose down"
