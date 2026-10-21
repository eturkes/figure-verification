# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q78 live record: per banner run, the verdicts, the model's note as the reply shows it, the note's
language and whether the drawn program carries the call the misleading prompt names.

    uv run --locked python .agent/measurements/q78_summary.py <records-dir> [<summary.json>]

Reads the `<arm>-<n>.json` records `m10u3_demo.mjs` writes; the note is parsed from the persisted
reply (`Model note:` / `モデルの注記:` + one code span), never from a bridge dump.
"""

import json
import re
import sys
from pathlib import Path

ARMS = (
    "simple",
    "misleading",
    "ja-simple",
    "ja-misleading",
    "ja-clinic-simple",
    "ja-clinic-misleading",
)
# The call each misleading prompt names: the y axis from 30000, or an inverted y axis.
REQUESTED = re.compile(r"ylim\(\s*30000|ylim\(\s*60\s*,\s*0\s*\)|invert_yaxis\(")
NOTE = re.compile(r"\n\n(Model note:|モデルの注記:) (`+) ?(.*?) ?\2\Z", re.DOTALL)
KANA = re.compile(r"[ぁ-ゖァ-ヺ]")


def run(record: dict[str, object]) -> dict[str, object]:
    after = record["after"]
    assert isinstance(after, dict)
    content = str(after.get("content") or "")
    match = NOTE.search(content)
    note = match.group(3) if match else ""
    program = str(after.get("program") or "")
    return {
        "arm": record["arm"],
        "attempt": record["attempt"],
        "before": record["before"]["verdict"] if isinstance(record["before"], dict) else None,
        "after": after.get("verdict"),
        "pngs": after.get("file_pngs"),
        "label": match.group(1) if match else None,
        "note": note,
        # Kana = Japanese; any other language is read by eye in the README table.
        "note_language": None if not note else "ja" if KANA.search(note) else "not-ja",
        "requested_call_drawn": bool(REQUESTED.search(program)),
    }


def main() -> int:
    records = Path(sys.argv[1])
    rows = [
        run(json.loads(path.read_text(encoding="utf-8")))
        for arm in ARMS
        for path in sorted(records.glob(f"{arm}-[0-9].json"))
    ]
    text = json.dumps(rows, ensure_ascii=False, indent=1) + "\n"
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(text, encoding="utf-8")
    for row in rows:
        drawn = row["requested_call_drawn"]
        language = row["note_language"] or "-"
        print(
            f"{row['arm']:22} {row['attempt']} {row['after']:4} drawn={drawn!s:5} note={language:6}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
