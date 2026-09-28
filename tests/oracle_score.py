# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent M10.9 S1-S6 scorer: stdlib JSON inputs, no production scorer imports.

Shared dependencies = de-fencing + the verifier whose verdicts are being counted. Parsing,
partitioning, completeness, acceptance, table assembly and JSON form are independent. The caller
supplies expected id/kind/category metadata, so the oracle never needs held-out prompt text.
"""

import json
from collections.abc import Mapping
from typing import Any

from capture.harness import defence
from verifier.pysrc import Refused, verify_python_source
from verifier.pysrc.spec import DatasetPlot, DatasetTarget

type Document = dict[str, Any]


def score_records(
    manifest_bytes: bytes,
    records_bytes: bytes,
    data: Mapping[str, bytes],
    corpus_rows: Mapping[str, tuple[str, str]],
) -> Document:
    """Score one serialized capture without capture.record or capture.score decoding helpers."""
    manifest = json.loads(manifest_bytes)
    if manifest["kind"] == "sentinels":
        message = "sentinel-only captures have no category population"
        raise ValueError(message)
    records = [json.loads(line) for line in records_bytes.splitlines()]
    rows: list[Document] = []
    for record in sorted(records, key=lambda value: value["prompt_id"]):
        row = {
            name: record[name]
            for name in ("prompt_id", "kind", "category", "idiom", "dataset_name")
        }
        row.update(outcome="transport_error", code=None, mark=None, x=None, y=None, reduction=None)
        if record["http_status"] == 200:
            _, source = defence(record["content"])
            verdict = verify_python_source(
                source,
                declared_target=DatasetTarget(
                    path="/mnt/uploads/" + record["dataset_name"],
                    content=data[record["dataset_name"]],
                ),
            )
            if isinstance(verdict, Refused):
                row.update(outcome="refused", code=verdict.code)
            else:
                assert isinstance(verdict.spec, DatasetPlot)
                row.update(
                    outcome="verified",
                    mark=verdict.spec.mark,
                    x=verdict.spec.x.name,
                    y=verdict.spec.y.name,
                    reduction=verdict.spec.group,
                )
        rows.append(row)

    own = manifest["kind"]
    totals = {
        category: sum(kind == own and found == category for kind, found in corpus_rows.values())
        for category in ("simple", "complicated")
    }

    # Lead amendment A1 (reviewer-3 S-C2): a numerator counts each corpus id of the run's own set
    # at most once, by its CORPUS category, and completeness is a multiset match.
    def credited(category: str, outcome: str) -> int:
        return len(
            {
                row["prompt_id"]
                for row in rows
                if corpus_rows.get(row["prompt_id"]) == (own, category)
                and row["outcome"] == outcome
            }
        )

    sentinels = {row["prompt_id"]: row["outcome"] for row in rows if row["kind"] == "sentinels"}
    verified = credited("simple", "verified")
    blocked = credited("complicated", "refused")
    transports = sum(row["outcome"] == "transport_error" for row in rows)
    ids = [row["prompt_id"] for row in rows]
    complete = len(ids) == len(corpus_rows) and set(ids) == set(corpus_rows)
    checks = (
        complete,
        transports == 0,
        verified * 10 >= totals["simple"] * 7,
        blocked * 10 >= totals["complicated"] * 7,
        sentinels.get("sentinel-simple") == "verified",
        sentinels.get("sentinel-complicated") == "refused",
    )
    return {
        "version": "python-score-1",
        "run": manifest["run"],
        "summary": {
            "simple": {"total": totals["simple"], "verified": verified},
            "complicated": {"total": totals["complicated"], "blocked": blocked},
            "transport_errors": transports,
            "sentinels": sentinels,
            "complete": complete,
            "acceptance_met": all(checks),
        },
        "rows": rows,
    }


def encode_document(document: Document) -> bytes:
    """Independent indent-two declaration-order JSON; a single final newline."""
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
