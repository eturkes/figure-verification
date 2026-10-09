# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The anchoring suites' verdict over the figure path (M19.7b re-root).

The host reader runs the program beside its CSV (`data.csv` in a scratch working directory, the
Japanese test font when the program or the file holds non-ASCII text); the judge decides with that
file, the request, the anchoring rule and the admin aliases (`.claude/rules/figure.md` § Columns).
"""

import contextlib
import tempfile
from pathlib import Path

from verifier.figure import reader
from verifier.figure.anchoring import Aliases, Anchoring
from verifier.figure.description import parse_description
from verifier.figure.judge import Passed, Sources, judge

PASSED = "VERIFIED"
_NAME = "data.csv"
_FONT = Path(__file__).resolve().parent / "fonts" / "NotoSansJP-subset.ttf"


def verdict(
    program: str,
    request: str | None,
    content: bytes,
    *,
    anchoring: Anchoring | None = None,
    aliases: Aliases = (),
) -> str:
    """`VERIFIED`, or the reason the judge blocks the figure; no rule = `Sources`' own default."""
    font = None if program.isascii() and content.isascii() else str(_FONT)
    with tempfile.TemporaryDirectory() as scratch, contextlib.chdir(scratch):
        Path(_NAME).write_bytes(content)
        described = parse_description(reader.run(program, font))
    assert described is not None
    files = ((_NAME, content),)
    sources = (
        Sources(files, request, aliases=aliases)
        if anchoring is None
        else Sources(files, request, anchoring, aliases)
    )
    result = judge(described, sources)
    return PASSED if isinstance(result, Passed) else result.reason
