# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""NR (M23.1 N7, N8): the nucllei tool's markdown under hostile text, for `nucllei_render.mjs`.

    PYTHONPATH="$PWD" uv run --locked python .agent/measurements/nucllei_render_corpus.py <out.json>

Cases: `display` = the pass display `nucllei_skill/tool.py::_Draw.publish` pushes (verdict, image,
an interpretation of hostile names as `inert.code` spans, the note line) per hostile note, EN + JA;
`fail` = a blocked display; `result` = the check list over a hostile program. Each case states
what may render: the driver fails on any other markup token. `control` = the same note unescaped,
which must render markup (the driver's positive control).
"""

import json
import sys
from pathlib import Path

from nucllei_skill.checks import checklist
from nucllei_skill.reasons import REASONS
from nucllei_skill.texts import IMAGE_ALT
from verifier.figure.inert import code, visible
from webui.paste_in.checks import Evidence
from webui.paste_in.reply import FAIL_TEXTS, NOTE_LABELS, PASS_TEXTS, note_line

sys.path.insert(0, str(Path(__file__).resolve().parent))
from q79_corpus import NOTES  # the Open WebUI corpus, reused whole

FILE_ID = "0a1b2c3d-0000-4000-8000-000000000000"
# nucllei's own constructs on top of Q79's: bracket references (`/ext/` pages, file ids in the
# chat), attribute braces, file-id tokens `replaceTokens` rewrites, block math on its own lines.
NUCLLEI_NOTES = (
    f"[/ext/public/figure-verification/checks.html] [{FILE_ID}] [/ext/a.md#x]",
    "[x](/ext/a.md){download=evil.html} [y](https://example.invalid){target=_self} z{.cls}",
    f"{{{{VIDEO_FILE_ID_{FILE_ID}}}}} {{{{HTML_FILE_ID_{FILE_ID}}}}} {{{{user}}}} {{{{char}}}}",
    "$$\nx\n$$ \\[\ny\n\\] \\begin{equation}\nz\n\\end{equation}",
)
NAMES = (
    "[/ext/a.md]",
    f"[{FILE_ID}]",
    "$x$",
    "\\(y\\)",
    "a`b",
    "``",
    f"{{{{HTML_FILE_ID_{FILE_ID}}}}}`",
    "{download=x}",
    "<img src=x onerror=1>",
    "line\nbreak",
    " spaced ",
    "",
    "`",
)
PROGRAM = "\n".join(
    (
        "import matplotlib.pyplot as plt",
        "# </details> ``` [/ext/a.md] $x$ \\(y\\)",
        f"label = '{{{{HTML_FILE_ID_{FILE_ID}}}}} {{download=x}} <img src=x>'",
        "plt.bar(['a'], [1], label=label)",
        "plt.ylim(1, 2)",
        "plt.show()",
    )
)


def display(note: str, *, japanese: bool) -> str:
    """The pass display, as `_Draw.publish` builds it."""
    language = int(japanese)
    interpretation = "Drawn columns: " + ", ".join(map(code, NAMES)) + "."
    return (
        f"{PASS_TEXTS[language]}\n\n![{IMAGE_ALT[language]}](/api/v1/files/{FILE_ID}/content)"
        f"\n\n{interpretation}{note_line(note, japanese=japanese)}"
    )


def main() -> int:
    cases: list[dict[str, object]] = []
    for japanese in (False, True):
        language = int(japanese)
        cases.extend(
            {
                "kind": "display",
                "content": display(note, japanese=japanese),
                "codespans": ["".join(map(visible, name)) or " " for name in NAMES],
                "note": " " + "".join(map(visible, note.strip())),
            }
            for note in (*NOTES, *NUCLLEI_NOTES)
        )
        cases.append(
            {
                "kind": "fail",
                "content": f"{FAIL_TEXTS[language]}\n\n"
                f"{REASONS['zero_not_in_limits'][language]} (zero_not_in_limits)",
            }
        )
        evidence = Evidence(PROGRAM, 5, (("axes", frozenset({4, 5})),))
        cases.append(
            {
                "kind": "result",
                "content": checklist("zero_not_in_limits", japanese=japanese, evidence=evidence),
                "program": ["".join(map(visible, line)) for line in PROGRAM.split("\n")],
            }
        )
        raw = NOTES[1] + " " + NUCLLEI_NOTES[0]
        cases.append(
            {
                "kind": "control",
                "content": f"{PASS_TEXTS[language]}\n\n{NOTE_LABELS[language]} {raw}",
            }
        )
    Path(sys.argv[1]).write_text(json.dumps(cases, ensure_ascii=False, indent=1), "utf-8")
    print(len(cases), "cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
