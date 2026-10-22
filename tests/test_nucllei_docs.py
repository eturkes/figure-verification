# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q82.4: nucllei guide/admin parity + generated offline copy currency.

Transport rows differ; shared integrity rows stay single-source. Structural checks cannot decide
prose truth: source/code consistency + the rendered pages still need a reading pass.
"""

import importlib.util
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import cast, get_args
from urllib.parse import urlsplit

import pytest

from nucllei_skill.checks import CHECK_OF
from nucllei_skill.reasons import ToolCause
from webui.paste_in.checks import CHECKS

_ROOT = Path(__file__).resolve().parents[1]
_DOCS = _ROOT / "docs"
_PUBLIC = _ROOT / "llens/ext/public/figure-verification"
_ANCHOR = re.compile(r'<a id="check-([a-z]+)"></a>')
_REFERENCE = "https://github.com/eturkes/figure-verification/blob/main/docs/verification"
_OWN = {
    "no_user": "program",
    "delegated_session": "program",
    "sandbox_unreachable": "run",
    "sandbox_timeout": "run",
    "sandbox_error": "run",
    "reply_malformed": "run",
    "no_description": "run",
    "verifier_error": "figure",
    "no_image": "attach",
    "publish_failed": "attach",
}


def _text(language: str, *, admin: bool = False) -> str:
    suffix = ".ja" if language == "ja" else ""
    path = f"admin/nucllei{suffix}.md" if admin else f"nucllei/checks{suffix}.md"
    return (_DOCS / path).read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    marks = list(_ANCHOR.finditer(text))
    return {
        mark.group(1): text[
            mark.end() : marks[index + 1].start() if index + 1 < len(marks) else None
        ]
        for index, mark in enumerate(marks)
    }


@pytest.mark.parametrize("language", ["en", "ja"])
def test_each_guide_keeps_check_order_and_reason_owners(language: str) -> None:
    text = _text(language)
    assert _ANCHOR.findall(text) == list(CHECKS)
    sections = _sections(text)
    assert _OWN.keys() == set(get_args(ToolCause))
    for reason, check in CHECK_OF.items():
        owners = [name for name, body in sections.items() if f"`{reason}`" in body]
        assert owners == [_OWN.get(reason, check)], (reason, owners)
    assert "no_tool_call" not in text
    assert "Pyodide" not in text


@pytest.mark.parametrize("language", ["en", "ja"])
def test_shared_integrity_sections_stay_byte_equal(language: str) -> None:
    suffix = ".ja" if language == "ja" else ""
    source = (_DOCS / f"checks{suffix}.md").read_text(encoding="utf-8")
    generated = _text(language)
    label = "Full rules (online)" if language == "en" else "詳細 (オンライン)"
    original_label = "Full rules" if language == "en" else "詳細"
    generated = generated.replace(
        f"[{label}]({_REFERENCE}{suffix}.md", f"[{original_label}](verification{suffix}.md"
    ).replace(f"](../gallery{suffix}.md", f"](gallery{suffix}.md")
    before, after = _sections(source), _sections(generated)
    for check in ("parts", "axes", "marks", "columns"):
        assert before[check] == after[check], check
    for check, changed in (
        ("figure", ("glyph_missing", "verifier_error")),
        ("values", ("csv_too_large",)),
    ):
        pattern = rf"^\|.*`(?:{'|'.join(changed)})` \|\n"
        assert re.sub(pattern, "", before[check], flags=re.MULTILINE) == re.sub(
            pattern, "", after[check], flags=re.MULTILINE
        )


def test_generated_files_equal_a_fresh_render() -> None:
    path = _ROOT / "tools/render_nucllei_guide.py"
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("render_nucllei_guide", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for path, expected in cast("dict[Path, bytes]", module.artifacts()).items():
        assert path.is_file(), path.relative_to(_ROOT)
        assert path.read_bytes() == expected, path.relative_to(_ROOT)


class _HTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        for key, value in attrs:
            if key in {"href", "src"} and value is not None:
                self.links.append((key, value))
            if key == "id" and value is not None:
                self.ids.append(value)


@pytest.mark.parametrize(
    "name", ["checks.html", "checks.ja.html", "gallery.html", "gallery.ja.html"]
)
def test_html_keeps_assets_local_and_reference_links_labelled(name: str) -> None:
    path = _PUBLIC / name
    text = path.read_text(encoding="utf-8")
    parsed = _HTML()
    parsed.feed(text)
    assert "script" not in parsed.tags
    assert "<script" not in text.lower()
    assert "<style>" in text and "prefers-color-scheme: dark" in text
    assert ":focus-visible" in text and "76ch" in text
    assert '<meta name="viewport"' in text
    for attr, target in parsed.links:
        url = urlsplit(target)
        if url.scheme or url.netloc:
            assert attr == "href" and target.startswith(_REFERENCE), target
            assert re.search(
                rf'<a href="{re.escape(target)}">[^<]*(?:online|オンライン)[^<]*</a>', text
            )
        else:
            local = (path.parent / url.path).resolve() if url.path else path
            assert local.is_relative_to(_PUBLIC), target
            assert local.is_file(), target
            if url.fragment and local.suffix == ".html":
                destination = _HTML()
                destination.feed(local.read_text(encoding="utf-8"))
                assert url.fragment in destination.ids, target
    if name.startswith("checks"):
        assert [name for name in parsed.ids if name.startswith("check-")] == [
            f"check-{check}" for check in CHECKS
        ]
        assert len([url for _, url in parsed.links if url.startswith(_REFERENCE)]) == 10


def test_nucllei_diagrams_keep_language_structure_and_current_sources() -> None:
    structures = []
    for suffix in ("", ".ja"):
        path = _DOCS / f"diagrams/verifier-nucllei{suffix}.dot"
        source = path.read_text(encoding="utf-8")
        svg = path.with_suffix(".svg").read_text(encoding="utf-8")
        start = svg.index(f"<!-- source: {path.relative_to(_ROOT).as_posix()} (")
        assert svg[svg.index("\n", start) + 1 : svg.index("-->\n", start)] == source
        assert (_PUBLIC / f"verifier{suffix}.svg").read_bytes() == path.with_suffix(
            ".svg"
        ).read_bytes()
        structures.append(
            (
                set(re.findall(r"^\s*(\w+) \[", source, re.MULTILINE)) - {"node", "edge", "graph"},
                set(re.findall(r"^\s*(\w+(?: -> \w+)+)", source, re.MULTILINE)),
            )
        )
        assert "Pyodide" not in source and "/exec" in source and "load_skill" in source
        for number in range(1, 10):
            assert re.search(rf"<b>(?:(?:Check|チェック) )?{number}[ : ]", source), number
    assert structures[0] == structures[1]


def test_admin_guides_keep_headings_steps_code_and_identifiers_in_parity() -> None:
    english, japanese = (_text(language, admin=True) for language in ("en", "ja"))
    for pattern in (r"^#{1,6} ", r"^\d+\. ", r"^\|"):
        assert re.findall(pattern, english, re.MULTILINE) == re.findall(
            pattern, japanese, re.MULTILINE
        )
    assert re.findall(r"```[^\n]*\n(.*?)```", english, re.DOTALL) == re.findall(
        r"```[^\n]*\n(.*?)```", japanese, re.DOTALL
    )
    identifiers = []
    for text in (english, japanese):
        identifiers.append(set(re.findall(r"`([A-Za-z0-9_./=-]+)`", text)))
        for required in (
            "figure-verification",
            "figure_verification",
            "meta.skillIds",
            "meta.toolIds",
            "column_aliases",
            "model_note",
            "EXT_MOUNTS",
            "public=/ext/public",
            "TOOL_RESULT_MAX_CHARS",
            "run_python",
            "fetch_from_workspace",
            "3.12.15",
            "3.11.2",
            "2.3.3",
            "2.5.4",
            "0.13.2",
            "Figure verification passed",
            "Figure verification failed, no image produced",
            "図の検証に合格しました。",
            "図の検証に合格しませんでした。画像は表示されません。",
        ):
            assert f"`{required}`" in text, required
        for reason in _OWN:
            assert f"`{reason}`" in text, reason
        assert "enforce_access_control=False" in text
        assert "make nuc-sync" in text
    assert identifiers[0] == identifiers[1]
