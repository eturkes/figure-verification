# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Core plot spec — what the verifier claims an admitted program draws.

Stdlib-only frozen dataclasses, deliberately not the `msgspec` structs of `verifier.schema`: M14
inlines this package into one pasted file, so a dependency here becomes a dependency there.

The spec holds NO `ast` node, line number or source text. Two consequences that are the point:
a projection is comparable by value, and no model-authored byte can ride a verdict into a log.

Numbers are exact `Fraction`. A source `0.1` is projected as `Fraction(0.1)` -- the exact float64
the executed program actually passes to numpy -- and NOT as `Fraction(1, 10)`, which is the decimal
a reader means but not the value that runs. Projection is faithful to execution; the gap between
the two spellings belongs to the comparison layer, which has to state which one it is checking.
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

# Closed vocabularies. Each mirrors an `admit.py` allowlist entry, stripped of its `np.` alias:
# admission decides which SOURCE spellings exist, projection names the MEANINGS they map onto.
type FnName = Literal["sin", "cos", "tan", "exp", "log", "sqrt", "abs"]
type ConstName = Literal["pi", "e"]
type BinOp = Literal["add", "sub", "mul", "div", "pow"]
# Sampled functions are line or scatter, never bar: a bar's length encodes a categorical magnitude
# from a zero baseline, which a continuous sample has no claim to. Mirrors `schema.FormulaMark`.
type FormulaMark = Literal["line", "scatter"]
# The dataset arm adds bar: a CSV column carries the categorical magnitude a bar's length claims.
type DatasetMark = Literal["line", "scatter", "bar"]


@dataclass(frozen=True, slots=True)
class Num:
    """One exact literal."""

    value: Fraction


@dataclass(frozen=True, slots=True)
class Var:
    """The grid variable -- the sample point. Nameless on purpose.

    A projected expression has exactly one free variable, so carrying the model's chosen spelling
    would make two programs that compute the same thing project to unequal specs. It also lets the
    bound form (`x = np.linspace(...)`) and the inline form (`plt.plot(np.linspace(...), ...)`)
    compare equal, which is what makes the two spellings one projection.
    """


@dataclass(frozen=True, slots=True)
class Const:
    """`np.pi` or `np.e`, held symbolically -- neither has an exact `Fraction`."""

    name: ConstName


@dataclass(frozen=True, slots=True)
class Neg:
    operand: "Expr"


@dataclass(frozen=True, slots=True)
class Fn:
    name: FnName
    arg: "Expr"


@dataclass(frozen=True, slots=True)
class Bin:
    op: BinOp
    left: "Expr"
    right: "Expr"


type Expr = Num | Var | Const | Neg | Fn | Bin


@dataclass(frozen=True, slots=True)
class Grid:
    """The sample points, as one shape for every admitted grid call.

    `stop` is INCLUSIVE -- it is the last sample, not `np.arange`'s excluded bound. Normalizing
    `arange` onto this triple is what lets a projection compare two source spellings of one grid
    by value, and it is why `arange` needs rational bounds while `linspace` does not.
    """

    start: Expr
    stop: Expr
    samples: int


@dataclass(frozen=True, slots=True)
class Labels:
    """Everything the figure says about itself, for tier-3 publication.

    Carried through the projection rather than discarded because the certificate publishes what
    was verified in plain words, and a label that disagrees with the computation is a finding.
    """

    title: str | None = None
    xlabel: str | None = None
    ylabel: str | None = None
    series: str | None = None
    legend: bool = False
    grid: bool = False


@dataclass(frozen=True, slots=True)
class FormulaPlot:
    """A function sampled over a grid: the arm where the request sentence is the specification."""

    mark: FormulaMark
    grid: Grid
    y: Expr
    labels: Labels


@dataclass(frozen=True, slots=True)
class DatasetRef:
    """The user's file, as the program names it.

    `path` is the EXACT string literal passed to `read_csv`, never a resolved or normalized path:
    binding it to the bytes the user actually uploaded is a CHECK the comparison layer performs
    against a caller-supplied target, not a fact the projection may invent. Keeping it verbatim is
    what lets that check compare the program's own claim against the user's own artifact.
    """

    path: str


@dataclass(frozen=True, slots=True)
class Column:
    """One column of the bound frame, named by the string literal that selected it."""

    name: str


@dataclass(frozen=True, slots=True)
class DatasetPlot:
    """Two columns of the user's file: the clinical spine, and the demo's acceptance surface.

    Bar is admitted here and refused in the formula arm. That asymmetry is G5, not an oversight: a
    bar's length encodes a categorical magnitude from a zero baseline, which a CSV column supports
    and a continuous sample has no claim to.
    """

    mark: DatasetMark
    source: DatasetRef
    x: Column
    y: Column
    labels: Labels


# The union M13.4 widened. Every total map over it needs its own exact-set pin: this repo has
# shipped a defect where a union grew and a total map over it stayed green.
type CorePlotSpec = FormulaPlot | DatasetPlot
