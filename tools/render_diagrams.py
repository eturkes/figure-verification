# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Render every `docs/diagrams/*.dot` to its sibling `.svg` with Graphviz.

    uv run --locked python tools/render_diagrams.py

`dot -Tsvg:cairo` draws text as glyph outlines, so a Japanese label shows the same on a viewer
without Noto Sans CJK JP (GitHub serves the SVG through `<img>`, which loads no web font). Each SVG
carries its source verbatim in a comment after the XML declaration;
`tests/test_verification_docs.py` compares that copy with the `.dot` file, so the gate catches a
source edited without a re-render and needs no Graphviz itself. Graphviz = a host binary
from the system package manager; the comment records its version.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIAGRAMS = ROOT / "docs" / "diagrams"
MARKER = "<!-- source: "


def render(source: Path, version: str) -> str:
    text = source.read_text(encoding="utf-8")
    if "--" in text:
        sys.exit(f"{source}: '--' cannot sit inside an XML comment")
    svg = subprocess.run(  # noqa: S603 - fixed argv
        ["dot", "-Tsvg:cairo", str(source)],  # noqa: S607 - Graphviz from PATH
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    declaration, rest = svg.split("\n", 1)
    name = source.relative_to(ROOT).as_posix()
    return f"{declaration}\n{MARKER}{name} ({version})\n{text}-->\n{rest}"


def main() -> None:
    version = subprocess.run(
        ["dot", "-V"],  # noqa: S607 - Graphviz from PATH
        capture_output=True,
        check=True,
        text=True,
    ).stderr.strip()
    for source in sorted(DIAGRAMS.glob("*.dot")):
        target = source.with_suffix(".svg")
        target.write_text(render(source, version), encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)}")  # noqa: T201 - CLI report


if __name__ == "__main__":
    main()
