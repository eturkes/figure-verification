# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.3 D3-D7 + D9: the python-mode reference names every check, reason, accepted name + limit.

Contract: `.agent/archive/contracts/m18u3.md`. The reference is what each "Show checks" row links
to, so it must move with the code: a check, a reason, an admitted call or a limit added without its
sentence here fails this module. Presence is all a token scan decides; whether a sentence is TRUE
stays the closing review's (D8).
"""

import dataclasses
import os
import re
import subprocess
from pathlib import Path
from typing import get_args

import pytest

from verifier.pysrc import admit
from verifier.pysrc.errors import RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS
from webui.paste_in import checks
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
    """D3: 11 `check-<id>` anchors in CHECKS order, each before its TEXTS title heading."""
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
    """D4: all 69 reasons, each inside its CHECK_OF section, both languages."""
    reasons = set(get_args(RefusalCode)) | set(get_args(OutletCause))
    assert len(reasons) == 69
    sections = _sections(_text(language))
    for reason in sorted(reasons):
        owners = [check for check, body in sections.items() if f"`{reason}`" in body]
        assert owners == [checks.CHECK_OF[reason]], (reason, owners)


def _accepted_names() -> set[str]:
    """Read off the live admission tables, so a name admitted later without its sentence fails."""
    names = set(admit.ADMITTED_CALL_TARGETS) | set(admit.ADMITTED_CONSTANT_ATTRS)
    names |= {*admit.ADMITTED_IMPORTS, *admit.ADMITTED_IMPORTS.values()}
    names |= {keyword for keywords in admit.ADMITTED_KEYWORDS.values() for keyword in keywords}
    names |= set(admit.ADMITTED_VALUE_ATTRS) | set(admit.ADMITTED_ACCESSOR_KINDS)
    names |= set(admit.ADMITTED_ACCESSOR_KEYWORDS) | set(admit.ADMITTED_UNWRAPPED_ATTRS)
    # The reduction set has no public name; reading the private one is the point (reviewer-3 K7-F1).
    return names | set(admit._REDUCTIONS)


@pytest.mark.parametrize("language", ["en", "ja"])
def test_d5_every_accepted_name_is_named(language: str) -> None:
    """D5: imports, call targets, keywords, attributes, accessor kinds, unwraps, reductions."""
    text = _text(language)
    spans = re.findall(r"`([^`\n]+)`", text)
    missing = sorted(
        name
        for name in _accepted_names()
        if not any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", span) for span in spans)
    )
    assert not missing, missing
    # A call target counts only when written whole, never as two words (`np` + `sin`).
    whole = sorted(name for name in admit.ADMITTED_CALL_TARGETS if f"`{name}`" not in text)
    assert not whole, whole


@pytest.mark.parametrize("language", ["en", "ja"])
def test_d6_every_limit_is_named_with_its_value(language: str) -> None:
    """D6: every DEFAULT_LIMITS field + value, both languages."""
    text = _text(language)
    for field in dataclasses.fields(DEFAULT_LIMITS):
        value: int = getattr(DEFAULT_LIMITS, field.name)
        row = re.search(rf"^\| `{field.name}` \| ([0-9,_]+) \|", text, re.MULTILINE)
        assert row is not None, field.name
        assert int(row.group(1).replace(",", "").replace("_", "")) == value, field.name


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
