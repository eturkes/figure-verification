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
    "S6",
    "T3",
    "T4",
    "T5",
    "T6",
    "T7",
    "T8",
    "F7",
    "Versions",
    "M15",
    "M16",
    "M17",
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
    "I1",
    "I2",
    "I3",
    "C1",
    "NS",
    "X1",
    "Image",
)
# M21.2 F11: the official image the shipped pair targets (podman, network off).
IMAGE = "ghcr.io/open-webui/open-webui:v0.12.3"
# Host-only ids whose script name is not `<id lower>.py` and takes no pandas pin.
HOST_ONLY = {
    "I2": "i2_ambiguity.py",
    "X1": "x1_transforms.py",
    # Q82.2: the nucllei sandbox image, started by the script itself (sudo podman, privileged).
    "NS": "ns_sandbox.py",
}
# Every Node leg runs in the installed Open WebUI bundle (Pyodide 314.0.3), the sandbox production
# ships; M19 ids pair it with a host leg.
BUILD_PAIRS = (("owui", "31403"),)
BUNDLE_PAIRS = {
    "I1": ("i1_census.py", "i1_pyodide.mjs", "i1-31403.json"),
    "I3": ("i3_export.py", "i3_pyodide.mjs", "i3-31403.json"),
    "C1": ("c1_export.py", "c1_pyodide.mjs", "c1-31403.json"),
}
M17_ARMS = {
    "ja-simple": "sales.csv",
    "ja-misleading": "sales.csv",
    "ja-clinic-simple": "clinic_ja.csv",
    "ja-clinic-misleading": "clinic_ja.csv",
}
GENERATORS = {
    "S6": (("make_s6_csv.py", True),),
    "T6": (("make_s6_csv.py", True),),
    "T7": (("t7_profile.py", True), ("t7_quoted.py", True)),
    "T8": (("make_t8_inputs.py", False), ("t8_profile.py", True)),
}
NODE_SCRIPTS = {
    "S6": "s6_pyodide.mjs",
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


def setting(name):
    """`name` from the environment, else from the repository's gitignored `.env` (`KEY=VALUE`)."""
    if os.environ.get(name):
        return os.environ[name]
    dotenv = PROJECT / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip().removeprefix("export ").strip() == name:
                return value.strip().strip("'\"") or None
    return None


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
        self.bundle = self.webui_env / "lib/python3.11/site-packages/open_webui/frontend/pyodide"

    def python(self, script, *args, pandas=False):
        options = ["--with", "pandas==3.0.2"] if pandas else []
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
            chrome = setting("CHROME")
            if not chrome:
                fail("CHROME unset: set it in the environment or .env to a Chromium binary")
            browser_path = executable(chrome)
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
                except OSError, urllib.error.URLError:
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
        elif name == "M16":
            dump = DATA / "checks.json"
            self.run("checks-dump", self.python("m16u1_dump.py", dump))
            args = [csv, str(dump), str(DATA / "m16")]
            script = "m16u1_checks.mjs"
        else:
            # M17.4: one stub-arm attempt per Japanese banner prompt, each over its own CSV.
            for arm, dataset in M17_ARMS.items():
                self.run(
                    f"M17-{arm}",
                    [
                        "node",
                        str(ROOT / "m10u3_demo.mjs"),
                        browser_url,
                        webui_url,
                        str(PROJECT / "data" / dataset),
                        arm,
                        "1",
                        str(DATA / "m17"),
                    ],
                )
            return
        self.run(name, ["node", str(ROOT / script), browser_url, webui_url, *args])

    def measurement(self, name):
        for script, pandas in GENERATORS.get(name, ()):
            self.run(script, self.python(script, pandas=pandas))
        if name in NODE_SCRIPTS:
            script = NODE_SCRIPTS[name]
            for package, build in BUILD_PAIRS:
                self.run(
                    f"{name}-{build}",
                    ["node", str(ROOT / script), package, f"{name.lower()}-{build}.json"],
                )
        elif name in ("M15", "M16", "M17"):
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
                    str(ROOT / "f7-31403.json"),
                ],
            )
        elif name in BUNDLE_PAIRS:
            host, node, result = BUNDLE_PAIRS[name]
            self.run(f"{name}-host", self.python(host))
            self.run(name, ["node", str(ROOT / node), "owui", result])
        elif name == "Image":
            self.run(name, self.python("image_import.py", IMAGE, ROOT / "image-0123.json"))
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


def cli_contract():
    """Every harness answers `--help` (rc 0, `usage:`) and refuses an unknown argument (rc 2)
    before it measures; a full replay runs this first."""
    env = {**os.environ, "PYTHONPATH": str(PROJECT)}
    broken = []
    for script in sorted(ROOT.glob("*.py")):
        runs = [
            subprocess.run(  # noqa: S603 - fixed argv
                [sys.executable, str(script), argument],
                cwd=PROJECT,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            for argument in ("--help", "--no-such-option")
        ]
        if not (
            runs[0].returncode == 0
            and runs[0].stdout.startswith("usage:")
            and runs[1].returncode == 2
            and "error:" in runs[1].stderr
        ):
            broken.append(script.name)
    if broken:
        fail(f"no --help or unknown-argument refusal: {', '.join(broken)}")


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
        if replay and not args.ids:
            try:
                cli_contract()
                print("cli: PASS", flush=True)
            except RuntimeError as exc:
                failures += 1
                print(f"cli: FAIL {exc}", file=sys.stderr, flush=True)
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
