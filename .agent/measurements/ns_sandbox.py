# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""NS (Q82.2): every rule-corpus case through the nucllei sandbox, as the nucllei tool sends it.

`uv run --locked python .agent/measurements/ns_sandbox.py [<image>]` starts the sandbox image
(default `localhost/nucllei-sandbox:v20261020-01`, built from nucllei's tag with
`sudo podman build --network=host`; privileged, as nucllei deploys it: nsjail + quota loop
devices) on a free loopback port with a fresh token, records the jail's interpreter + plotting
releases, then posts each case to `/exec` exactly as `nucllei_skill.run.exec_payload` builds it:
the production wrapper (the jail's Japanese font found as the tool finds it), the program with
`{data}` + `{corpus}` at `/workspace/imports`, every file it names imported. Writes `ns-host.json`
(each case's Sources + the host verdict) and `ns-sandbox.json` (each jail stdout's description
line + faults); the NS projector judges every jail description with the same Sources.
"""

import json
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
sys.path[:0] = [str(PROJECT / "src"), str(PROJECT)]

from nucllei_skill import run as jail  # noqa: E402
from nucllei_skill.host import Attachment  # noqa: E402
from verifier.figure import reader  # noqa: E402
from verifier.figure.description import TAG, parse_description  # noqa: E402
from verifier.figure.judge import Passed, Sources, judge  # noqa: E402

IMAGE = "localhost/nucllei-sandbox:v20261020-01"
CORPUS = PROJECT / "tests" / "figure_corpus"
DATA = PROJECT / "data"
NAMED = re.compile(r"\{(?:data|corpus)\}/([^'\"\s)]+)")
VERSIONS = (
    "import sys, matplotlib, pandas, numpy, seaborn\n"
    "print(sys.version.split()[0], matplotlib.__version__, pandas.__version__,"
    " numpy.__version__, seaborn.__version__)\n"
)


def cases():
    for path in sorted(CORPUS.glob("*.toml")):
        yield from tomllib.loads(path.read_text(encoding="utf-8"))["case"]


def file_bytes(name):
    path = DATA / name
    return (path if path.is_file() else CORPUS / name).read_bytes()


def host_verdict(case):
    local = case["program"].replace("{data}", str(DATA)).replace("{corpus}", str(CORPUS))
    described = parse_description(reader.run(local))
    if described is None:
        return None
    files = () if "csv" not in case else ((case["csv"], file_bytes(case["csv"])),)
    outcome = judge(described, Sources(files, case.get("request"), case.get("anchoring", "strict")))
    return "pass" if isinstance(outcome, Passed) else outcome.reason


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def post(port, token, payload, timeout):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/exec",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read())


def main(image):
    podman, sudo = shutil.which("podman"), shutil.which("sudo")
    if podman is None or sudo is None:
        sys.exit("podman + sudo required")
    port, token, name = free_port(), secrets.token_hex(16), f"fv-ns-{secrets.token_hex(4)}"
    subprocess.run(  # noqa: S603 -- resolved podman, closed argv
        [sudo, podman, "run", "-d", "--rm", "--name", name, "--privileged", "-p",
         f"127.0.0.1:{port}:8000", "-e", f"SANDBOX_TOKEN={token}", image],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 120
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)
        probe = post(port, token, {"user_id": "ns", "lang": "python", "code": VERSIONS}, 120)
        versions = dict(
            zip(
                ("python", "matplotlib", "pandas", "numpy", "seaborn"),
                probe["stdout"].split(),
                strict=True,
            )
        )
        host, sandbox = {}, {}
        for case in cases():
            names = sorted(
                {*NAMED.findall(case["program"]), *([case["csv"]] if "csv" in case else [])}
            )
            program = case["program"].replace("{data}", "/workspace/imports")
            program = program.replace("{corpus}", "/workspace/imports")
            attachments = [Attachment(n, file_bytes(n)) for n in names]
            payload = jail.exec_payload("ns", program, attachments)
            try:
                stdout = jail.reply_stdout(post(port, token, payload, jail.HTTP_TIMEOUT_SECONDS))
                line = next((l for l in stdout.splitlines() if l.startswith(TAG)), None)  # noqa: E741
                sandbox[case["id"]] = {"description": line, "fault": None}
            except jail.ReplyFaultError as fault:
                sandbox[case["id"]] = {"description": None, "fault": fault.reason}
            host[case["id"]] = {
                "expect": case["expect"],
                "csv": case.get("csv"),
                "request": case.get("request"),
                "anchoring": case.get("anchoring", "strict"),
                "verdict": host_verdict(case),
            }
    finally:
        subprocess.run([sudo, podman, "stop", "-t", "5", name], check=False, capture_output=True)  # noqa: S603
    (ROOT / "ns-host.json").write_text(json.dumps(host, indent=1, sort_keys=True) + "\n")
    out = {"image": image, "versions": versions, "results": sandbox}
    (ROOT / "ns-sandbox.json").write_text(json.dumps(out, sort_keys=True) + "\n")
    print(json.dumps({"cases": len(host), "versions": versions}))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else IMAGE)
