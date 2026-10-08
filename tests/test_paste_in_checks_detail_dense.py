# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.2 E9b (reviewer-2 K5-F1): a refusal spanning thousands of lines keeps the bounded cost.

A 19,006-byte program whose one string statement spans 19,001 lines refuses with that whole span:
the listing's neighbour scan was quadratic in the marked lines (12.4 s render, 12.0 s diagnostics
against the 5 s deadline), and the renderer runs on the event loop.
"""

import asyncio
import time

from verifier.pysrc import Refused, verify_python_source
from webui.paste_in.checks import Evidence, breakdown_html
from webui.paste_in.filter import _diagnose


def test_real_dense_multiline_refusal_renders_in_half_second() -> None:
    program = '"""' + "\n" * 19_000 + '"""'
    verdict = verify_python_source(program)
    assert isinstance(verdict, Refused)
    assert verdict.code == "statement_not_admitted"
    assert len(verdict.at) == 1
    assert (verdict.at[0].line, verdict.at[0].end_line) == (1, 19001)
    started = time.perf_counter()
    document = breakdown_html(
        verdict.code,
        japanese=False,
        anchoring="strict",
        evidence=Evidence(program, verdict.at, verdict.trace),
    )
    elapsed = time.perf_counter() - started
    assert len(document.encode()) <= 262144
    assert elapsed < 0.5, f"dense real refusal render took {elapsed:.3f}s; bound=0.500s"


def test_real_dense_multiline_refusal_diagnostics_keep_five_second_deadline() -> None:
    program = '"""' + "\n" * 19_000 + '"""'
    verdict = verify_python_source(program)
    assert isinstance(verdict, Refused)
    events: list[object] = []

    async def emit(event: dict[str, object]) -> None:
        events.append(event["type"])

    started = time.perf_counter()
    asyncio.run(
        _diagnose(emit, verdict.code, None, "strict", Evidence(program, verdict.at, verdict.trace))
    )
    elapsed = time.perf_counter() - started
    assert elapsed < 5.25, f"diagnostics took {elapsed:.3f}s; shared deadline=5s; events={events}"
