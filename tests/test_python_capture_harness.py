# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Red suite for M12.6b — the capture INSTRUMENT (live driver + offline derived stats).

One test per check-set row of .agent/contracts/m12u6b.md; each docstring states that row's OWN
acceptance check. Authored diff-blind against the contract, never against capture/harness.py.

Hardware-free: every live-transport row drives httpx.MockTransport, so no backend, no accelerator
and no network are reachable from this file. The positive control is the committed golden run
tests/golden/capture-golden-v1/, whose statistic is HAND-STATED here rather than re-derived.

capture/ sits outside the coverage source, so a predicate without a near-miss refusal test ships
unpinned: every row below must refuse a near miss of the SAME family, not only a generic outsider.
"""

import pytest

pytestmark = pytest.mark.skip(reason="M12.6b seed — the red suite fills these in place")


def test_s_shape() -> None:
    """S-shape — S1 + S2 + S4 each fail on one mutation of the golden stats and nothing else.

    Accept when: a foreign ``version`` and a foreign ``mode`` each fail S1 alone; a ``run``,
    ``kind`` or ``record_count`` disagreeing with the run manifest fails S2 alone; a dropped or
    extra ``by_category`` key, a sentinel row that is not one of the run's sentinel records, and a
    category block whose ``records`` sum plus the sentinel count misses ``record_count`` each fail
    S4 alone. The unmodified golden yields no S-failure at all.
    """


def test_s3_reproduce() -> None:
    """S3 — the committed stats.json IS the re-derivation from the committed records.

    Accept when: ``validate_stats`` returns ``[]`` on the golden, and a stats.json edited by one
    count, one rate digit, or one key-order swap fails S3 while the records stay untouched.
    """


def test_h1_body_provenance() -> None:
    """H1 — every outbound body is build_request_body's bytes and nothing else.

    Accept when: the content captured by the mock transport equals
    ``build_request_body(prompt=render_capture_prompt(row), model=…, max_tokens=…,
    temperature=…)`` byte for byte, the emitted record's ``request_sha256`` is that sha256, and the
    request key set is exactly ``REQUEST_KEYS`` with no member of ``BANNED_REQUEST_KEYS``.
    """


def test_h2_row_selection() -> None:
    """H2 — run scope is the manifest's kind plus the sentinels, in corpus order.

    Accept when: ``design`` selects the 48 design rows followed by both sentinels in corpus order,
    the no-sentinels form selects exactly 48, and ``--kind heldout`` without the acknowledgement
    flag exits non-zero having issued ZERO requests through the transport.
    """


def test_h3_per_row_flush() -> None:
    """H3 — the directory is a valid gradeable capture after every row.

    Accept when: after row k the directory grades clean under ``capture.record.validate`` and its
    manifest ``record_count`` is k; a driver interrupted after row k leaves exactly that state on
    disk, with run.json, records.ndjson and stats.json all present and mutually consistent.
    """


def test_h4_ok_mapping() -> None:
    """H4 — a 200 envelope is copied verbatim into the record.

    Accept when: content, ``finish_reason`` and all three usage counts equal the envelope's, a
    non-ASCII reply keeps its exact bytes (``content_bytes`` counts UTF-8 bytes, not characters),
    and ``error`` is None.
    """


def test_h5_fault_mapping() -> None:
    """H5 — every unusable exchange takes the fault arm with its status named in the error.

    Accept when: a non-200 records the SERVER's status; a transport error, an undecodable body, an
    envelope with no usable choice, and a ``finish_reason`` outside ``FINISH_REASONS`` each record
    ``NO_STATUS`` with a non-empty ``error`` naming the observed status; in every arm all five
    reply fields are absent, so ``capture.record.check_outcome_shape`` reports nothing.
    """


def test_h8_defence() -> None:
    """H8 — one de-fencer, and it survives an unterminated fence.

    Accept when: a closed fence yields its inner block; an UNTERMINATED fence (the truncation
    shape) yields the remainder rather than the whole reply; an unfenced reply is returned
    unchanged with ``fenced`` False; a fence with a language tag is stripped; and a ``` that is not
    at the start of a line does not open a fence. ``fenced`` agrees with the extraction in all five.
    """


def test_h9_parse_rule() -> None:
    """H9 — the parse statistic is total over adversarial bytes and refuses an empty module.

    Accept when: a real program scores parsed; a blank body, a comment-only body, a body over
    ``MAX_PARSE_BYTES``, a body carrying a NUL byte, and 2000-deep nested parentheses all score
    NOT parsed and none of them raises.
    """


def test_h10_denominators() -> None:
    """H10 — rates count replies, and a sentinel never reaches a category denominator.

    Accept when: a run holding sentinels of both categories leaves every ``by_category`` block's
    ``records`` free of them; a fault is excluded from ``replies`` and from all three numerators;
    and the category ``records`` sum plus the sentinel row count equals ``record_count``.
    """


def test_h11_undefined_rates() -> None:
    """H11 — an undefined rate is None, never 0.0.

    Accept when: a category whose every record is a fault reports ``replies`` 0 and all three rates
    ``None``; the encoded stats.json spells them ``null``; and a category with replies but zero
    fenced replies reports ``0.0``, so the two cases stay distinguishable on disk.
    """


def test_h12_canonical_stats_bytes() -> None:
    """H12 — stats.json is canonical and carries no clock.

    Accept when: the encoded bytes are indent-2 with exactly one trailing newline; ``by_category``
    keys appear in ``CATEGORIES`` declaration order; every stats struct's ``__struct_fields__``
    equals a hand-stated exact tuple; and no field name or encoded byte carries a timestamp.
    """


def test_h13_golden_statistic() -> None:
    """H13 — the golden's statistic equals a hand-stated value, never a re-derived one.

    Accept when: ``derive_stats`` over tests/golden/capture-golden-v1/ equals a literal built in
    this file — one reply per category, the complicated reply truncated, the simple one not, zero
    fences, both parse rates hand-stated, and one sentinel row carrying a 503 and no rate.
    """


def test_h14_resume_overwrite() -> None:
    """H14 — a populated run directory refuses, resumes or restarts, never mixes.

    Accept when: a populated directory refuses by default with zero requests issued; the resume
    form drives ONLY the missing prompt ids and preserves the committed rows byte for byte; the
    resume form refuses when the rebuilt manifest disagrees with the committed one in any field
    but ``record_count``; and the overwrite form restarts from empty.
    """


def test_h15_cli() -> None:
    """H15 — the two subcommands exit as contracted.

    Accept when: ``stats`` returns 0 on the golden and 1 on a broken run; ``stats`` with no
    argument grades every run under the captures root; ``stats --write`` regenerates a deleted or
    stale stats.json to byte-identical content; and a non-finite or non-positive timeout refuses
    before any request is issued.
    """
