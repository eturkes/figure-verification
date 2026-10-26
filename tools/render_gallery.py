# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Write the blocked-chart gallery: `docs/gallery.md`, `docs/gallery.ja.md`, `docs/gallery/*.png`.

    uv run --locked python tools/render_gallery.py

Each entry of `docs/gallery/entries.toml` pairs a rule-corpus case that blocks with one reason and
an honest case that passes (`tests/figure_corpus/*.toml`, or a gallery-only twin in
`docs/gallery/cases.toml`). Every case runs through the trusted reader and the judge on this host;
a verdict other than the entry states stops the run, so a published pair is a checked pair. The PNG
= the one the reader returns, the image the sandbox would show. The rule text comes from the
checklist tables (`docs/checks{,.ja}.md`), the check titles from `webui/paste_in/checks.py`.
`markdown()` renders text alone, so `tests/test_gallery.py` compares it with the committed pages
without rendering.
"""

import argparse
import base64
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

# A script run by path puts its own directory on `sys.path`, never the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webui.paste_in.checks import CHECK_OF, CHECKS, TEXTS

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
GALLERY = DOCS / "gallery"
CORPUS = ROOT / "tests" / "figure_corpus"
DATA = ROOT / "data"
SANDBOX = "/mnt/uploads"
_ROW = re.compile(r"^\| (.+?) \| .+? \| (.+?) \|$", re.MULTILINE)

_WORDS = {
    "en": {
        "title": "# Blocked chart gallery",
        "intro": (
            "Each pair shows a chart that the verifier blocks, beside an honest chart that passes."
            " Every chart is a test case: the generator, `tools/render_gallery.py`, runs each"
            " program through the figure reader and the judge, and it stops unless each verdict"
            " matches. The rules: [checks.md](checks.md). [日本語版](gallery.ja.md)"
        ),
        "check": "Check",
        "blocked": "Blocked",
        "passes": "Passes",
        "programs": "Programs",
        "comma": ", ",
        "request": "Request: {request}.",
        "file": " File: {file}.",
        "both": "Blocked chart's request: {blocked}. Passing chart's request: {passes}.",
        "with": "{request} with {file}",
    },
    "ja": {
        "title": "# 不合格になるグラフの例",
        "intro": (
            "各組は、検証器が不合格にするグラフと、合格する正しいグラフを並べて示します。"
            "どのグラフもテストケースです。生成スクリプト `tools/render_gallery.py` が、"
            "各プログラムを図の読み取り処理と判定処理で実行し、判定が一致しない場合は停止します。"
            "規則: [checks.ja.md](checks.ja.md)。[English](gallery.md)"
        ),
        "check": "チェック",
        "blocked": "不合格",
        "passes": "合格",
        "programs": "プログラム",
        "comma": "、",
        "request": "依頼文: {request}。",
        "file": "ファイル: {file}。",
        "both": "不合格のグラフの依頼文: {blocked}。合格するグラフの依頼文: {passes}。",
        "with": "{request} (ファイル {file})",
    },
}


def cases() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in [*sorted(CORPUS.glob("*.toml")), GALLERY / "cases.toml"]:
        for case in tomllib.loads(path.read_text(encoding="utf-8"))["case"]:
            if case["id"] in found:
                sys.exit(f"duplicate case id {case['id']}")
            found[case["id"]] = case
    return found


def entries() -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = tomllib.loads(
        (GALLERY / "entries.toml").read_text(encoding="utf-8")
    )["entry"]
    order = {reason: index for index, reason in enumerate(CHECK_OF)}
    return sorted(loaded, key=lambda entry: order[entry["reason"]])


def rules(language: str) -> dict[str, str]:
    """Reason -> the first checklist row naming it (`docs/checks{,.ja}.md`)."""
    name = "checks.md" if language == "en" else "checks.ja.md"
    found: dict[str, str] = {}
    for rule, codes in _ROW.findall((DOCS / name).read_text(encoding="utf-8")):
        for code in re.findall(r"`([a-z_]+)`", codes):
            found.setdefault(code, rule)
    return found


def _program(case: dict[str, Any]) -> str:
    return str(case["program"]).replace("{data}", SANDBOX).strip()


def _request(case: dict[str, Any], words: dict[str, str]) -> str:
    request = f"`{case['request']}`" if "request" in case else "`(none)`"
    if "csv" in case:
        return words["with"].format(request=request, file=f"`{case['csv']}`")
    return request


def _entry(entry: dict[str, Any], every: dict[str, dict[str, Any]], language: str) -> list[str]:
    words = _WORDS[language]
    rule = rules(language)[entry["reason"]]
    blocked = every[entry["blocked"]]
    twin = every[entry["twin"]] if "twin" in entry else None
    lines = [
        f'<a id="{entry["reason"]}"></a>',
        "",
        f"### `{entry['reason']}`: {rule}",
        "",
        entry[language],
        "",
    ]
    image = f"![{words['blocked']}: {rule}](gallery/{blocked['id']}.png)"
    if twin is None:
        lines += [f"| {words['blocked']} |", "|---|", f"| {image} |", ""]
    else:
        passing = f"![{words['passes']}: {rule}](gallery/{twin['id']}.png)"
        lines += [
            f"| {words['blocked']} | {words['passes']} |",
            "|---|---|",
            f"| {image} | {passing} |",
            "",
        ]
    if twin is not None and (blocked.get("request"), blocked.get("csv")) != (
        twin.get("request"),
        twin.get("csv"),
    ):
        line = words["both"].format(blocked=_request(blocked, words), passes=_request(twin, words))
    else:
        line = words["request"].format(request=f"`{blocked.get('request', '(none)')}`")
        if "csv" in blocked:
            line += words["file"].format(file=f"`{blocked['csv']}`")
    lines += [line, "", f"<details><summary>{words['programs']}</summary>", ""]
    for label, case in ((words["blocked"], blocked), (words["passes"], twin)):
        if case is not None:
            lines += [f"{label}:", "", "```python", _program(case), "```", ""]
    lines += ["</details>", ""]
    return lines


def markdown(language: str) -> str:
    every = cases()
    words = _WORDS[language]
    lines = [words["title"], "", words["intro"], ""]
    listed = entries()
    for index, check in enumerate(CHECKS):
        links = [
            f"[`{e['reason']}`](#{e['reason']})" for e in listed if CHECK_OF[e["reason"]] == check
        ]
        if links:
            lines.append(f"- {words['check']} {index + 1}: {words['comma'].join(links)}")
    lines.append("")
    for index, check in enumerate(CHECKS):
        mine = [entry for entry in listed if CHECK_OF[entry["reason"]] == check]
        if not mine:
            continue
        title = TEXTS[check][0 if language == "en" else 1][0]
        lines += [
            f'<a id="check-{check}"></a>',
            "",
            f"## {words['check']} {index + 1}: {title}",
            "",
        ]
        for entry in mine:
            lines += _entry(entry, every, language)
    return "\n".join(lines).rstrip("\n") + "\n"


def _render(case: dict[str, Any]) -> bytes:
    """Run one case through the reader + judge; its PNG, after the verdict matched."""
    from verifier.figure import reader  # noqa: PLC0415 - matplotlib loads only when rendering
    from verifier.figure.description import parse_description  # noqa: PLC0415
    from verifier.figure.judge import Sources, judge  # noqa: PLC0415
    from verifier.figure.reasons import Blocked  # noqa: PLC0415

    program = case["program"].replace("{data}", str(DATA)).replace("{corpus}", str(CORPUS))
    output = reader.run(program)
    described = parse_description(output)
    if described is None:
        sys.exit(f"{case['id']}: no description")
    files: tuple[tuple[str, bytes], ...] = ()
    if "csv" in case:
        path = DATA / case["csv"]
        files = ((case["csv"], (path if path.is_file() else CORPUS / case["csv"]).read_bytes()),)
    verdict = judge(described, Sources(files, case.get("request"), case.get("anchoring", "strict")))
    got = verdict.reason if isinstance(verdict, Blocked) else "pass"
    if got != case["expect"]:
        sys.exit(f"{case['id']}: verdict {got}, expected {case['expect']}")
    pngs = [line for line in output.splitlines() if line.startswith(reader.PNG_PREFIX)]
    if len(pngs) != 1:
        sys.exit(f"{case['id']}: {len(pngs)} PNG lines")
    return base64.b64decode(pngs[0][len(reader.PNG_PREFIX) :])


def main(argv: list[str]) -> None:
    argparse.ArgumentParser(
        description="Render the gallery images and pages from the gallery cases in docs/gallery.",
        allow_abbrev=False,
    ).parse_args(argv)
    every = cases()
    wanted = sorted(
        {entry["blocked"] for entry in entries()} | {e["twin"] for e in entries() if "twin" in e}
    )
    for stale in GALLERY.glob("*.png"):
        if stale.stem not in wanted:
            stale.unlink()
    for name in wanted:
        (GALLERY / f"{name}.png").write_bytes(_render(every[name]))
    for language, page in (("en", "gallery.md"), ("ja", "gallery.ja.md")):
        (DOCS / page).write_text(markdown(language), encoding="utf-8")
    print(f"wrote {len(wanted)} images + 2 pages")  # noqa: T201 - CLI report


if __name__ == "__main__":
    main(sys.argv[1:])
