#!/bin/sh
# Entrypoint of the `qwen` container: run llama-server on the GPU, and if the GPU
# server crashes, keep serving on the CPU instead of failing.
#
# Arguments are passed to llama-server. GPU mode = LLAMA_ARG_N_GPU_LAYERS > 0
# (set by the compose.gpu-*.yaml overrides). After LUMEN_GPU_MAX_CRASHES GPU
# crashes (default 2) this container serves on the CPU until it is recreated;
# the next ./start.sh tries the GPU again. The app retries a request that was
# cut off by a crash, so users get an answer either way.
set -u
server=/app/llama-server
max=${LUMEN_GPU_MAX_CRASHES:-2}
crashes=0
pid=""

# Forward `docker stop` to llama-server so it shuts down cleanly.
trap '[ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; exit 143' TERM INT

run() {
  "$server" "$@" &
  pid=$!
  wait "$pid"
  code=$?
  pid=""
  return $code
}

if [ "${LLAMA_ARG_N_GPU_LAYERS:-0}" != 0 ]; then
  while [ "$crashes" -lt "$max" ]; do
    run "$@"
    code=$?
    [ "$code" -eq 0 ] && exit 0
    crashes=$((crashes + 1))
    echo "lumen: GPU llama-server stopped unexpectedly (exit $code; $crashes of $max)." >&2
  done
  echo "lumen: the GPU keeps failing; serving the model on the CPU from now on." >&2
fi

export LLAMA_ARG_N_GPU_LAYERS=0
run "$@" --device none --no-mmproj-offload
exit $?
