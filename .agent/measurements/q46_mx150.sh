#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#
# Q46 live MX150 probe: start the backend from .venv-model, send one fixed short prompt and one
# fixed chart prompt three times each at temperature 0 (content SHA-256 per reply), then run the
# smoke probe three times (tok/s + GPU temperature and clock). Holds port 8001 and the dGPU.
#
#     bash .agent/measurements/q46_mx150.sh <out-prefix>          # short + long + smoke
#     LONG=' ' bash .agent/measurements/q46_mx150.sh <out-prefix> # short + smoke (cool start)
set -uo pipefail
out=$1
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." || exit 1
.venv-model/bin/python -m model_backend >"$out.server.log" 2>&1 &
pid=$!
for _ in $(seq 1 120); do
    curl -sS -o /dev/null http://127.0.0.1:8001/v1/models 2>/dev/null && break
    sleep 1
done
digest='import hashlib, json, sys
body = json.loads(open(sys.argv[1]).read().split("\n")[0])
text = body["choices"][0]["message"]["content"]
tokens = body["usage"]["completion_tokens"]
print(sys.argv[2], hashlib.sha256(text.encode()).hexdigest(), tokens, "tokens")'
for i in 1 2 3; do
    curl -sS http://127.0.0.1:8001/v1/chat/completions -H 'content-type: application/json' \
        -d '{"messages":[{"role":"system","content":"Reply with one Python statement only."},{"role":"user","content":"Print the sum of 2 and 3."}],"temperature":0.0,"max_tokens":64}' \
        >"$out.short$i.json"
    python3 -c "$digest" "$out.short$i.json" "short$i"
done
for i in ${LONG:-1 2 3}; do
    curl -sS http://127.0.0.1:8001/v1/chat/completions -H 'content-type: application/json' \
        -d '{"messages":[{"role":"user","content":"Write a complete Python program that reads /mnt/uploads/sales.csv with pandas and draws a bar chart of total revenue by region with matplotlib."}],"temperature":0.0,"max_tokens":512}' \
        -w '\n%{time_total}\n' >"$out.long$i.json"
    python3 -c "$digest" "$out.long$i.json" "long$i"
    printf 'long%s seconds=%s\n' "$i" "$(sed -n 2p "$out.long$i.json")"
done
for _ in 1 2 3; do
    .venv-model/bin/python -m model_backend.smoke
    nvidia-smi --query-gpu=temperature.gpu,clocks.sm --format=csv,noheader
done
kill "$pid"
wait "$pid" 2>/dev/null
exit 0
