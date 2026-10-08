# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.1 P1-P9: refusal places + the statement-role trace, positions only, no source bytes.

Contract: `.agent/archive/contracts/m18u1.md`. The implementation stays unread.
"""

import ast
import re
import sys
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast, get_args, get_type_hints

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from hypothesis.strategies import DrawFn, SearchStrategy

from test_pysrc_position_cases import (
    ADMISSION,
    ALL_WITNESSES,
    DATASET,
    FORMULA,
    PASS,
    POST_PROJECTION,
    PRESCAN,
    PROJECTION,
    TARGET,
    Coordinates,
    TraceLiteral,
    Witness,
)
from verifier.pysrc import Refused, Verdict, Verified, verify_python_source
from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.errors import PysrcRefusalError
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits
from verifier.pysrc.prescan import prescan
from verifier.pysrc.project import project

_ROLES = (
    "import",
    "source",
    "data",
    "mark",
    "title",
    "xlabel",
    "ylabel",
    "decoration",
    "layout",
    "show",
)


class _Span(Protocol):
    line: int
    column: int
    end_line: int
    end_column: int


class _Step(Protocol):
    role: str
    span: _Span


class _Located(Protocol):
    at: tuple[_Span, ...]


class _Traced(Protocol):
    trace: tuple[_Step, ...]


def _coordinates(span: _Span) -> Coordinates:
    return span.line, span.column, span.end_line, span.end_column


def _at(value: object) -> tuple[Coordinates, ...]:
    return tuple(_coordinates(span) for span in cast(_Located, value).at)


def _trace(value: object) -> TraceLiteral:
    return tuple((step.role, _coordinates(step.span)) for step in cast(_Traced, value).trace)


def _run(witness: Witness) -> Verdict:
    result = verify_python_source(
        witness.source, declared_target=witness.target, limits=witness.limits
    )
    if witness.code is None:
        assert isinstance(result, Verified), (witness.name, result)
    else:
        assert isinstance(result, Refused), (witness.name, result)
        assert result.code == witness.code, witness.name
    return result


def _boundaries(piece: str) -> set[int]:
    offset = 0
    result = {0}
    for character in piece:
        offset += len(character.encode("utf-8", errors="surrogatepass"))
        result.add(offset)
    return result


def _assert_valid(source: str | bytes, result: Verdict) -> None:
    spans = [step.span for step in cast(_Traced, result).trace]
    if isinstance(result, Refused):
        spans.extend(cast(_Located, result).at)
    _assert_valid_spans(source, tuple(spans))


def _assert_valid_spans(source: str | bytes, spans: tuple[_Span, ...]) -> None:
    if isinstance(source, bytes):
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError:
            # An undecodable byte has a byte extent but no UTF-8 character boundary.
            pieces = re.split(rb"\r\n|\r|\n", source)
            for span in spans:
                assert 1 <= span.line <= span.end_line <= len(pieces)
                assert 0 <= span.column <= len(pieces[span.line - 1])
                assert 0 <= span.end_column <= len(pieces[span.end_line - 1])
                assert (span.line, span.column) <= (span.end_line, span.end_column)
            return
    else:
        text = source
    lines = re.split(r"\r\n|\r|\n", text)
    for span in spans:
        assert 1 <= span.line <= span.end_line <= len(lines)
        assert (span.line, span.column) <= (span.end_line, span.end_column)
        assert span.column in _boundaries(lines[span.line - 1])
        assert span.end_column in _boundaries(lines[span.end_line - 1])


def _assert_no_source(value: object) -> None:
    if is_dataclass(value) and not isinstance(value, type):
        for item in fields(cast(Any, value)):
            _assert_no_source(getattr(value, item.name))
    elif isinstance(value, tuple):
        for item in value:
            _assert_no_source(item)
    else:
        assert type(value) is int or (type(value) is str and value in _ROLES), repr(value)


def _assert_witness(witness: Witness) -> Verdict:
    result = _run(witness)
    if isinstance(result, Refused):
        assert _at(result) == witness.at
    assert _trace(result) == witness.trace
    _assert_valid(witness.source, result)
    return result


def test_p1_role_span_step_vocabulary_is_hand_stated() -> None:
    """P1: ordered roles/fields, frozen slots, integer spans, stdlib imports alone."""
    position = import_module("verifier.pysrc.position")
    role = position.Role
    assert get_args(getattr(role, "__value__", role)) == _ROLES
    assert tuple(item.name for item in fields(position.Span)) == (
        "line",
        "column",
        "end_line",
        "end_column",
    )
    assert tuple(item.name for item in fields(position.Step)) == ("role", "span")
    assert get_type_hints(position.Span) == {
        "line": int,
        "column": int,
        "end_line": int,
        "end_column": int,
    }
    assert get_args(position.Trace.__value__) == (position.Step, Ellipsis)
    span = position.Span(2, 3, 4, 5)
    step = position.Step("data", span)
    assert tuple(position.Span.__slots__) == ("line", "column", "end_line", "end_column")
    assert tuple(position.Step.__slots__) == ("role", "span")
    assert not hasattr(span, "__dict__")
    assert not hasattr(step, "__dict__")
    for value, field, replacement in ((span, "line", 9), (step, "role", "mark")):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)
    tree = ast.parse(Path(cast(str, position.__file__)).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in sys.stdlib_module_names for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert node.module is not None
            assert node.module.split(".")[0] in sys.stdlib_module_names


@st.composite
def _programs(draw: DrawFn) -> str:
    statements = list(
        draw(
            st.sampled_from(
                (
                    (
                        "import numpy as np",
                        "import matplotlib.pyplot as plt",
                        "x = np.linspace(0, 1, num=3)",
                        "y = np.sin(x)",
                        "plt.plot(x, y)",
                        "plt.show()",
                    ),
                    (
                        "import pandas as pd",
                        "import matplotlib.pyplot as plt",
                        'df = pd.read_csv("data.csv")',
                        'plt.bar(df["site"], df["value"])',
                        "plt.show()",
                    ),
                )
            )
        )
    )
    fragments = draw(
        st.lists(
            st.sampled_from(
                (
                    "",
                    "# 題🙂",
                    'plt.title("題🙂")',
                    'plt.title("""題\n値""")',
                    'plt.title("""題\r値""")',
                    'plt.title("題\x85値\u2028終")',
                    "年 = 1",
                    "年 = missing",
                    "x = np.sinh(1)",
                    "x = [i for i in (1, 2)]",
                    "plt.figure()",
                    "import seaborn as sns",
                    "\tpass",
                    "\x00",
                    "\ud800",
                )
            ),
            max_size=4,
        )
    )
    for fragment in fragments:
        statements.insert(draw(st.integers(min_value=0, max_value=len(statements))), fragment)
    separators = draw(
        st.lists(
            st.sampled_from(("\n", "\r\n", "\r", "; ", ";\t")),
            min_size=len(statements),
            max_size=len(statements),
        )
    )
    return "".join(
        statement + separator for statement, separator in zip(statements, separators, strict=True)
    )


_PROPERTY_LIMITS: SearchStrategy[PysrcLimits] = st.sampled_from(
    (
        DEFAULT_LIMITS,
        replace(DEFAULT_LIMITS, max_source_bytes=16),
        replace(DEFAULT_LIMITS, max_line_bytes=20),
        replace(DEFAULT_LIMITS, max_tokens=20),
        replace(DEFAULT_LIMITS, max_bracket_depth=2),
        replace(DEFAULT_LIMITS, max_indent_depth=1),
    )
)


@given(source=_programs(), limits=_PROPERTY_LIMITS)
@example(source="", limits=DEFAULT_LIMITS)
@example(source=FORMULA, limits=DEFAULT_LIMITS)
@example(source=DATASET.replace("\n", "\r\n"), limits=DEFAULT_LIMITS)
@example(source=FORMULA.replace("\n", "\r"), limits=DEFAULT_LIMITS)
@example(source=FORMULA.replace("x =", "x\t="), limits=DEFAULT_LIMITS)
@example(source='年 = "\ud800"', limits=DEFAULT_LIMITS)
def test_p2_every_emitted_span_is_valid_and_verify_never_raises(
    source: str, limits: PysrcLimits
) -> None:
    """P2: universal-newline pieces + UTF-8 boundaries, including surrogates and mixed joins."""
    target = TARGET if "import pandas as pd" in source else None
    result = verify_python_source(source, declared_target=target, limits=limits)
    assert isinstance(result, (Verified, Refused))
    _assert_valid(source, result)
    _assert_no_source(cast(_Traced, result).trace)
    if isinstance(result, Refused):
        _assert_no_source(cast(_Located, result).at)


def test_p2_tokenizer_mixed_cr_nonascii_is_total() -> None:
    """P2/P3: tokenizer UnicodeDecodeError refuses without inventing a source location."""
    source = '年 = 1\rplt.title("題")\r値 = "終'
    result = verify_python_source(source)
    assert isinstance(result, Refused)
    assert result.code == "source_not_tokenizable"
    assert _at(result) == ()
    assert _trace(result) == ()
    _assert_valid(source, result)


@pytest.mark.parametrize("witness", PRESCAN, ids=lambda witness: witness.name)
def test_p3_prescan_places(witness: Witness) -> None:
    """P3: each prescan refusal, UTF-8 offsets, bare CR, NEL, EOF point + clamp."""
    _assert_witness(witness)


def test_p3_prescan_undecodable_bytes() -> None:
    """P3/P9: the first bad byte, not the next one or the valid non-ASCII prefix."""
    source = "年 = 1\r\n題 = ".encode() + b"\xff\xfe"
    with pytest.raises(PysrcRefusalError) as caught:
        prescan(source, DEFAULT_LIMITS)
    assert caught.value.code == "source_not_utf8"
    assert _at(caught.value) == ((2, 6, 2, 7),)
    _assert_no_source(cast(_Located, caught.value).at)
    _assert_valid_spans(source, cast(_Located, caught.value).at)


@pytest.mark.parametrize("witness", ADMISSION, ids=lambda witness: witness.name)
def test_p4_admission_places(witness: Witness) -> None:
    """P4: innermost expression or statement fallback; SyntaxError character-to-byte conversion."""
    source = witness.source
    assert prescan(source.encode(), witness.limits) == source
    with pytest.raises(PysrcRefusalError) as caught:
        parse_admitted(source)
    assert caught.value.code == witness.code
    assert _at(caught.value) == witness.at
    _assert_witness(witness)


@pytest.mark.parametrize("witness", PROJECTION, ids=lambda witness: witness.name)
def test_p5_projection_places(witness: Witness) -> None:
    """P5: admitted programs; nested substitution location then mark, otherwise statement."""
    tree = parse_admitted(witness.source)
    with pytest.raises(PysrcRefusalError) as caught:
        project(tree)
    assert caught.value.code == witness.code
    assert _at(caught.value) == witness.at
    _assert_witness(witness)


@pytest.mark.parametrize("witness", POST_PROJECTION, ids=lambda witness: witness.name)
def test_p6_post_projection_places(witness: Witness) -> None:
    """P6: source/label hints alone; every other post-projection code has no fault span."""
    project(parse_admitted(witness.source))
    _assert_witness(witness)


@pytest.mark.parametrize("witness", PASS, ids=lambda witness: witness.name)
def test_p7_trace_literals(witness: Witness) -> None:
    """P7: exact traces, one step per statement; pure classifier agrees with the verdict."""
    tree = parse_admitted(witness.source)
    project(tree)
    before = ast.dump(tree, include_attributes=True)
    result = _assert_witness(witness)
    projection = import_module("verifier.pysrc.project")
    traced = cast(tuple[_Step, ...], projection.statement_trace(tree))
    assert tuple((step.role, _coordinates(step.span)) for step in traced) == witness.trace
    assert traced == cast(_Traced, result).trace
    assert projection.statement_trace(tree) == traced
    assert ast.dump(tree, include_attributes=True) == before


def test_p8_positions_stay_outside_verdict_identity() -> None:
    """P8: new fields excluded from equality/hash, defaults empty, legacy exceptions intact."""
    position = import_module("verifier.pysrc.position")
    verdicts = import_module("verifier.pysrc.verify")
    errors = import_module("verifier.pysrc.errors")
    at = (position.Span(1, 2, 3, 4),)
    trace = (position.Step("mark", at[0]),)
    ordinary = Refused("no_mark")
    located = verdicts.Refused("no_mark", at=at, trace=trace)
    assert located == ordinary
    assert hash(located) == hash(ordinary)
    assert len({located, ordinary}) == 1
    assert _at(ordinary) == ()
    assert _trace(ordinary) == ()
    base = verify_python_source(FORMULA)
    assert isinstance(base, Verified)
    plain = verdicts.Verified(base.spec, base.table, base.certificate)
    traced = verdicts.Verified(base.spec, base.table, base.certificate, trace=trace)
    assert plain == traced
    assert hash(plain) == hash(traced)
    assert len({plain, traced}) == 1
    assert _trace(plain) == ()
    for cls, names in ((Refused, ("at", "trace")), (Verified, ("trace",))):
        metadata = {item.name: item for item in fields(cls)}
        for name in names:
            assert metadata[name].default == ()
            assert metadata[name].compare is False
    error = errors.PysrcRefusalError("x")
    assert error.code == "x"
    assert error.at == ()
    assert error.role is None
    located_error = errors.PysrcRefusalError("x", at=at, role="mark")
    assert located_error.at is at
    assert located_error.role == "mark"
    assert str(located_error) == "x"
    with pytest.raises(TypeError):
        errors.PysrcRefusalError("x", at, "mark")


@pytest.mark.parametrize("witness", ALL_WITNESSES, ids=lambda witness: witness.name)
def test_p9_positions_hold_no_source_bytes(witness: Witness) -> None:
    """P9: every diagnostic leaf is an exact integer or a member of the closed role set."""
    result = _run(witness)
    _assert_no_source(cast(_Traced, result).trace)
    if isinstance(result, Refused):
        _assert_no_source(cast(_Located, result).at)
    _assert_valid(witness.source, result)


@pytest.mark.parametrize("witness", ALL_WITNESSES, ids=lambda witness: witness.name)
def test_witness_codes_and_stage_prerequisites(witness: Witness) -> None:
    """Every literal witness reaches its contracted verdict on the uninstrumented base too."""
    _run(witness)
    if witness in PROJECTION:
        parse_admitted(witness.source)
    elif witness in POST_PROJECTION + PASS:
        project(parse_admitted(witness.source))


def test_p2_coordinate_validator_accepts_contract_boundaries_and_rejects_bad_spans() -> None:
    """Positive controls: validator cannot turn missing diagnostics into a vacuous pass."""
    position = import_module("verifier.pysrc.position")
    verdicts = import_module("verifier.pysrc.verify")
    source = "年\r\n題\r値\n終\udfff\x85"
    good = (
        position.Span(1, 0, 1, 3),
        position.Span(2, 0, 3, 3),
        position.Span(4, 3, 4, 6),
        position.Span(4, 8, 4, 8),
    )
    _assert_valid(source, verdicts.Refused("no_mark", at=good))
    for coordinates in (
        (0, 0, 1, 0),
        (1, 0, 5, 0),
        (2, 0, 1, 0),
        (1, 1, 1, 2),
        (1, 0, 1, 4),
        (4, 6, 4, 3),
    ):
        with pytest.raises(AssertionError):
            _assert_valid(source, verdicts.Refused("no_mark", at=(position.Span(*coordinates),)))
