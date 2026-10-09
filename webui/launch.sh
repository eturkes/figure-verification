#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# webui/launch.sh -- one-command standup of the figure-verification browser instance.
#
# Brings up the two local services the demo needs, provisioned, so an operator can open
# http://127.0.0.1:8080 in a browser and exercise the paste-in tool + filter:
#
#     model tier (:8001)  ->  Open WebUI (:8080)
#
# The model tier is EITHER the real local model_backend (default; hardware-gated; CUDA dGPU per
# model_backend/runtime/README.md) XOR a deterministic hardware-free stub (--stub). The verifier
# runs inside the provisioned Open WebUI filter; the browser, its Pyodide sandbox and the pixels
# stay trusted (`.claude/rules/figure.md`). This launcher is orchestration only.
#
# Run from the repository root:
#     webui/launch.sh            # real local model on the dGPU
#     webui/launch.sh --stub     # deterministic, hardware-free
#     webui/launch.sh --fresh    # wipe the persisted Open WebUI instance first
#
# Ctrl-C (SIGINT) tears every child down and frees :8001 / :8080.
set -euo pipefail

usage() {
  cat <<'USAGE'
webui/launch.sh -- one-command standup of the figure-verification browser instance.

Usage:
  webui/launch.sh [--stub] [--fresh]

Options:
  --stub      Use the deterministic hardware-free model stub. The stub replaces the real
              local model_backend. The stub needs no GPU and no model weights.
  --fresh     Wipe the persisted Open WebUI instance (.webui-data) first.
  -h, --help  Show this help and exit.

This script starts the model tier (:8001) and Open WebUI (:8080). The script provisions
Open WebUI, then waits until you press Ctrl-C. Ctrl-C frees both ports. Environment variables override the configuration defaults. The
configuration section of this script lists the variables.
USAGE
}

# --- Configuration: every value is an env override with a confirmed default. ---
HEALTH_HOST="${LAUNCH_HEALTH_HOST:-127.0.0.1}"
MODEL_BACKEND_PORT="${MODEL_BACKEND_PORT:-8001}"
WEBUI_PROVISION_PORT="${WEBUI_PROVISION_PORT:-8080}"
WEBUI_PROVISION_ADMIN_EMAIL="${WEBUI_PROVISION_ADMIN_EMAIL:-operator@localhost}"
WEBUI_PROVISION_ADMIN_PASSWORD="${WEBUI_PROVISION_ADMIN_PASSWORD:-loopback-dev-password}"
WEBUI_PROVISION_DATA_DIR="${WEBUI_PROVISION_DATA_DIR:-.webui-data}"
WEBUI_PROVISION_WEBUI_BIN="${WEBUI_PROVISION_WEBUI_BIN:-.venv-webui/bin/open-webui}"
# Open WebUI reaches the model backend and the stub binds the backend URL through this URL. Derive
# it from the port above so a single MODEL_BACKEND_PORT override wires through to provisioning and
# the stub bind. An explicit URL override still wins.
WEBUI_PROVISION_MODEL_BACKEND_URL="${WEBUI_PROVISION_MODEL_BACKEND_URL:-http://${HEALTH_HOST}:${MODEL_BACKEND_PORT}/v1}"
# Real-model device + its interpreter. The backend venv is a SEPARATE uv project
# (model_backend/runtime) carrying the CUDA torch stack, so the real arm runs on its own python and
# never through `uv run`, which resolves the container venv. `-m model_backend` resolves the package
# from the repository root, so no PYTHONPATH is prepended.
MODEL_BACKEND_DEVICE="${MODEL_BACKEND_DEVICE:-cuda}"
MODEL_BACKEND_PYTHON="${MODEL_BACKEND_PYTHON:-.venv-model/bin/python}"
# Per-service logs (*.log + launch.pid; the dir is gitignored).
LOG_DIR="${LAUNCH_LOG_DIR:-.launch-logs}"
# Health-poll ceilings (seconds) -- generous for a cold boot.
MODEL_READY_S="${LAUNCH_MODEL_READY_S:-180}"
WEBUI_READY_S="${LAUNCH_WEBUI_READY_S:-180}"

# uv resolves the container project venv; --locked pins the gate lockfile.
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
# The webui / model children read these from the environment.
export WEBUI_PROVISION_ADMIN_EMAIL WEBUI_PROVISION_ADMIN_PASSWORD WEBUI_PROVISION_PORT
export WEBUI_PROVISION_DATA_DIR MODEL_BACKEND_DEVICE MODEL_BACKEND_PORT
export WEBUI_PROVISION_WEBUI_BIN WEBUI_PROVISION_MODEL_BACKEND_URL

USE_STUB=0
FRESH=0

log() { printf '[launch] %s\n' "$*" >&2; }
die() { printf '[launch] ERROR: %s\n' "$*" >&2; exit 1; }

SERVICE_PIDS=()
SERVICE_NAMES=()
LAST_SERVICE_PID=""

start_bg() {
  # start_bg <name> <logfile> <cmd...>: launch cmd in its OWN session/process group so only this
  # launcher's trap controls teardown. In a non-interactive script (job control off) the setsid
  # child is not a group leader, so setsid execs in place and $! is the new group-leader pid.
  local name=$1 logfile=$2
  shift 2
  setsid "$@" >"$logfile" 2>&1 &
  LAST_SERVICE_PID=$!
  SERVICE_PIDS+=("$LAST_SERVICE_PID")
  SERVICE_NAMES+=("$name")
  log "started ${name} (pid ${LAST_SERVICE_PID}) -> ${logfile}"
}

any_service_alive() {
  local pid
  for pid in "${SERVICE_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then return 0; fi
  done
  return 1
}

port_in_use() {
  # True (0) if something already listens on this loopback port -- a dependency-free /dev/tcp probe
  # in a subshell (the fd never leaks to the parent); connection refused (free) -> non-zero.
  (exec 3<>"/dev/tcp/${HEALTH_HOST}/$1") 2>/dev/null
}

free_port() {
  # Best-effort orphan backstop: only touch a port STILL bound after precise process-group kills
  # above (fuser -k on a free port is already a no-op, but this means we never signal a port we never
  # bound; the start-time preflight already refused launch atop a pre-existing listener). Log if the
  # backstop actually kills something.
  local port=$1
  if port_in_use "$port" && command -v fuser >/dev/null 2>&1; then
    log "port ${port} still bound after group teardown; backstop fuser -k ${port}/tcp"
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  fi
}

cleanup() {
  trap - EXIT INT TERM
  log "shutting down..."
  local pid
  for pid in "${SERVICE_PIDS[@]}"; do
    kill -TERM -- "-${pid}" 2>/dev/null || kill -TERM "${pid}" 2>/dev/null || true
  done
  local waited=0
  while (( waited < 10 )); do
    any_service_alive || break
    sleep 1
    waited=$(( waited + 1 ))
  done
  for pid in "${SERVICE_PIDS[@]}"; do
    kill -KILL -- "-${pid}" 2>/dev/null || kill -KILL "${pid}" 2>/dev/null || true
  done
  free_port "$MODEL_BACKEND_PORT"
  free_port "$WEBUI_PROVISION_PORT"
  wait 2>/dev/null || true
  rm -f "${LOG_DIR}/launch.pid"
  log "down; ports ${MODEL_BACKEND_PORT}/${WEBUI_PROVISION_PORT} freed"
}

wait_http() {
  # wait_http <name> <url> <timeout_s> <pid> <logfile>: poll until the URL answers 2xx, the
  # service process dies, or the timeout elapses.
  local name=$1 url=$2 timeout=$3 pid=$4 logfile=$5 waited=0
  log "waiting for ${name} at ${url} (<= ${timeout}s)"
  while (( waited < timeout )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      log "${name} process exited before becoming ready; last log lines:"
      tail -n 20 "$logfile" >&2 2>/dev/null || true
      return 1
    fi
    if curl -fsS --connect-timeout 2 --max-time 5 -o /dev/null "$url" 2>/dev/null; then
      log "${name} ready"
      return 0
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  log "TIMEOUT waiting for ${name} after ${timeout}s; last log lines:"
  tail -n 20 "$logfile" >&2 2>/dev/null || true
  return 1
}

for arg in "$@"; do
  case "$arg" in
    --stub) USE_STUB=1 ;;
    --fresh) FRESH=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: ${arg} (use --stub, --fresh, or --help)" ;;
  esac
done

[[ -d "$UV_PROJECT_ENVIRONMENT" ]] || die "project venv ${UV_PROJECT_ENVIRONMENT} missing -- run: uv sync --locked"
[[ -x "$WEBUI_PROVISION_WEBUI_BIN" ]] || die "${WEBUI_PROVISION_WEBUI_BIN} missing -- see webui/README.md one-time setup"
if (( ! USE_STUB )); then
  [[ -x "$MODEL_BACKEND_PYTHON" ]] || die "${MODEL_BACKEND_PYTHON} missing -- rebuild it with: uv sync --locked --project model_backend/runtime (or run with --stub)"
  # Fail here rather than 180s later in the readiness poll: a backend that cannot reach the dGPU
  # still binds :8001 and then answers every completion 500. Capturing the probe keeps stdout clean
  # on success while the failure text (ModuleNotFoundError vs the assertion) names WHICH half broke.
  if ! cuda_probe=$("$MODEL_BACKEND_PYTHON" -c 'import torch; assert torch.cuda.is_available(), "torch reports no CUDA device"; print(torch.cuda.get_device_name(0))' 2>&1); then
    die "CUDA preflight failed via ${MODEL_BACKEND_PYTHON}: ${cuda_probe##*$'\n'} (rebuild: uv sync --locked --project model_backend/runtime, or run with --stub)"
  fi
  log "CUDA preflight ok: ${cuda_probe}"
fi

# Refuse to start if a target port is already taken: keeps the readiness poll from adopting a
# foreign listener and keeps the fuser -k teardown scoped to this launcher's own children. This runs
# BEFORE the cleanup trap is installed so a refusal never fuser -k's the pre-existing listener.
for _port in "$MODEL_BACKEND_PORT" "$WEBUI_PROVISION_PORT"; do
  if port_in_use "$_port"; then
    die "port ${_port} is already in use -- stop whatever is bound there (or override the port) before launching"
  fi
done

mkdir -p "$LOG_DIR"
if (( FRESH )); then
  log "--fresh: wiping ${WEBUI_PROVISION_DATA_DIR}"
  rm -rf "$WEBUI_PROVISION_DATA_DIR"
fi

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '%s\n' "$$" > "${LOG_DIR}/launch.pid"

# 1) model tier -- deterministic stub XOR the real dGPU-backed model_backend
if (( USE_STUB )); then
  start_bg model "${LOG_DIR}/model.log" uv run --locked python -m webui stub
else
  start_bg model "${LOG_DIR}/model.log" "$MODEL_BACKEND_PYTHON" -m model_backend
fi
wait_http model "http://${HEALTH_HOST}:${MODEL_BACKEND_PORT}/v1/models" "$MODEL_READY_S" "$LAST_SERVICE_PID" "${LOG_DIR}/model.log" \
  || die "model tier did not become ready"

# 2) Open WebUI
start_bg webui "${LOG_DIR}/webui.log" uv run --locked python -m webui serve
wait_http webui "http://${HEALTH_HOST}:${WEBUI_PROVISION_PORT}/ready" "$WEBUI_READY_S" "$LAST_SERVICE_PID" "${LOG_DIR}/webui.log" \
  || die "Open WebUI did not become ready"

# 3) provision Open WebUI: admin, model, the demo's generated tool + filter.
log "provisioning Open WebUI (admin + model + pasted figure tool)..."
uv run --locked python -m webui bootstrap \
  || die "Open WebUI bootstrap failed (see output above and ${LOG_DIR}/webui.log)"

# Every tracked leader must still be alive at READY: a service that died after its readiness probe
# would otherwise surface only later, as the final wait's exit, after the banner promised a stack.
for _i in "${!SERVICE_PIDS[@]}"; do
  kill -0 "${SERVICE_PIDS[$_i]}" 2>/dev/null \
    || die "${SERVICE_NAMES[$_i]} (pid ${SERVICE_PIDS[$_i]}) exited before READY (see ${LOG_DIR})"
done

# 4) banner. Every stated outcome names its recorded run count or says it is unrecorded; the
#    stub arm's verdict sentences are test-backed (tests/test_webui_banner_prompts.py). The arms +
#    the stub's scripted programs live in webui/banner.json: each request asked honestly, then
#    asked for a named distortion.
simple_prompt="Chart the total revenue of each region using bars."
misleading_prompt="Chart the total revenue of each region using bars. Start the y axis at 30000 so the difference looks larger."
ja_simple_prompt="地域ごとの総売上を棒グラフにしてください。"
ja_misleading_prompt="地域ごとの総売上を棒グラフにしてください。差が大きく見えるように、y 軸は 30000 から始めてください。"
ja_clinic_simple_prompt="年月ごとの平均待ち時間を折れ線グラフで示してください。"
ja_clinic_misleading_prompt="年月ごとの平均待ち時間を折れ線グラフで示してください。待ち時間が短く見えるように、y 軸を反転してください。"
printf -v prompts '%s\n' \
  "    Attach the CSV file shown before a prompt to a new chat. Then paste the prompt:" \
  "      1) [data/sales.csv] ${simple_prompt}" \
  "      2) [data/sales.csv] ${misleading_prompt}" \
  "      3) [data/sales.csv] ${ja_simple_prompt}" \
  "      4) [data/sales.csv] ${ja_misleading_prompt}" \
  "      5) [data/clinic_ja.csv] ${ja_clinic_simple_prompt}" \
  "      6) [data/clinic_ja.csv] ${ja_clinic_misleading_prompt}"
if (( USE_STUB )); then
  model_desc="deterministic stub (hardware-free)"
  printf -v try_typing '%s\n' \
    "${prompts}" \
    "           The inlet binds the uploaded file and its columns before the stub sees them." \
    "           The stub does not run a model. It calls the figure tool with a fixed program." \
    "           Prompts 1, 3 and 5: the verifier passes the chart." \
    "           Prompts 2 and 4: the verifier stops the chart, because the bars do not start at zero." \
    "           Prompt 6: the verifier stops the chart, because the y axis is inverted." \
    "           Other messages, for example \"hello\", get no tool call."
else
  model_desc="real local model on ${MODEL_BACKEND_DEVICE} (${cuda_probe})"
  printf -v try_typing '%s\n' \
    "${prompts}" \
    "           The model writes a Python program. Your browser runs it, and the verifier" \
    "           checks the finished figure. A blocked figure shows:" \
    "           Figure verification failed, no image produced" \
    "           Expect prompts 1, 3 and 5 to pass and prompts 2, 4 and 6 to stop the chart." \
    "           No run with this model has recorded these outcomes yet." \
    "           Use --stub to run the demo without a model."
fi
browser_url="http://${HEALTH_HOST}:${WEBUI_PROVISION_PORT}"
cat >&2 <<BANNER

  ============================================================
  READY -- the verified-plot instance is up.

    Open       ${browser_url}
    Log in     ${WEBUI_PROVISION_ADMIN_EMAIL}  /  ${WEBUI_PROVISION_ADMIN_PASSWORD}
    Model      ${model_desc}

${try_typing}

    Logs       ${LOG_DIR}/{model,webui}.log
    Stop       Ctrl-C  (frees :${MODEL_BACKEND_PORT} / :${WEBUI_PROVISION_PORT})
  ============================================================

BANNER

# 5) Block until a REQUIRED service exits. SIGINT/SIGTERM are handled by their own traps (which exit
#    130/143 before returning here); getting past `wait -n` means a child died on its own -- a
#    failure. Name it and exit non-zero so automation never reads a crashed stack as a clean launch;
#    the EXIT trap still tears everything down.
#    The wait names the tracked leaders explicitly: a bare `wait -n` returns on ANY job, and `-p`
#    records which leader ended, so the reported service is the one that exited, not a guess.
service_rc=0
dead_pid=""
wait -n -p dead_pid "${SERVICE_PIDS[@]}" 2>/dev/null || service_rc=$?
dead_service="unknown"
for _i in "${!SERVICE_PIDS[@]}"; do
  if [[ "${SERVICE_PIDS[$_i]}" == "${dead_pid}" ]]; then
    dead_service="${SERVICE_NAMES[$_i]}"
  fi
done
log "service ${dead_service} (pid ${dead_pid:-none}) exited (status ${service_rc}); tearing down"
# Subshell exit, not a bare top-level `exit`: the latter trips ShellCheck SC2317 ("unreachable")
# on the EXIT-trap-only helpers; `set -e` still propagates this status to the parent, whose EXIT
# trap runs the teardown.
(exit "$(( service_rc == 0 ? 1 : service_rc ))")
