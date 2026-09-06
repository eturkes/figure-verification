# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Structural gate for the python-mode capture record format (contract .agent/contracts/m12u6.md).

Predicates R1-R11 live in capture.record and are called here, never restated: a test that
re-implements a check pins its own copy instead of the shipped one. What this file adds on top of
the calls is what the validator cannot check about ITSELF -- strict-decode refusal against
near-miss inputs, the closed predicate set, the hand-authored golden run, one-field mutations that
must kill exactly one predicate each, the outbound body shape, the injected subprocess seams, and
the CLI.

SEED STATE: every predicate below is skip-marked with its acceptance check in its docstring. A
filled test drops its skip mark. capture.record ships real structs and constants with
NotImplementedError bodies, so a correctly filled test fails RED with NotImplementedError until
the implementation lands.
"""

import pytest

_SEED = "M12.6a seed: fill against .agent/contracts/m12u6.md"


@pytest.mark.skip(reason=_SEED)
def test_r1_versions() -> None:
    """R1: check_versions returns [] on a sound run, and a failure line naming the offending
    record when a record or the manifest carries a foreign mode or version."""


@pytest.mark.skip(reason=_SEED)
def test_r2_unguided() -> None:
    """R2: check_unguided returns [] on a sound run; a record whose request_keys adds, drops or
    reorders a key fails, and a record naming any member of BANNED_REQUEST_KEYS fails."""


@pytest.mark.skip(reason=_SEED)
def test_r3_run_identity() -> None:
    """R3: check_run_identity returns [] on a sound run; a directory renamed away from
    manifest.run, a record carrying a different run, a wrong record_count and a duplicated
    prompt_id each fail."""


@pytest.mark.skip(reason=_SEED)
def test_r4_corpus_binding() -> None:
    """R4: check_corpus_binding returns [] on a sound run; an unknown prompt_id, a mismatched
    category/idiom/dataset_name and a prompt_sha256 that is not sha256 of the re-rendered capture
    prompt each fail."""


@pytest.mark.skip(reason=_SEED)
def test_r5_run_scope() -> None:
    """R5: check_run_scope returns [] for a design run holding design plus sentinel rows, and
    fails for a heldout row inside a design run."""


@pytest.mark.skip(reason=_SEED)
def test_r6_outcome_shape() -> None:
    """R6: check_outcome_shape returns [] for a 200 record with all five reply fields present and
    error None, and for a fault record with all five absent and a non-empty error. Each half-shape
    fails: a 200 missing any of the five, a 200 carrying an error, a fault carrying content, a
    fault whose error is None or empty."""


@pytest.mark.skip(reason=_SEED)
def test_r7_content_integrity() -> None:
    """R7: check_content_integrity returns [] when content_sha256 and content_bytes describe
    content exactly; a wrong digest and a wrong byte count each fail. Include one non-ASCII reply
    so byte length is proved to be UTF-8 bytes, never character count."""


@pytest.mark.skip(reason=_SEED)
def test_r8_usage() -> None:
    """R8: check_usage returns [] on coherent usage; a total that is not prompt + completion, a
    negative count and a finish_reason outside FINISH_REASONS each fail."""


@pytest.mark.skip(reason=_SEED)
def test_r9_canonical_bytes() -> None:
    """R9: check_canonical_bytes returns [] for a run written by write_run; it fails when
    records.ndjson is re-ordered, re-indented, given a blank trailing line, or when run.json is
    re-encoded in any non-canonical form, even though every decode still succeeds."""


@pytest.mark.skip(reason=_SEED)
def test_r10_provenance() -> None:
    """R10: check_provenance returns [] on a run stamped from the live tree; a non-40-hex
    git_commit, a non-64-hex lock or prompt digest, a capture_prompt_sha256 other than
    CAPTURE_PROMPT_SHA256, and a model_repo_id / model_revision / engine_dtype that disagrees with
    the live pin each fail. A None git_commit is admitted."""


@pytest.mark.skip(reason=_SEED)
def test_r11_request_reproduces() -> None:
    """R11: check_request_reproduces returns [] when every record's request_sha256 equals the sha
    of build_request_body over the re-rendered prompt and the manifest's model, max_tokens and
    temperature; changing any of those four inputs in the manifest or the record fails."""


@pytest.mark.skip(reason=_SEED)
def test_i1_closed_predicate_set() -> None:
    """I1: PREDICATES keys equal the hand-stated literal ("R1".."R11") and every value is the
    module-level function of the matching name. Hand-state the tuple; never derive it from the
    dict under test."""


@pytest.mark.skip(reason=_SEED)
def test_i2_strict_decode() -> None:
    """I2: decode_run and decode_records refuse near-miss inputs of the same family -- an unknown
    field, an absent required field, a wrong version, a wrong mode, a float where an int is
    declared, an NDJSON line that is not an object, and a blank line beyond the canonical trailing
    newline. Each raises rather than returning a partial value."""


@pytest.mark.skip(reason=_SEED)
def test_i3_golden_run() -> None:
    """I3: the hand-authored golden at tests/golden/capture-golden-v1/ re-encodes byte-identically
    from structs built by hand in this test (encode_run and encode_records both), decodes back to
    equal structs, and validate() returns [] on it -- the positive control for every predicate."""


@pytest.mark.skip(reason=_SEED)
def test_i4_near_miss_refusal() -> None:
    """I4: for each of R1-R11, one field mutation of the golden run makes that predicate fail; a
    mutation kills its own predicate and the run stays otherwise loadable. Drive this from a
    hand-stated table of (predicate id, mutation) so a new predicate cannot enter uncovered."""


@pytest.mark.skip(reason=_SEED)
def test_i5_no_wall_clock() -> None:
    """I5: __struct_fields__ of CaptureRecord, RunManifest, Provenance, RepoProvenance,
    ServiceProvenance, HostProvenance and Usage equal hand-stated exact tuples, and no field name
    or encoded byte of the golden carries a timestamp. A new field cannot enter unnoticed."""


@pytest.mark.skip(reason=_SEED)
def test_i6_request_body_shape() -> None:
    """I6: build_request_body emits exactly REQUEST_KEYS at the top level, one user message whose
    content is the rendered prompt verbatim, and identical bytes across repeated calls. No
    guidance key appears for any input, including a prompt that spells one."""


@pytest.mark.skip(reason=_SEED)
def test_i7_subprocess_seam() -> None:
    """I7: collect_repo_provenance and collect_host_provenance take an injected runner. A missing
    tool, a non-zero return code and unparseable output each degrade as contracted -- git to
    (None, False), nvidia-smi to None -- and never raise. A well-formed nvidia-smi line parses
    into HostProvenance with memory as an int."""


@pytest.mark.skip(reason=_SEED)
def test_i8_cli() -> None:
    """I8: main() returns 0 on the golden run and 1 with id-prefixed failure lines on stderr for a
    broken one, and with no argument it grades every directory under CAPTURES_ROOT."""
