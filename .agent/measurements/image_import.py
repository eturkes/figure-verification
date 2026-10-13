# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M21.2 F11: the generated pairs inside the official Open WebUI image, network off.

Host leg: the reader draws each banner arm's program (host matplotlib, the CSV beside it, the test
font for Japanese text) and keeps its description line. Image leg (`image_leg.py`, podman): the
image's own interpreter imports both pairs, constructs `Tools` + `Filter`, and judges every arm
with the filter's embedded judge and anchoring.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from verifier.figure import reader
from verifier.figure.description import TAG

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
FONT = PROJECT / "tests/fonts/NotoSansJP-subset.ttf"


def described(program, dataset):
    font = None if program.isascii() else str(FONT)
    with tempfile.TemporaryDirectory() as scratch:
        shutil.copy(PROJECT / "data" / dataset, Path(scratch) / dataset)
        output = reader.run(program.replace("/mnt/uploads/", f"{scratch}/"), font)
    return next(line for line in output.splitlines() if line.startswith(TAG))


def main(image, out):
    arms = json.loads((PROJECT / "webui/banner.json").read_text())["arms"]
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        shutil.copytree(PROJECT / "paste-in", work / "production")
        shutil.copytree(PROJECT / "webui/demo-paste-in", work / "demo")
        shutil.copy(ROOT / "image_leg.py", work)
        for arm in arms:
            shutil.copy(PROJECT / "data" / arm["dataset"], work)
            arm["description"] = described(arm["program"], arm["dataset"])
        (work / "arms.json").write_text(json.dumps(arms, ensure_ascii=False))
        stdout = subprocess.check_output(  # noqa: S603 -- resolved podman, closed argv
            [
                shutil.which("podman") or "podman",
                "run",
                "--rm",
                "--network=none",
                "--entrypoint=python",
                "--env=PYTHONPATH=/app/backend",
                f"--volume={work}:/w:ro,Z",
                image,
                "/w/image_leg.py",
                "/w",
            ],
            text=True,
        )
    result = {"image": image, **json.loads(stdout.splitlines()[-1])}
    Path(out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main(*sys.argv[1:3])
