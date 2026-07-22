#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# webui/launch.sh -- one-command standup of the verified-plot browser instance (M7.1).
#
# Brings up the three local services the PoC needs, provisioned, so an operator can open
# http://127.0.0.1:8080 in a browser and interactively exercise the verified-plot pipeline:
#
#     verifier (:8000)  ->  model tier (:8001)  ->  Open WebUI (:8080)
#
# The model tier is EITHER the real local OpenVINO model_backend (default; hardware-gated;
# device NPU per CLAUDE.local.md) XOR a deterministic hardware-free stub (--stub). Open WebUI,
# its function runner, the iframe/browser, and pixels stay trusted display/orchestration -- the
# verifier adds no trust here and no claim boundary moves (POC_SCOPE TCB, as M4 established).
# This launcher is orchestration only; every service, provisioning step, and the chart/embed
# contract already exists (M3 model_backend, M4 webui/, M5 verifier, M6 persisted-chat + demo).
#
# Run from the repository root:
#     webui/launch.sh            # real local model on the NPU
#     webui/launch.sh --stub     # deterministic, hardware-free
#     webui/launch.sh --fresh    # wipe the persisted Open WebUI instance first
#
# Ctrl-C (SIGINT) tears every child down and frees :8000 / :8001 / :8080.
set -euo pipefail

usage() {
  cat <<'USAGE'
webui/launch.sh -- one-command standup of the verified-plot browser instance.

Usage:
  webui/launch.sh [--stub] [--fresh]

Options:
  --stub      Use the deterministic hardware-free model stub instead of the real local
              OpenVINO model_backend (no NPU / accel farm required).
  --fresh     Wipe the persisted Open WebUI instance (.webui-data) before starting.
  -h, --help  Show this help and exit.

Brings up verifier (:8000), the model tier (:8001), and Open WebUI (:8080), provisions
Open WebUI, then blocks until Ctrl-C (which frees all three ports). Every default is
overridable via environment variables (see the header of this script).
USAGE
}

# --- Configuration: every value is an env override with a confirmed default. ---
HEALTH_HOST="${LAUNCH_HEALTH_HOST:-127.0.0.1}"
VERIFIER_PORT="${VERIFIER_PORT:-8000}"
MODEL_BACKEND_PORT="${MODEL_BACKEND_PORT:-8001}"
WEBUI_PROVISION_PORT="${WEBUI_PROVISION_PORT:-8080}"
WEBUI_PROVISION_ADMIN_EMAIL="${WEBUI_PROVISION_ADMIN_EMAIL:-operator@localhost}"
WEBUI_PROVISION_ADMIN_PASSWORD="${WEBUI_PROVISION_ADMIN_PASSWORD:-loopback-dev-password}"
WEBUI_PROVISION_DATA_DIR="${WEBUI_PROVISION_DATA_DIR:-.webui-data}"
WEBUI_PROVISION_WEBUI_BIN="${WEBUI_PROVISION_WEBUI_BIN:-.venv-webui/bin/open-webui}"
# Open WebUI reaches the verifier + model backend, the verifier reaches the model backend for
# /propose-spec, and the stub binds the backend URL -- all through these URLs. Derive them from the
# ports above so a single VERIFIER_PORT / MODEL_BACKEND_PORT override wires through to provisioning,
# the verifier's model client, the stub bind, and (via VERIFIER_PORT, which the verifier turns into
# its chart Location) the certificate links. An explicit URL override still wins, and at the default
# ports these are byte-identical to the previous defaults.
WEBUI_PROVISION_VERIFIER_URL="${WEBUI_PROVISION_VERIFIER_URL:-http://${HEALTH_HOST}:${VERIFIER_PORT}}"
WEBUI_PROVISION_MODEL_BACKEND_URL="${WEBUI_PROVISION_MODEL_BACKEND_URL:-http://${HEALTH_HOST}:${MODEL_BACKEND_PORT}/v1}"
VERIFIER_MODEL_BASE_URL="${VERIFIER_MODEL_BASE_URL:-http://${HEALTH_HOST}:${MODEL_BACKEND_PORT}/v1}"
# Real-model device preference (CLAUDE.local.md: NPU>GPU>CPU) and the host-coupled accel farm
# (bench/README "OpenVINO wiring"): sourced + prepended ONLY for the real model_backend child.
MODEL_BACKEND_DEVICE="${MODEL_BACKEND_DEVICE:-NPU}"
INTEL_ACCEL_ENV="${INTEL_ACCEL_ENV:-/var/home/eturkes/.local/app/intel-accel/env.sh}"
OPENVINO_GENAI_PYTHON="${OPENVINO_GENAI_PYTHON:-/var/home/eturkes/.local/app/openvino_genai/python}"
MODEL_BACKEND_PYTHON="${MODEL_BACKEND_PYTHON:-.venv-model/bin/python}"
# Per-service logs (*.log + launch.pid; the dir is gitignored).
LOG_DIR="${LAUNCH_LOG_DIR:-.launch-logs}"
# Health-poll ceilings (seconds) -- generous for a cold boot.
VERIFIER_READY_S="${LAUNCH_VERIFIER_READY_S:-90}"
MODEL_READY_S="${LAUNCH_MODEL_READY_S:-180}"
WEBUI_READY_S="${LAUNCH_WEBUI_READY_S:-180}"

# Raise the verifier's process-local work rate so interactive clicking is not 429-throttled
# (production defaults stay in force when the operator does not override).
export VERIFIER_WORK_RATE_PER_MINUTE="${VERIFIER_WORK_RATE_PER_MINUTE:-10000}"
export VERIFIER_WORK_BURST="${VERIFIER_WORK_BURST:-10000}"
# uv resolves the container project venv; --locked pins the gate lockfile.
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"
# The webui / model children read these from the environment.
export WEBUI_PROVISION_ADMIN_EMAIL WEBUI_PROVISION_ADMIN_PASSWORD WEBUI_PROVISION_PORT
export WEBUI_PROVISION_DATA_DIR MODEL_BACKEND_DEVICE MODEL_BACKEND_PORT VERIFIER_PORT
export WEBUI_PROVISION_WEBUI_BIN WEBUI_PROVISION_VERIFIER_URL WEBUI_PROVISION_MODEL_BACKEND_URL VERIFIER_MODEL_BASE_URL

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
  free_port "$VERIFIER_PORT"
  free_port "$MODEL_BACKEND_PORT"
  free_port "$WEBUI_PROVISION_PORT"
  wait 2>/dev/null || true
  rm -f "${LOG_DIR}/launch.pid"
  log "down; ports ${VERIFIER_PORT}/${MODEL_BACKEND_PORT}/${WEBUI_PROVISION_PORT} freed"
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
  [[ -x "$MODEL_BACKEND_PYTHON" ]] || die "${MODEL_BACKEND_PYTHON} missing -- see bench/README.md (or run --stub)"
  [[ -f "$INTEL_ACCEL_ENV" ]] || die "accel env not found: ${INTEL_ACCEL_ENV} (set INTEL_ACCEL_ENV, or run with --stub)"
  [[ -d "$OPENVINO_GENAI_PYTHON" ]] || die "OpenVINO GenAI python dir not found: ${OPENVINO_GENAI_PYTHON} (set OPENVINO_GENAI_PYTHON, or run with --stub)"
fi

# Refuse to start if a target port is already taken: keeps the readiness poll from adopting a
# foreign listener and keeps the fuser -k teardown scoped to this launcher's own children. This runs
# BEFORE the cleanup trap is installed so a refusal never fuser -k's the pre-existing listener.
for _port in "$VERIFIER_PORT" "$MODEL_BACKEND_PORT" "$WEBUI_PROVISION_PORT"; do
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

# 1) verifier
start_bg verifier "${LOG_DIR}/verifier.log" uv run --locked python -m verifier.service
wait_http verifier "http://${HEALTH_HOST}:${VERIFIER_PORT}/health" "$VERIFIER_READY_S" "$LAST_SERVICE_PID" "${LOG_DIR}/verifier.log" \
  || die "verifier did not become ready"

# 2) model tier -- deterministic stub XOR the real accel-backed model_backend
if (( USE_STUB )); then
  start_bg model "${LOG_DIR}/model.log" uv run --locked python -m webui stub
else
  # The single-quoted child script intentionally expands only inside the child bash.
  # shellcheck disable=SC2016
  start_bg model "${LOG_DIR}/model.log" \
    bash -c 'source "$1"; export PYTHONPATH="$2${PYTHONPATH:+:$PYTHONPATH}"; exec "$3" -m model_backend' \
    _accel "$INTEL_ACCEL_ENV" "$OPENVINO_GENAI_PYTHON" "$MODEL_BACKEND_PYTHON"
fi
wait_http model "http://${HEALTH_HOST}:${MODEL_BACKEND_PORT}/v1/models" "$MODEL_READY_S" "$LAST_SERVICE_PID" "${LOG_DIR}/model.log" \
  || die "model tier did not become ready"

# 3) Open WebUI
start_bg webui "${LOG_DIR}/webui.log" uv run --locked python -m webui serve
wait_http webui "http://${HEALTH_HOST}:${WEBUI_PROVISION_PORT}/ready" "$WEBUI_READY_S" "$LAST_SERVICE_PID" "${LOG_DIR}/webui.log" \
  || die "Open WebUI did not become ready"

# 4) provision Open WebUI (order is load-bearing: the verifier is up first so its OpenAPI is
#    re-fetched and its proposeSpec tool server is not dropped as unreachable).
log "provisioning Open WebUI (admin + model + verifier tool registration)..."
uv run --locked python -m webui bootstrap \
  || die "Open WebUI bootstrap failed (see output above and ${LOG_DIR}/webui.log)"

# 5) banner. With the real model, outcomes are prompt-driven: naming `dataset_name` sends a
#    request through the verifier to a rendered figure; a loose request yields a raw chart the guard
#    blocks. The --stub fixture proposes a known-good spec for every request, so it demonstrates only
#    the verified-render path.
succeeds_prompt="Plot a scatter chart of revenue versus orders. dataset_name: sales.csv"
blocked_prompt="Using sales.csv, plot a chart of revenue versus orders."
if (( USE_STUB )); then
  model_desc="deterministic stub (hardware-free)"
  printf -v try_typing '%s\n' \
    "    Try typing (either prompt):" \
    "      1) ${succeeds_prompt}" \
    "      2) ${blocked_prompt}" \
    "" \
    "           Both VERIFY -- the stub proposes a known-good spec for any request, so each renders a real" \
    "           figure inline. It cannot show the blocked path; relaunch on the real model (drop --stub)" \
    "           to watch prompt 2 get BLOCKED."
else
  model_desc="real local model on ${MODEL_BACKEND_DEVICE}"
  printf -v try_typing '%s\n' \
    "    Try typing:" \
    "      1) ${succeeds_prompt}" \
    "" \
    "           VERIFIES -- the verifier drafts the spec, recomputes the data, and every check passes," \
    "           so a real figure renders inline (a sandboxed frame), not just its code." \
    "" \
    "      2) ${blocked_prompt}" \
    "" \
    "           BLOCKED -- the model answers with its own unverified chart, so the Verified Plot Guard" \
    "           replaces it with a plain \"blocked\" notice."
fi
browser_url="http://${HEALTH_HOST}:${WEBUI_PROVISION_PORT}"
cat >&2 <<BANNER

  ============================================================
  READY -- verified-plot instance is up.

    Open       ${browser_url}
    Log in     ${WEBUI_PROVISION_ADMIN_EMAIL}  /  ${WEBUI_PROVISION_ADMIN_PASSWORD}
    Model      ${model_desc}

${try_typing}

    Logs       ${LOG_DIR}/{verifier,model,webui}.log
    Stop       Ctrl-C  (frees :${VERIFIER_PORT} / :${MODEL_BACKEND_PORT} / :${WEBUI_PROVISION_PORT})
  ============================================================

BANNER

# 6) Block until a REQUIRED service exits. SIGINT/SIGTERM are handled by their own traps (which exit
#    130/143 before returning here); getting past `wait -n` means a child died on its own -- a
#    failure. Name it and exit non-zero so automation never reads a crashed stack as a clean launch;
#    the EXIT trap still tears everything down.
service_rc=0
wait -n 2>/dev/null || service_rc=$?
dead_service=""
for _i in "${!SERVICE_PIDS[@]}"; do
  if ! kill -0 "${SERVICE_PIDS[$_i]}" 2>/dev/null; then
    dead_service="${SERVICE_NAMES[$_i]}"
    break
  fi
done
log "service ${dead_service:-unknown} exited (status ${service_rc}); tearing down"
# Subshell exit, not a bare top-level `exit`: the latter trips ShellCheck SC2317 ("unreachable")
# on the EXIT-trap-only helpers; `set -e` still propagates this status to the parent, whose EXIT
# trap runs the teardown.
(exit "$(( service_rc == 0 ? 1 : service_rc ))")
