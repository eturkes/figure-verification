# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.3 D3-D7 + D9, re-keyed by M19.5; Q72 G1-G3: the python-mode reference names every check,
reason + limit, and the short guide each "Show checks" row opens names every check.

Contracts: `.agent/archive/contracts/m18u3.md`, `.agent/archive/contracts/m19u5.md` (W6),
`.agent/archive/contracts/q72.md`. Each row links its guide section, which links its reference
section, so both move with the code: a check, a reason or a limit added without its sentence here
fails this module. Presence is all a token scan decides; whether a sentence is TRUE stays the
closing review's (D8). D5 (every admitted Python name) retired with the static admission path.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import get_args

import pytest

from outlet_support import GUIDE
from verifier.figure import explain, reader, request
from verifier.figure.reasons import FigureReason
from verifier.pysrc.limits import DEFAULT_LIMITS
from webui.paste_in import checks
from webui.paste_in import filter as filter_module
from webui.paste_in.reasons import OutletCause

_ROOT = Path(__file__).resolve().parents[1]
_DOCS = {
    "reference": {"en": _ROOT / "docs/verification.md", "ja": _ROOT / "docs/verification.ja.md"},
    "guide": {"en": _ROOT / "docs/checks.md", "ja": _ROOT / "docs/checks.ja.md"},
}
_MAIN = "https://github.com/eturkes/figure-verification/blob/main/"
_ANCHOR = re.compile(r'<a id="check-([a-z]+)"></a>')
_HEADING = re.compile(r"^#{1,6} (.+)$", re.MULTILINE)
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)\s]*)?\)")


def _text(language: str, doc: str = "reference") -> str:
    return _DOCS[doc][language].read_text(encoding="utf-8")


def _name(language: str, doc: str) -> str:
    return _DOCS[doc][language].name


def _tracked() -> set[str]:
    listed = subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(_ROOT), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return {os.fsdecode(raw) for raw in listed.split(b"\0") if raw}


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


@pytest.mark.parametrize("doc", ["reference", "guide"])
@pytest.mark.parametrize("language", ["en", "ja"])
def test_d3_each_check_has_its_anchor_and_title(language: str, doc: str) -> None:
    """D3 + Q72 G1: 9 `check-<id>` anchors in CHECKS order, each before its TEXTS title heading."""
    text = _text(language, doc)
    assert [mark.group(1) for mark in _ANCHOR.finditer(text)] == list(checks.CHECKS)
    column = 0 if language == "en" else 1
    sections = _sections(text)
    for check in checks.CHECKS:
        heading = _HEADING.search(sections[check])
        assert heading is not None, check
        assert checks.TEXTS[check][column][0] in heading.group(1), (check, heading.group(1))


@pytest.mark.parametrize("doc", ["reference", "guide"])
@pytest.mark.parametrize("language", ["en", "ja"])
def test_d4_each_reason_sits_in_its_check_section(language: str, doc: str) -> None:
    """D4 + Q72 G1: all 53 reasons (39 figure + 14 outlet), each inside its CHECK_OF section only;
    the guide too, since it is the complete checklist (user)."""
    reasons = set(get_args(FigureReason)) | set(get_args(OutletCause))
    assert len(reasons) == 53
    sections = _sections(_text(language, doc))
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


@pytest.mark.parametrize("doc", ["reference", "guide"])
@pytest.mark.parametrize("language", ["en", "ja"])
def test_d7_links_resolve_and_each_doc_has_one_h1(language: str, doc: str) -> None:
    """D7 + Q72 G1: relative links -> tracked files; one H1."""
    text = _text(language, doc)
    outside_code = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    assert len(re.findall(r"^# ", outside_code, re.MULTILINE)) == 1
    tracked = _tracked()
    for target in _LINK.findall(outside_code):
        if not target.startswith(("http://", "https://")):
            resolved = (_DOCS[doc][language].parent / target).resolve()
            assert resolved.is_file(), target
            # On disk is not enough: a gitignored target vanishes for a reader of the committed
            # reference (reviewer-3 K7-F2).
            assert resolved.relative_to(_ROOT).as_posix() in tracked, target


@pytest.mark.parametrize(
    ("guide", "reference"),
    [
        ("README.md", "docs/verification.md"),
        ("README.md", "docs/checks.md"),
        ("docs/admin/README.md", "../verification.md"),
        ("docs/admin/README.md", "../checks.md"),
        ("docs/admin/README.ja.md", "../verification.ja.md"),
        ("docs/admin/README.ja.md", "../checks.ja.md"),
    ],
)
def test_d9_readmes_and_admin_guides_link_the_reference(guide: str, reference: str) -> None:
    """D9 + Q72 G6: README.md + both admin guides link the reference and the guide."""
    assert f"]({reference})" in (_ROOT / guide).read_text(encoding="utf-8")


@pytest.mark.parametrize("language", ["en", "ja"])
def test_q72_g3_each_row_link_opens_a_tracked_guide_section(language: str) -> None:
    """G3: the hand-stated row URL (`outlet_support.GUIDE`, which O9 matches against every rendered
    href) = GitHub `main` + this language's tracked guide, which holds every check's anchor."""
    url = GUIDE[0 if language == "en" else 1]
    assert url.startswith(_MAIN), url
    path = url.removeprefix(_MAIN)
    assert path == _DOCS["guide"][language].relative_to(_ROOT).as_posix()
    assert path in _tracked()
    anchors = [mark.group(1) for mark in _ANCHOR.finditer(_text(language, "guide"))]
    assert anchors == list(checks.CHECKS)


@pytest.mark.parametrize("language", ["en", "ja"])
def test_q72_g2_the_guide_and_the_reference_link_each_other(language: str) -> None:
    """G2: the guide's intro + every check section link the same language's reference (the section
    at its own anchor); the guide links its language twin; the reference links its guide."""
    guide = _text(language, "guide")
    reference = _name(language, "reference")
    intro = guide[: guide.find('<a id="check-')]
    assert f"]({reference})" in intro
    for check, body in _sections(guide).items():
        assert f"]({reference}#check-{check})" in body, check
    twin = _name("ja" if language == "en" else "en", "guide")
    assert f"]({twin})" in guide
    assert f"]({_name(language, 'guide')})" in _text(language)


_ROW = re.compile(r"^\|(.+)\|$", re.MULTILINE)


@pytest.mark.parametrize("language", ["en", "ja"])
def test_q72_each_guide_rule_states_how_it_is_checked(language: str) -> None:
    """Q72 amendment 3 (user: "HOW does this tool verify these things?"): every rule row of a
    guide check table = rule | how | code, each cell filled, the code cell naming known reasons."""
    reasons = set(get_args(FigureReason)) | set(get_args(OutletCause))
    for check, body in _sections(_text(language, "guide")).items():
        rows = [match.group(1) for match in _ROW.finditer(body)]
        rules = [row for row in rows[2:] if not set(row) <= {"-", "|"}]
        assert rules, check
        for row in rules:
            cells = [cell.strip() for cell in row.split("|")]
            assert len(cells) == 3 and all(cells), (check, row)
            codes = re.findall(r"`([a-z_]+)`", cells[2])
            assert codes and set(codes) <= reasons, (check, row)


_DIAGRAMS = _ROOT / "docs" / "diagrams"


def test_q72_each_diagram_renders_its_current_source() -> None:
    """Q72: each `docs/diagrams/*.dot` has a tracked sibling `.svg` whose embedded source copy
    (`tools/render_diagrams.py`) equals the `.dot` text, so an edit without a re-render fails here
    with no Graphviz on the gate host; each guide embeds its language's diagram."""
    sources = sorted(_DIAGRAMS.glob("*.dot"))
    assert [source.name for source in sources] == ["verifier.dot", "verifier.ja.dot"]
    tracked = _tracked()
    for source in sources:
        svg = source.with_suffix(".svg")
        assert svg.relative_to(_ROOT).as_posix() in tracked, svg
        text = svg.read_text(encoding="utf-8")
        assert text.startswith("<?xml") and "<svg " in text and text.rstrip().endswith("</svg>")
        start = text.index(f"<!-- source: {source.relative_to(_ROOT).as_posix()} (")
        copy = text[text.index("\n", start) + 1 : text.index("-->\n", start)]
        assert copy == source.read_text(encoding="utf-8"), source.name
    for language, name in (("en", "verifier.svg"), ("ja", "verifier.ja.svg")):
        assert f"](diagrams/{name})" in _text(language, "guide")
