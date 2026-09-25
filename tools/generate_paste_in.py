# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Write the production paste-in artifacts, or check the committed ones against their sources.

A bare run rewrites every artifact `webui.paste_in.bundle.ARTIFACTS` names. `--check` writes
nothing and exits 1 naming each path whose committed bytes differ from a fresh render.

`--check` is what makes the hand-fork ban enforceable rather than aspirational: the pasted artifact
and the tracked sources are the same code by construction, and an edit made in the artifact is
reported as drift on the next gate run instead of surviving as a silent second copy.

Generation is deterministic in the tracked sources -- one emission order, one embedding transform,
no clock, no environment -- so a rerun on an already-current tree writes byte-identical files.
"""

import sys
from pathlib import Path

# `webui` is an uninstalled repo-root package -- the wheel builds `src/verifier` alone -- and a
# script run by path puts its OWN directory on `sys.path`, never the repo root. pytest supplies the
# same entry through `pythonpath = ["tests", "."]`; a command-line run has to state it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui.paste_in.bundle import (
    ARTIFACTS,
    CAPTURE_TEMPLATE_SOURCE,
    BundleError,
    generated_template_source,
    render,
    repo_root,
)


def _artifact_text(module: str) -> str:
    """Render one artifact, turning an unembeddable source into a loud non-zero exit."""
    try:
        return render(module)
    except BundleError as exc:
        sys.stderr.write(f"cannot generate {module}: {exc}\n")
        raise SystemExit(1) from exc


def main(argv: list[str]) -> int:
    check = argv == ["--check"]
    if argv and not check:
        sys.stderr.write(f"usage: {Path(__file__).name} [--check]\n")
        return 2

    root = repo_root()
    drifted: list[str] = []
    outputs = [(CAPTURE_TEMPLATE_SOURCE, generated_template_source())]
    outputs.extend(
        (relative, _artifact_text(module)) for relative, module in sorted(ARTIFACTS.items())
    )
    for relative, text in outputs:
        target = root / relative
        if check:
            current = target.read_text(encoding="utf-8") if target.is_file() else None
            if current != text:
                drifted.append(relative)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        sys.stdout.write(f"wrote {relative} ({len(text.encode())} bytes)\n")

    if drifted:
        sys.stderr.write(
            "committed artifact(s) differ from their sources; rerun without --check: "
            f"{', '.join(drifted)}\n"
        )
        return 1
    if check:
        sys.stdout.write(f"{len(ARTIFACTS)} artifact(s) current\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
