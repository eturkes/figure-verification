# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.1 the outlet filter authors the verdict on both paths.

Contract: `.agent/contracts/m10u1.md`. Each docstring carries its predicate's acceptance check; the
check is the test's specification and the contract's wording wins wherever a body would assert
more.

Skeleton: each body is `pytest.skip`, retired at M10.1's close together with this line.
"""

import pytest


def test_f1_every_draw_figure_call_that_receives() -> None:
    """F1: Every `draw_figure` call that receives a `__request__` writes ONE receipt to
    `__request__.state` BEFORE any verification, replacing any earlier receipt of the same request ⇒
    the LAST call of a completion decides. Receipt = frozen plain data: `program: str`, `file_ids:
    tuple[str, ...]` (the owned attachment ids the tool scanned, chat order), `request_text: str |
    None` (`__metadata__["user_message"]["content"]` when a `str`). No verdict, no `Verified`, no
    bytes.

    Accept: Fake request: two calls ⇒ state holds the second receipt; field types exact; a call that
    raises inside verification still left its receipt; the tool's return value set =
    `TOOL_VERDICTS`.
    """
    pytest.skip("owned by **M10.1** (`.agent/spec.md` Deferred)")


def test_f2_authenticity_the_filter_reads_a_receipt() -> None:
    """F2: AUTHENTICITY: the filter reads a receipt from `__request__.state` ONLY. Message
    `content`, `output`, tool-result text, citation `sources`, `body` fields and `__metadata__` can
    never produce PASS.

    Accept: `body` whose assistant text = `CHART_PRODUCED`, a PNG data URI, a serialized receipt, or
    the pass notice, with no state receipt ⇒ FAIL text, no files event, no RPC; `__request__` absent
    or state without the attribute ⇒ FAIL.
    """
    pytest.skip("owned by **M10.1** (`.agent/spec.md` Deferred)")


def test_f3_re_derivation_the_filter_re_fetches() -> None:
    """F3: RE-DERIVATION: the filter re-fetches every receipt file id through
    `Files.get_file_by_id_and_user_id` with the user id from `__user__` (never from the receipt),
    rebuilds the candidates exactly as the tool does (owned attachments in chat order, then the
    formula target of `request_text` LAST) through ONE shared function, and calls
    `verify_python_source` itself.

    Accept: A foreign or missing id ⇒ that candidate vanishes; receipt + `__user__` of another user
    ⇒ FAIL; the tool and the filter call the same selection function object (identity pinned); a
    receipt whose verdict the filter re-derives as `Refused` ⇒ FAIL even when the tool returned
    `CHART_PRODUCED`.
    """
    pytest.skip("owned by **M10.1** (`.agent/spec.md` Deferred)")


def test_f4_fail_totality_every_outcome_other_than() -> None:
    """F4: FAIL TOTALITY: every outcome other than F5's ⇒ the LAST assistant message's `content` =
    exactly `Figure verification failed, no image produced`, its `output` = exactly one completed
    assistant message item holding that text, no files event, earlier messages untouched. Covers: no
    receipt (a prose-only reply included), `Refused`, no candidate, RPC absent/raising/timing
    out/returning a non-dict, non-empty `stderr`, zero or ≥2 PNG data URIs in `stdout`, a data URI
    that is not base64 PNG.

    Accept: One case per listed outcome; model prose never survives in `content` or `output`.
    """
    pytest.skip("owned by **M10.1** (`.agent/spec.md` Deferred)")


def test_f5_pass_verified_exactly_one_well_formed() -> None:
    r"""F5: PASS: `Verified` + exactly one well-formed PNG data URI in `stdout` + empty `stderr` ⇒
    ONE `files` event `{'type': 'files', 'data': {'files': [{'type': 'image', 'url': <uri>}]}}` and
    `content` = `Figure verification passed` + `\n\n` + `certificate.interpretation`, `output` = one
    message item with the same text.

    Accept: Fake `__event_call__` returning one data URI ⇒ exact event + exact text; the
    interpretation bytes equal the re-derived certificate's.
    """
    pytest.skip("owned by **M10.1** (`.agent/spec.md` Deferred)")


def test_f6_rpc_shape_type_execute_python_data() -> None:
    """F6: RPC shape: `{'type': 'execute:python', 'data': {'id': <uuid4 str>, 'code': <str>,
    'session_id': __metadata__['session_id'], 'files': <list>}}`; `files` = exactly the one
    attachment the verified target consumed as `{'id', 'filename'}` (dataset arm) or `[]` (formula
    arm); `code` holds no substring `matplotlib`; the program travels base64-encoded and the wrapper
    decodes it to bytes equal to `receipt.program`; one RPC per completion at most; bounded by a
    timeout ≤ 60 s.

    Accept: Captured RPC per arm; decode(payload) == program; `'matplotlib' not in code`; a
    `Refused` path issues zero RPCs.
    """
    pytest.skip("owned by **M10.1** (`.agent/spec.md` Deferred)")


def test_f7_the_wrapper_trusted_generated_into_the() -> None:
    """F7: The wrapper (trusted, generated into the filter) loads the plotting stack without the
    literal name, installs its OWN `plt.show` that saves the current figure as ONE PNG data URI line
    then clears it, executes the decoded program, and calls that show once if the program never did.

    Accept: Static checks in the gate (F6); behaviour = one Node run over the installed Pyodide
    0.28.3 bundle (`.agent/measurements/`, outside the gate) on sentinel-simple + one line + one
    scatter + one no-show program: exactly one PNG line each, zero stderr.
    """
    pytest.skip("owned by **M10.1** (`.agent/spec.md` Deferred)")


def test_f8_packaging_artifacts_tool_filter_generate_paste() -> None:
    """F8: Packaging: `ARTIFACTS` = tool + filter; `generate_paste_in.py --check` covers both; the
    filter's import closure = stdlib + `open_webui` + the embedded core (B6 law);
    `webui/enforcement_filter.py` and every test importing it are deleted; bootstrap provisions the
    generated filter bytes as the ONE global active function, and smoke reads back byte equality +
    global + active.

    Accept: `--check` rc=0; B-series tests extended to the second artifact; smoke fails closed on a
    second active filter or drifted bytes.
    """
    pytest.skip("owned by **M10.1** (`.agent/spec.md` Deferred)")


def test_f9_demo_wiring_webui_settings_py_sets() -> None:
    """F9: Demo wiring: `webui/settings.py` sets `BYPASS_EMBEDDING_AND_RETRIEVAL=true`;
    `webui/model_stub.py` answers a pinned demo prompt with a legacy-mode `draw_figure` call
    carrying sentinel-simple's committed program, and a second pinned prompt with prose only.

    Accept: Settings pin test; stub classification tests per prompt.
    """
    pytest.skip("owned by **M10.1** (`.agent/spec.md` Deferred)")
