# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent tool oracle: owned CSV targets, then the user's formula target."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol, cast

from oracle_request import Neutral, oracle_formula_target
from paste_in_support import StoredFile
from verifier.pysrc import DeclaredTarget, Verified, spec, verify_python_source
from verifier.pysrc.verify import Verdict
from webui.paste_in.verdicts import CHART_NOT_PRODUCED, CHART_PRODUCED


class Verifier(Protocol):
    def __call__(self, source: str, /, *, declared_target: DeclaredTarget) -> Verdict: ...


class RequestParser(Protocol):
    def __call__(self, text: str, /) -> Neutral | None: ...


@dataclass(frozen=True, slots=True)
class _UnfixedInterval:
    """The skeleton tip lacks Interval; this placeholder exists only until the core lands."""

    start: spec.Expr
    stop: spec.Expr


def _leaf(node: Neutral) -> spec.Expr:
    tag = node[0]
    if tag == "num":
        return spec.Num(cast(Fraction, node[1]))
    if tag == "var":
        return spec.Var()
    if tag == "const":
        return spec.Const(cast(spec.ConstName, node[1]))
    raise ValueError


def _expr(node: Neutral) -> spec.Expr:
    tag = node[0]
    if tag in {"num", "var", "const"}:
        return _leaf(node)
    if tag == "neg":
        return spec.Neg(_expr(cast(Neutral, node[1])))
    if tag == "fn":
        return spec.Fn(cast(spec.FnName, node[1]), _expr(cast(Neutral, node[2])))
    if tag == "bin":
        return spec.Bin(
            cast(spec.BinOp, node[1]),
            _expr(cast(Neutral, node[2])),
            _expr(cast(Neutral, node[3])),
        )
    raise ValueError


def _formula_target(neutral: Neutral) -> spec.FormulaTarget:
    """Convert our neutral tree, never by calling the production request parser."""
    if neutral[0] != "target":
        raise ValueError
    domain = cast(Neutral, neutral[2])
    a, b = _expr(cast(Neutral, domain[1])), _expr(cast(Neutral, domain[2]))
    if domain[0] == "interval":
        constructor = cast(
            Callable[[spec.Expr, spec.Expr], spec.Grid],
            vars(spec).get("Interval", _UnfixedInterval),
        )
        grid = constructor(a, b)
    elif domain[0] == "grid":
        grid = spec.Grid(a, b, cast(int, domain[3]))
    else:
        raise ValueError
    return spec.FormulaTarget(y=_expr(cast(Neutral, neutral[1])), grid=grid)


@dataclass(frozen=True, slots=True)
class ToolContext:
    user_id: str | None
    attachments: Sequence[Mapping[str, object]]
    stored: Mapping[str, StoredFile]
    user_message: object = None


def oracle_draw_figure(
    program: str,
    context: ToolContext,
    *,
    verify: Verifier = verify_python_source,
    parse: RequestParser = oracle_formula_target,
) -> str:
    """Only a path mismatch advances the scan; the user's formula candidate is last.

    Attachment metadata authorizes no bytes or path: its top-level id selects a row, and the
    ownership-checked row supplies filename and content. Formula bytes come solely from the
    user's current message, independently parsed by `oracle_request`; the same message rides every
    dataset target as the request its column names anchor against (Q8).
    """
    if not context.user_id:
        return CHART_NOT_PRODUCED
    request = context.user_message if isinstance(context.user_message, str) else None
    for attachment in context.attachments:
        file_id = attachment.get("id")
        if not isinstance(file_id, str):
            continue
        row = context.stored.get(file_id)
        if row is None or row.user_id != context.user_id:
            continue
        target = spec.DatasetTarget(
            path=f"/mnt/uploads/{row.filename}", content=row.content, request=request
        )
        verdict = verify(program, declared_target=target)
        if isinstance(verdict, Verified):
            return CHART_PRODUCED
        if verdict.code != "target_mismatch":
            return CHART_NOT_PRODUCED
    neutral = parse(request) if request is not None else None
    if neutral is not None:
        verdict = verify(program, declared_target=_formula_target(neutral))
        if isinstance(verdict, Verified):
            return CHART_PRODUCED
    return CHART_NOT_PRODUCED
