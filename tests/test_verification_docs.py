# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.3 D3-D7 + D9, re-keyed by M19.5: the python-mode reference names every check, reason +
limit.

Contracts: `.agent/archive/contracts/m18u3.md`, `.agent/archive/contracts/m19u5.md` (W6). The
reference is what each "Show checks" row links to, so it must move with the code: a check, a reason
or a limit added without its sentence here fails this module. Presence is all a token scan decides;
whether a sentence is TRUE stays the closing review's (D8). D5 (every admitted Python name) retired
with the static admission path.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import get_args

import pytest

from verifier.figure import explain, reader, request
from verifier.figure.reasons import FigureReason
from verifier.pysrc.limits import DEFAULT_LIMITS
from webui.paste_in import checks
from webui.paste_in import filter as filter_module
from webui.paste_in.reasons import OutletCause

_ROOT = Path(__file__).resolve().parents[1]
_DOCS = {"en": _ROOT / "docs/verification.md", "ja": _ROOT / "docs/verification.ja.md"}
_ANCHOR = re.compile(r'<a id="check-([a-z]+)"></a>')
_HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)\s]*)?\)")


def _text(language: str) -> str:
    return _DOCS[language].read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    """Check id -> the text from its anchor to the next anchor or the next H2."""
    marks = list(_ANCHOR.finditer(text))
    sections: dict[str, str] = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        body = text[mark.end() : end]
        cut = body.find("\n## ")
        sections[mark.group(1)] = body if cut < 0 else body[:cut]
    return sections


@pytest.mark.parametrize("language", ["en", "ja"])
def test_d3_each_check_has_its_anchor_and_title(language: str) -> None:
    """D3: 9 `check-<id>` anchors in CHECKS order, each before its TEXTS title heading."""
    text = _text(language)
    assert [mark.group(1) for mark in _ANCHOR.finditer(text)] == list(checks.CHECKS)
    column = 0 if language == "en" else 1
    sections = _sections(text)
    for check in checks.CHECKS:
        heading = _HEADING.search(sections[check])
        assert heading is not None, check
        assert checks.TEXTS[check][column][0] in heading.group(1), (check, heading.group(1))


@pytest.mark.parametrize("language", ["en", "ja"])
def test_d4_each_reason_sits_in_its_check_section(language: str) -> None:
    """D4: all 51 reasons (39 figure + 12 outlet), each inside its CHECK_OF section only."""
    reasons = set(get_args(FigureReason)) | set(get_args(OutletCause))
    assert len(reasons) == 51
    sections = _sections(_text(language))
    for reason in sorted(reasons):
        owners = [check for check, body in sections.items() if f"`{reason}`" in body]
        assert owners == [checks.CHECK_OF[reason]], (reason, owners)


# Hand-stated: each published limit -> the module that owns it (the value is read live, so a
# changed value without its sentence fails here).
_LIMITS = {
    "MAX_AXES": reader,
    "MAX_CHILDREN": reader,
    "MAX_COORDINATES": reader,
    "MAX_TEXT": reader,
    "MAX_DESCRIPTION_BYTES": reader,
    "MAX_PNG_CHARACTERS": reader,
    "MAX_GROUPS": explain,
    "MAX_WORK": explain,
    "MAX_RANGE": request,
    "RPC_TIMEOUT_SECONDS": filter_module,
}
_CSV_LIMITS = ("max_csv_bytes", "max_csv_rows", "max_csv_columns", "max_csv_cell_bytes")


def _limit_row(text: str, name: str) -> int:
    row = re.search(rf"^\| `{name}` \| ([0-9,_]+) \|", text, re.MULTILINE)
    assert row is not None, name
    return int(row.group(1).replace(",", "").replace("_", ""))


@pytest.mark.parametrize("language", ["en", "ja"])
def test_d6_every_limit_is_named_with_its_value(language: str) -> None:
    """D6: every published limit + its live value, both languages."""
    text = _text(language)
    for name, module in _LIMITS.items():
        assert _limit_row(text, name) == getattr(module, name), name
    for name in _CSV_LIMITS:
        assert _limit_row(text, name) == getattr(DEFAULT_LIMITS, name), name


@pytest.mark.parametrize("language", ["en", "ja"])
def test_d7_links_resolve_and_each_doc_has_one_h1(language: str) -> None:
    """D7: relative links -> tracked files; one H1."""
    text = _text(language)
    outside_code = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    assert len(re.findall(r"^# ", outside_code, re.MULTILINE)) == 1
    listed = subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(_ROOT), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    tracked = {os.fsdecode(raw) for raw in listed.split(b"\0") if raw}
    for target in _LINK.findall(outside_code):
        if not target.startswith(("http://", "https://")):
            resolved = (_DOCS[language].parent / target).resolve()
            assert resolved.is_file(), target
            # On disk is not enough: a gitignored target vanishes for a reader of the committed
            # reference (reviewer-3 K7-F2).
            assert resolved.relative_to(_ROOT).as_posix() in tracked, target


@pytest.mark.parametrize(
    ("guide", "reference"),
    [
        ("README.md", "docs/verification.md"),
        ("docs/admin/README.md", "../verification.md"),
        ("docs/admin/README.ja.md", "../verification.ja.md"),
    ],
)
def test_d9_readmes_and_admin_guides_link_the_reference(guide: str, reference: str) -> None:
    """D9: README.md + both admin guides link the reference."""
    assert f"]({reference})" in (_ROOT / guide).read_text(encoding="utf-8")
