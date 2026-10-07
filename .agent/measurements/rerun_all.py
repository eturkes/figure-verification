# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Replay every README id, including a private stub stack; compare independent projections."""

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from check import difference

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
DATA = ROOT / "all-data"
IDS = (
    "S1",
    "S2",
    "S3",
    "S6",
    "S7",
    "T3",
    "T4",
    "T5",
    "T6",
    "T7",
    "T8",
    "W1",
    "A1",
    "A2",
    "A3",
    "A4",
    "H1",
    "F7",
    "O8",
    "Versions",
    "M15",
    "M16",
    "R1",
    "R2",
    "R3",
    "R4",
    "R5",
    "R7",
    "R8",
    "R-ACCEL",
    "R-PORT",
    "R-BAR",
)
# Host-only ids whose script name is not `<id lower>.py` and takes no pandas pin.
HOST_ONLY = {
    "A1": "a1_anchor.py",
    "A2": "a2_labels.py",
    "A3": "a3_short_names.py",
    "A4": "a4_aliases.py",
    "H1": "h1_heldout_anchoring.py",
    "S1": "s1_host.py",
}
BUILD_PAIRS = (("pyodide", "0280"), ("pyodide0281", "0281"))
GENERATORS = {
    "S2": (("make_s2_inputs.py", False),),
    "S3": (("make_s3_grids.py", False),),
    "S6": (("make_s6_csv.py", True),),
    "S7": (("make_s7_pow.py", False), ("s7_mapping.py", False)),
    "T6": (("make_s6_csv.py", True),),
    "T7": (("t7_profile.py", True), ("t7_quoted.py", True)),
    "T8": (("make_t8_inputs.py", False), ("t8_profile.py", True)),
    "O8": (("make_s2_inputs.py", False), ("make_s7_pow.py", False)),
}
NODE_SCRIPTS = {
    "S2": "s2_pyodide.mjs",
    "S3": "s3_pyodide.mjs",
    "S6": "s6_pyodide.mjs",
    "S7": "s7_pyodide.mjs",
    "T6": "t6_pyodide.mjs",
    "T7": "t7_pyodide.mjs",
    "T8": "t8_pyodide.mjs",
    "Versions": "versions.mjs",
}


def fail(message):
    raise RuntimeError(message)


def executable(name):
    path = shutil.which(name)
    if path is None:
        fail(f"Missing executable: {name}")
    return path


def free_ports():
    sockets = [socket.socket() for _ in range(4)]
    try:
        for sock in sockets:
            sock.bind(("127.0.0.1", 0))
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def compare(name):
    try:
        expected = json.loads((ROOT / "expected" / f"{name}.json").read_text())
        actual = json.loads((ROOT / "results" / f"{name}.json").read_text())
        mismatch = difference(expected, actual)
    except (OSError, ValueError) as exc:
        mismatch = str(exc)
    if mismatch:
        raise ValueError(mismatch)


class Replay:
    def __init__(self):
        self.env = {
            **os.environ,
            "UV_PROJECT_ENVIRONMENT": str(PROJECT / ".venv"),
            "UV_LINK_MODE": "copy",
            "PYTHONPATH": f"{PROJECT / 'src'}:{PROJECT}",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.cache = {}
        self.processes = []
        self.handles = []
        self.live = None
        self.live_error = None
        self.state = PROJECT / ".scratch/measurements-live"
        DATA.mkdir(exist_ok=True)
        common = subprocess.check_output(  # noqa: S603 -- resolved git executable, constant args
            [executable("git"), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=PROJECT,
            text=True,
        ).strip()
        self.webui_env = Path(common).parent / ".venv-webui"
        self.bundle = self.webui_env / "lib/python3.12/site-packages/open_webui/frontend/pyodide"

    def python(self, script, *args, pandas=False):
        options = ["--with", "pandas==2.3.1"] if pandas else []
        return [
            "uv",
            "run",
            "--locked",
            "--project",
            str(PROJECT),
            *options,
            "python",
            str(ROOT / script),
            *map(str, args),
        ]

    def run(self, label, command, stdout=None):
        key = tuple(command)
        if key not in self.cache:
            output = stdout or DATA / f"{label}.log"
            error = DATA / f"{label}.stderr.log"
            with output.open("w") as stream, error.open("w") as errors:
                result = subprocess.run(  # noqa: S603 -- closed harness argv, no shell
                    command,
                    cwd=PROJECT,
                    env=self.env,
                    stdout=stream,
                    stderr=errors,
                    check=False,
                )
            self.cache[key] = (result.returncode, output, error)
        rc, output, error = self.cache[key]
        if rc:
            fail(f"{label} rc={rc}; logs={output}, {error}")

    def start(self, name, command, env):
        handle = (DATA / f"{name}.log").open("w")
        self.handles.append(handle)
        process = subprocess.Popen(  # noqa: S603 -- closed local launcher/browser argv
            command,
            cwd=PROJECT,
            env=env,
            stdout=handle,
            stderr=handle,
            start_new_session=True,
        )
        self.processes.append(process)
        print(f"started {name} pid={process.pid}", flush=True)
        return process

    def start_live(self):
        if self.live_error:
            raise RuntimeError(self.live_error)
        if self.live:
            return self.live
        try:
            verifier, model, webui, browser_port = free_ports()
            self.state.mkdir(parents=True, exist_ok=True)
            readonly_bin = self.state / "open-webui"
            readonly_bin.write_text(
                "#!/usr/bin/env bash\n# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception\n"
                f"exec {shlex.quote(str(self.webui_env / 'bin/python'))} -B "
                f'{shlex.quote(str(self.webui_env / "bin/open-webui"))} "$@"\n'
            )
            readonly_bin.chmod(0o700)
            stack_env = {
                **self.env,
                "VERIFIER_PORT": str(verifier),
                "MODEL_BACKEND_PORT": str(model),
                "WEBUI_PROVISION_PORT": str(webui),
                "WEBUI_PROVISION_DATA_DIR": str(self.state / "webui"),
                "VERIFIER_STATE_DIR": str(self.state / "verifier"),
                "LAUNCH_LOG_DIR": str(self.state / "logs"),
                "WEBUI_PROVISION_WEBUI_BIN": str(readonly_bin),
            }
            stack = self.start(
                "stack", ["bash", str(PROJECT / "webui/launch.sh"), "--stub"], stack_env
            )
            deadline = time.monotonic() + 240
            while "READY --" not in (DATA / "stack.log").read_text():
                if stack.poll() is not None or time.monotonic() >= deadline:
                    fail(f"stub stack not ready; rc={stack.poll()}; log={DATA / 'stack.log'}")
                time.sleep(1)
            browser_path = subprocess.check_output(  # noqa: S603 -- resolved chromiumfish, constant args
                [executable("chromiumfish"), "path"], text=True
            ).strip()
            browser = self.start(
                "browser",
                [
                    browser_path,
                    "--headless",
                    f"--remote-debugging-port={browser_port}",
                    f"--user-data-dir={self.state / 'browser'}",
                    "--disable-features=IsolateSandboxedIframes",
                    "--window-size=1280,900",
                    "about:blank",
                ],
                self.env,
            )
            browser_url = f"http://127.0.0.1:{browser_port}"
            deadline = time.monotonic() + 30
            while True:
                if browser.poll() is not None or time.monotonic() >= deadline:
                    fail(f"browser not ready; rc={browser.poll()}; log={DATA / 'browser.log'}")
                try:
                    with urllib.request.urlopen(f"{browser_url}/json/version", timeout=2):  # noqa: S310 -- loopback CDP only
                        break
                except (OSError, urllib.error.URLError):
                    time.sleep(1)
            self.env.update(
                FV_WEBUI_EMAIL="operator@localhost",
                FV_WEBUI_PASSWORD="loopback-dev-password",  # noqa: S106 -- private loopback stub credential
            )
            self.env.pop("FV_CASES", None)
            self.live = (browser_url, f"http://127.0.0.1:{webui}")
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self.live_error = str(exc)
            raise
        return self.live

    def live_measurement(self, name):
        browser_url, webui_url = self.start_live()
        csv = str(PROJECT / "data/sales.csv")
        if name == "M15":
            dump = DATA / "reasons.json"
            self.run(
                "reasons",
                [
                    "uv",
                    "run",
                    "--locked",
                    "python",
                    "-c",
                    "import json; from webui.paste_in.reasons import REASONS; "
                    "print(json.dumps(REASONS, ensure_ascii=False))",
                ],
                stdout=dump,
            )
            args = [csv, str(dump), str(self.state / "logs/webui.log"), str(DATA / "m15")]
            script = "m15u1_status.mjs"
        else:
            dump = DATA / "checks.json"
            self.run("checks-dump", self.python("m16u1_dump.py", dump))
            args = [csv, str(dump), str(DATA / "m16")]
            script = "m16u1_checks.mjs"
        self.run(name, ["node", str(ROOT / script), browser_url, webui_url, *args])

    def measurement(self, name):
        for script, pandas in GENERATORS.get(name, ()):
            self.run(script, self.python(script, pandas=pandas))
        if name in NODE_SCRIPTS:
            script = NODE_SCRIPTS[name]
            builds = (*BUILD_PAIRS, ("owui", "0283")) if name == "T8" else BUILD_PAIRS
            for package, build in builds:
                self.run(
                    f"{name}-{build}",
                    ["node", str(ROOT / script), package, f"{name.lower()}-{build}.json"],
                )
        elif name in ("M15", "M16"):
            self.live_measurement(name)
        elif name.startswith("R"):
            self.run("reductions", ["bash", str(ROOT / "r_run.sh")])
            return
        elif name == "F7":
            self.run(
                name,
                [
                    "node",
                    str(ROOT / "f7_wrapper.mjs"),
                    str(self.bundle),
                    str(ROOT / "f7-0283.json"),
                ],
            )
        elif name == "O8":
            for script, output in (
                ("s2_pyodide.mjs", "s2-0283.json"),
                ("s7_pyodide.mjs", "s7-0283.json"),
            ):
                self.run(output, ["node", str(ROOT / script), "owui", output])
            self.run(
                name,
                [
                    "node",
                    str(ROOT / "o8_observe.mjs"),
                    "owui",
                    "o8-0283.json",
                    "wrapper",
                    "--check-fixtures",
                ],
            )
        elif name == "W1":
            self.run(
                name, self.python("w1_width.py", PROJECT / "corpus/python/captures/m10-design")
            )
        elif name in HOST_ONLY:
            self.run(name, self.python(HOST_ONLY[name]))
        else:
            self.run(name, self.python(f"{name.lower()}.py", pandas=True))
        self.run(f"project-{name}", self.python("all_results.py", name))

    def close(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            print(f"stopped pid={process.pid} rc={process.returncode}", flush=True)
        for handle in self.handles:
            handle.close()
        if (self.state / "logs").exists():
            shutil.copytree(self.state / "logs", DATA / "stack-logs", dirs_exist_ok=True)
        # Only this runner's state is removed; measurement evidence and logs stay in all-data/.
        shutil.rmtree(self.state, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description="Replay measurements and check their published claims."
    )
    parser.add_argument("ids", nargs="*", choices=IDS, help="run these identifiers; default: all")
    parser.add_argument(
        "--check-only", action="store_true", help="compare existing results without replaying"
    )
    args = parser.parse_args()
    documented = set(
        re.findall(r"^\| ([A-Z][A-Za-z0-9-]*) \|", (ROOT / "README.md").read_text(), re.MULTILINE)
    )
    expected = {path.stem for path in (ROOT / "expected").glob("*.json")}
    if documented != set(IDS) or expected != set(IDS):
        parser.error(
            f"id inventory drift: README={sorted(documented)}, "
            f"expected={sorted(expected)}, driver={sorted(IDS)}"
        )
    ids = args.ids or IDS
    replay = None if args.check_only else Replay()
    failures = 0
    try:
        if replay:
            for name in ids:
                (ROOT / "results" / f"{name}.json").unlink(missing_ok=True)
        for name in ids:
            try:
                if replay:
                    print(f"{name}: REPLAY", flush=True)
                    replay.measurement(name)
                compare(name)
                print(f"{name}: PASS", flush=True)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                failures += 1
                print(f"{name}: FAIL {exc}", file=sys.stderr, flush=True)
    finally:
        if replay:
            replay.close()
    return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
