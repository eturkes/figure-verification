# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q79 render corpus: hostile model notes through the production note line, for `q79_render.mjs`.

    PYTHONPATH="$PWD" uv run --locked python .agent/measurements/q79_corpus.py <corpus.json>

Each case = the reply `content` the filter writes (`filter.py::_note_line` after the verdict) + the
text Open WebUI must show in the note's paragraph (the label, a space, the visible note).
"""

import argparse
import json
from pathlib import Path

from verifier.figure.inert import visible
from webui.paste_in.filter import _note_line
from webui.paste_in.reply import PASS_TEXTS

# What each language's label shows, and the element that draws it (Q80: KaTeX bold in Japanese).
LABELS = (("Model note:", "strong"), ("モデルの注記:", "katex"))

NOTES = (
    "The request asks for plt.ylim(30000, 45000); the chart starts the y axis at 0 instead.",
    "![x](http://example.invalid/a.png) [link](https://example.invalid) <https://example.invalid>",
    "https://example.invalid/path www.example.invalid user@example.invalid ftp://example.invalid",
    "<img src=x onerror=alert(1)> <iframe src='https://example.invalid'></iframe> <video src=x>",
    "<details><summary>s</summary>x</details> <u>u</u> <b>b</b> <script>alert(1)</script>",
    "$x^2$ $$y$$ \\(z\\) \\[w\\] \\pu{1 m} \\ce{H2O} \\begin{equation}e\\end{equation} a $b$ c",
    "**bold** *em* _em_ ~~del~~ ~one~ `code` ``` x ``` ==mark==",
    "# heading > quote - item 1. item | a | b | :::note x ::: ---",
    "[1] [1,2] [1#x] [^1] {{user}} {{CHAR}} {{VIDEO_FILE_ID_0123abcd}} {{HTML_FILE_ID_0a}} <@user>",
    "&amp; &lt; &#x41; &#65; &nbsp; \\& \\* \\\\ trailing backslash \\",
    "ご指定の plt.ylim(60, 0) は\uff08注\uff09**強調**【例】「軸」を反転します。$x$ と \\(y\\)",
    "line one\nline two\r\nthree\u2028four \u202eevil\u200b \x00 \x7f end",
)


def main(out: Path) -> int:
    cases = []
    for japanese in (False, True):
        metadata = {"user_message": {"content": "グラフ" if japanese else "Chart"}}
        label, kind = LABELS[japanese]
        for note in NOTES:
            shown = note.strip()
            cases.append(
                {
                    "note": note,
                    "label": label,
                    "label_kind": kind,
                    "content": PASS_TEXTS[japanese] + _note_line(note, metadata),
                    "expected": f"{label} " + "".join(map(visible, shown)),
                }
            )
    out.write_text(json.dumps(cases, ensure_ascii=False, indent=1), "utf-8")
    print(len(cases), "cases")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Write the hostile model-note corpus through the production note line."
    )
    parser.add_argument("out", type=Path, help="the corpus JSON file")
    raise SystemExit(main(parser.parse_args().out))
