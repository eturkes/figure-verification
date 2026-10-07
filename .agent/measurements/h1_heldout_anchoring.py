# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""H1 -- the held-out capture re-graded with each prompt as the user's request (Q39).

`capture/score.py` grades `m10-heldout` with no request text, so request anchoring never ran on
it. This re-grade keeps score.py's denominators and outcome rules (`score.score_run`: a record the
backend never answered is a transport fault, sentinels sit apart) and changes ONE input: each
dataset target carries the corpus prompt as its request, under each anchoring rule -- the demo's
`substitution` and production's `strict`. No proposer runs and no capture is taken; `score.json`,
T4 and the run-once guard stay as they are. This reads the held-out prompts, so the held-out set is
no longer blind for later anchoring changes (user ruling, session 6).

    uv run --locked python .agent/measurements/h1_heldout_anchoring.py   # writes h1-result.json
"""

import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from capture import score  # noqa: E402 -- the repo root must be on the path first
from capture.corpus import load_corpus  # noqa: E402
from capture.harness import defence  # noqa: E402
from capture.record import load_run  # noqa: E402
from verifier.pysrc.spec import DatasetPlot, DatasetTarget  # noqa: E402
from verifier.pysrc.verify import Verified, verify_python_source  # noqa: E402

HERE = Path(__file__).parent
RUN = REPO_ROOT / "corpus/python/captures" / score.HELDOUT_RUN
prompts = {prompt.id: prompt.prompt for _, prompt in load_corpus().rows()}
data = score.load_data()
run = load_run(RUN)
committed = json.loads((RUN / score.SCORE_FILE).read_text())
committed_rows = {row["prompt_id"]: row for row in committed["rows"]}


def regraded(anchoring, *, with_request=True):
    def row(record, data):
        if record.http_status != score._OK or record.content is None:
            return score._scored(record, "transport_error", None, None)
        target = DatasetTarget(
            path="/mnt/uploads/" + record.dataset_name,
            content=data[record.dataset_name],
            request=prompts[record.prompt_id] if with_request else None,
            anchoring=anchoring,
        )
        verdict = verify_python_source(defence(record.content)[1], declared_target=target)
        if not isinstance(verdict, Verified):
            return score._scored(record, "refused", verdict.code, None)
        assert isinstance(verdict.spec, DatasetPlot)
        return score._scored(record, "verified", None, verdict.spec)

    with mock.patch.object(score, "_row", row):
        graded = score.score_run(run, data)
    summary = graded.summary
    changed = [
        f"{r.prompt_id}:{committed_rows[r.prompt_id]['outcome']}->{r.outcome}"
        + ("" if r.code is None else f"({r.code})")
        for r in graded.rows
        if (r.outcome, r.code)
        != (
            committed_rows[r.prompt_id]["outcome"],
            committed_rows[r.prompt_id]["code"],
        )
    ]
    return {
        "simple_verified": summary.simple.verified,
        "simple_total": summary.simple.total,
        "complicated_blocked": summary.complicated.blocked,
        "complicated_total": summary.complicated.total,
        "transport_errors": summary.transport_errors,
        "sentinels": summary.sentinels,
        "acceptance_met": summary.acceptance_met,
        "changed": changed,
    }


# Control: the same patched grader with no request reproduces the committed score row for row.
control = regraded("strict", with_request=False)
assert control["changed"] == [], control["changed"]
assert control["simple_verified"] == committed["summary"]["simple"]["verified"]
result = {mode: regraded(mode) for mode in ("substitution", "strict")}
for mode, leg in result.items():
    print(
        f"{mode}: simple {leg['simple_verified']}/{leg['simple_total']} VERIFIED;"
        f" complicated {leg['complicated_blocked']}/{leg['complicated_total']} BLOCKED;"
        f" sentinels {leg['sentinels']}; acceptance_met {leg['acceptance_met']}"
    )
    print(f"  changed vs score.json: {leg['changed']}")
(HERE / "h1-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
