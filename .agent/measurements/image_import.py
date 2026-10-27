# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M21.2 F11: the generated pairs inside the official Open WebUI image, network off.

Host leg: the reader draws each banner arm's program (host matplotlib, the CSV beside it, the test
font for Japanese text) and keeps its description line. Image leg (`image_leg.py`, podman): the
image's own interpreter imports both pairs, constructs `Tools` + `Filter`, and judges every arm
with the filter's embedded judge and anchoring. Q74: it also cuts both test fonts for the
Japanese clinic arm with each filter's embedded stdlib cut; the host compares those bytes with its
own `fonts.cut_for` (CPython 3.11 in the image, no fontTools, vs the host's 3.14).
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from verifier.figure import reader
from verifier.figure.description import TAG
from webui.paste_in.fonts import cut_for

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
FONT = PROJECT / "tests/fonts/NotoSansJP-subset.ttf"
CUT_FONTS = ("NotoSansJP-subset.ttf", "NotoSansCJKjp-subset.otf")


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
        clinic = next(arm for arm in arms if arm["id"] == "ja-clinic-simple")
        cut_input = {"program": clinic["program"], "files": [clinic["dataset"]], "fonts": CUT_FONTS}
        (work / "cut.json").write_text(json.dumps(cut_input, ensure_ascii=False))
        contents = [(work / name).read_bytes() for name in cut_input["files"]]
        host_cuts = {}
        for font in CUT_FONTS:
            whole = (PROJECT / "tests/fonts" / font).read_bytes()
            shutil.copy(PROJECT / "tests/fonts" / font, work / font)
            cut = cut_for(whole, clinic["program"], contents)
            host_cuts[font] = [hashlib.sha256(cut).hexdigest(), len(cut), len(whole)]
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
    # Q74: each pair's in-image cut equals the host's, and is smaller than the font.
    result["cut_equals_host"] = {
        font: {
            pair: digest_size == host_cuts[font][:2] and host_cuts[font][1] < host_cuts[font][2]
            for pair, digest_size in pairs.items()
        }
        for font, pairs in result.pop("cuts").items()
    }
    Path(out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the generated files inside the official Open WebUI image, network off."
    )
    parser.add_argument("image", help="the Open WebUI image reference")
    parser.add_argument("out", help="the result JSON file")
    arguments = parser.parse_args()
    main(arguments.image, arguments.out)
