# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Figure verification for Open WebUI. GENERATED FILE -- do not edit.

Paste the whole file into Open WebUI. It imports the standard library and `open_webui`, which the
image already carries, and nothing else. There is no `requirements:` frontmatter and no network
call.

Regenerate with `uv run --locked python tools/generate_paste_in.py`. The same command with
`--check` fails when this file and its sources disagree, so an edit made here is lost at the next
gate run: change `webui/paste_in/` or `src/verifier/pysrc/` instead.
"""

import sys
import types

_SOURCES: dict[str, str] = {}

_SOURCES["verifier"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""verifier — trusted core for the verified-plot PoC.

Its job, as the trusted core: the model proposes only a restricted VPlot spec;
this package validates it, independently recomputes the plotted table from the
source data, runs the verification checks, and emits only verified output with a
provenance badge. See POC_SCOPE.md for the boundary and the claim this PoC makes.
"""

__version__ = "0.2.0"
'''

_SOURCES["verifier.pysrc.budget"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Consumer-neutral run-local logical-work admission.

A meter admits each consumer-defined non-negative charge atomically before the guarded work;
refusal preserves the prior count and reports the exact limit, consumption, and requested cost.

Lives in the portable core because `pysrc` may import no `verifier` sibling and the paste-in needs
a meter. The legacy JSON mode imports it FROM here rather than keeping a copy: two hand-maintained
meters is the fork the single-source ruling bans. The dependency runs sibling -> core only.
"""

from dataclasses import dataclass

__all__ = ["WorkBudget", "WorkBudgetExceededError"]


class WorkBudgetExceededError(Exception):
    """One atomic charge that would cross a cumulative work ceiling."""

    def __init__(self, *, limit: int, consumed: int, required: int) -> None:
        message = f"work limit {limit}: {consumed} consumed + {required} required"
        super().__init__(message)
        self.limit = limit
        self.consumed = consumed
        self.required = required


@dataclass(slots=True)
class WorkBudget:
    """Mutable cumulative meter shared across every operation in one consumer run."""

    limit: int
    consumed: int = 0

    def __post_init__(self) -> None:
        if type(self.limit) is not int or self.limit < 0:
            msg = f"work limit must be a non-negative integer, got {self.limit!r}"
            raise ValueError(msg)
        if type(self.consumed) is not int or not 0 <= self.consumed <= self.limit:
            msg = (
                "work consumption must be an integer between zero and the limit, "
                f"got {self.consumed!r}"
            )
            raise ValueError(msg)

    def charge(self, required: int) -> None:
        """Admit ``required`` atomically, or leave consumption unchanged and refuse."""
        if type(required) is not int or required < 0:
            msg = f"required work must be a non-negative integer, got {required!r}"
            raise ValueError(msg)
        if required > self.limit - self.consumed:
            raise WorkBudgetExceededError(
                limit=self.limit,
                consumed=self.consumed,
                required=required,
            )
        self.consumed += required
'''

_SOURCES["verifier.pysrc.errors"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Refusal and caller-error types for the portable core.

Two families, deliberately unrelated: `PysrcRefusalError` is a verdict about UNTRUSTED input and is
always convertible into a check result, while `PysrcCallerError` means the operator configured the
verifier wrongly and no verdict about the source exists. Collapsing them would let a
misconfiguration read as a refused program.

A refusal carries a closed `code` and never any bytes from the source. Echoing input back into a
message would smuggle model-authored text into logs, verdicts and, through those, into the operator
surface -- the one place this project must never let the model write.
"""

from typing import Literal

# Closed set. A new member needs a distinct fault shape, not a new phrasing of an existing one.
# Grouped by the stage that can raise it; a stage never raises another stage's code.
RefusalCode = Literal[
    # prescan
    "source_too_large",
    "source_not_utf8",
    "source_has_nul",
    "line_too_long",
    "source_not_tokenizable",
    "too_many_tokens",
    "nesting_too_deep",
    "unbalanced_brackets",
    "indent_too_deep",
    # admit
    "source_not_parsable",
    "statement_not_admitted",
    "expression_not_admitted",
    "import_not_admitted",
    "assign_target_not_admitted",
    "call_target_not_admitted",
    "keyword_not_admitted",
    "attribute_not_admitted",
    "operator_not_admitted",
    "literal_not_admitted",
    "name_not_bound",
    # project -- what an ADMITTED program fails to say about the figure it draws. Distinct from
    # admission: these bytes may run, and the refusal is that the verifier cannot state what they
    # would draw. A construct admitted without a projection rule lands on one of these, never on
    # silence.
    "no_mark",
    "multiple_marks",
    "mark_arity_not_projected",
    "mark_not_valid_for_arm",
    "x_not_a_grid",
    "y_not_over_grid",
    "grid_not_representable",
    "expression_not_projected",
    "label_not_literal",
    "name_rebound",
    "no_terminal",
    "statement_after_terminal",
    "statement_not_projected",
    # project, dataset arm -- each names a fault shape the formula arm cannot produce.
    "arm_ambiguous",
    "no_source",
    "multiple_sources",
    "source_not_literal",
    "column_not_literal",
    "column_not_from_source",
    # An admitted `groupby` chain whose MEANING the projection cannot state. Distinct from
    # `statement_not_projected`: the statement is a projectable kind, and distinct from
    # `column_not_from_source`: the columns may be perfectly valid. What is missing is a rule for
    # the shape -- `.reset_index()` re-spells the channels, a bare column selection reduces nothing.
    "aggregation_not_projected",
    # `plt.figure` after anything already drawn. The new figure would not contain it, so the
    # emitted artifact and the spec would disagree about what the chart holds. Distinct from
    # `statement_not_projected`: the call IS projectable, just not in that position.
    "figure_orphans_mark",
    # bind -- the submitted program versus the artifact the USER supplied. One code covers both
    # arms: the fault shape is "this program is not about your artifact", and which artifact is
    # evident from the program itself.
    "source_not_supplied",
    "target_mismatch",
    # A substitution (Q8): the program drops a CSV column the request names and plots one the
    # request never names. A request naming no column anchors nothing and never reaches this code.
    "column_not_requested",
    # recompute -- reading the user's bytes, then evaluating. `value_not_finite` is the SOLE
    # domain refusal: the evaluator reproduces numpy's IEEE results instead of raising, so every
    # domain and overflow fault arrives as a non-finite value and needs no classification.
    "csv_too_large",
    "csv_not_parsable",
    "column_not_present",
    "column_not_numeric",
    "value_not_in_profile",
    "value_not_finite",
    "work_budget_exceeded",
    # integrity -- what an otherwise-recomputable figure would misrepresent.
    "category_not_unique",
    "x_not_ordered",
    # G10 (Q16): a title, axis label or legend label names a CSV column the chart does not draw,
    # or -- over a reduction -- the summary word of another reduction.
    "label_not_consistent",
]


class PysrcRefusalError(Exception):
    """The submitted source is refused. `code` is the whole verdict; there is no free text."""

    def __init__(self, code: RefusalCode) -> None:
        super().__init__(code)
        self.code: RefusalCode = code


class PysrcCallerError(Exception):
    """The verifier was called wrongly -- a limit it cannot honour, or arguments that disagree with
    each other. Never a verdict about source, and never reachable from submitted bytes."""
'''

_SOURCES["verifier.pysrc.spec"] = r'''
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
# `barh` is the same claim rotated -- the length still encodes magnitude from a zero baseline, so it
# carries bar's integrity rules unchanged and differs only in the axis the renderer draws it on.
type DatasetMark = Literal["line", "scatter", "bar", "barh"]
# Grouped reductions, closed. Each one is a total function from a group's cells to one number, which
# is what lets recomputation reproduce it exactly; a reduction needing a parameter (quantile, std's
# delta degrees of freedom) would need that parameter projected and is therefore not a member.
type Reduction = Literal["sum", "mean", "min", "max"]


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

# The deepest expression tree the core walks recursively (Q34). Projection refuses a deeper program
# expression, the request grammar names no target for a deeper request expression, and
# `project.same_bound` never folds a deeper declared bound. Every level costs a few Python frames,
# so this sits far below the interpreter's recursion limit while far above any chart program.
MAX_EXPR_DEPTH = 100


def expr_height(expr: Expr) -> int:
    """Levels in `expr`, counted without recursion: a flat 10,000-term sum is 10,000 levels."""
    deepest = 0
    stack: list[tuple[Expr, int]] = [(expr, 1)]
    while stack:
        node, level = stack.pop()
        deepest = max(deepest, level)
        if isinstance(node, Bin):
            stack += ((node.left, level + 1), (node.right, level + 1))
        elif isinstance(node, Neg):
            stack.append((node.operand, level + 1))
        elif isinstance(node, Fn):
            stack.append((node.arg, level + 1))
    return deepest


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
class Interval:
    """The user-stated x interval, with an inclusive stop and no promised sample count."""

    start: Expr
    stop: Expr


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
    # Presentation, and DATA-EFFECT-FREE by construction: none of the three can change a value in
    # the plotted table. They are carried rather than discarded because admission admits nothing it
    # cannot represent -- a projection that dropped them would be silently ignoring a statement.
    # `figsize` is exact `Fraction` for the same reason every other projected number is: the figure
    # size the program passes is the size it passes, and a float would round it.
    figsize: tuple[Fraction, Fraction] | None = None
    tick_rotation: Fraction | None = None
    tight_layout: bool = False


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
    # `None` is the column pair M13.4 admitted: x and y are read row for row. A reduction means
    # `x.groupby(<x>)[<y>].<group>()`, so the group KEY is the x channel and the REDUCED column is
    # the y channel, and one row of the plotted table is one group rather than one file row. No new
    # union member and no new total map: a reduction changes how the two named columns combine, not
    # what the spec is.
    group: Reduction | None = None


# The union M13.4 widened. Every total map over it needs its own exact-set pin: this repo has
# shipped a defect where a union grew and a total map over it stayed green.
type CorePlotSpec = FormulaPlot | DatasetPlot


@dataclass(frozen=True, slots=True)
class DatasetTarget:
    """The user's uploaded file, as BYTES -- never as a path the core would open.

    Carrying the content is what makes dataset recomputation possible at all: the core is pure and
    has no filesystem, so a bare path would name an artifact it could never read. `path` is
    compared byte-for-byte against the string literal the program passed to `read_csv`; the caller
    derives both fields from ONE authenticated upload, so the comparison is name-binding and the
    content is byte-binding, and neither substitutes for the other.
    """

    path: str
    content: bytes
    # The user's request text, when the caller has it: lexical anchoring (Q8) checks the program's
    # columns against the header names it states. `None` anchors nothing.
    request: str | None = None


@dataclass(frozen=True, slots=True)
class FormulaTarget:
    """An expression the USER stated, already parsed into the core's own tree.

    The core's request grammar builds this tree from the user's request sentence, independently of
    the model-authored program. `Interval` binds only the stated bounds; `Grid` also binds a stated
    sample count. A headless caller may omit the target, but that verdict claims only internal
    consistency and publishes the gap.
    """

    y: Expr
    grid: Grid | Interval | None = None


type DeclaredTarget = DatasetTarget | FormulaTarget
'''

_SOURCES["webui"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""webui — the Open WebUI integration harness.

Provisions and drives a headless Open WebUI over its REST API: it registers the verifier as an
OpenAPI tool server, bootstraps an admin, and launches OWUI under a canonical hermetic env so the
weak local model proposes chart specs the verifier certifies before render. NOT part of the
verifier trust claim: an out-of-tree harness like model_backend and bench -- type-checked under
mypy --strict but excluded from coverage and the wheel, importing only gate-venv deps (the
.venv-webui open-webui binary is exec'd, never imported).

settings.py owns the frozen config every other module imports; the REST client, bootstrap, model
stub, and CLI keep their wire/process boundaries separate.
"""
'''

_SOURCES["webui.paste_in"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The production paste-in: the source an admin pastes into an Open WebUI instance.

Every module here is written for TWO environments at once. In this repo it is ordinary first-party
code the gate lints, types and tests; in the target instance it arrives as a generated file per
paste target (`tools/generate_paste_in.py`), with `verifier.pysrc` embedded verbatim by the same
generator. A hand fork of either side is banned (`.agent/spec.md` § Decisions) -- the generator is
the single source, and `--check` is what keeps the committed artifact equal to it.

Dependency envelope: the stdlib, plus `open_webui`, which the image already carries. `bundle.py`'s
import scan decides that over the generated bytes rather than over intent, so a dependency added
here fails generation instead of failing a paste.
"""
'''

_SOURCES["webui.paste_in.owui_files"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The ONLY module that imports `open_webui`: the user's uploaded bytes, fetched in-process.

The truth source for every recomputed number is the user's own upload (`.claude/rules/pysrc.md`,
comparison class II), so the bytes come from Open WebUI's own store and not from the chat metadata,
which is client-supplied end to end -- the item's nested `path` included. Only the top-level `id`
is trusted, and it is re-resolved against the requesting user:
`Files.get_file_by_id_and_user_id` returns `None` for a file that is missing, foreign or
unreadable, so a file the caller does not own is never read and no second path exists that could
read it.

The `open_webui` imports are function-local, and that is load-bearing rather than stylistic: this
module must import in the gate environment, which has no `open_webui` and cannot have one, while
binding the real API inside the image. A test injects fakes into `sys.modules` and drives the same
call chain.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# Where Open WebUI's Pyodide worker writes each attached file before it runs the program. An
# admitted `read_csv` literal must name exactly this, and the core compares byte-for-byte.
UPLOAD_DIR = "/mnt/uploads/"


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """One attachment, named as the sandbox will name it, carrying the store's exact bytes."""

    file_id: str
    path: str
    content: bytes


def attachment_ids(metadata: Mapping[str, object] | None) -> list[str]:
    """Top-level ids from `__metadata__["files"]`, in chat order. Every other key is untrusted."""
    if metadata is None:
        return []
    items = metadata.get("files")
    if not isinstance(items, Sequence) or isinstance(items, str | bytes):
        return []
    ids: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        file_id = item.get("id")
        if isinstance(file_id, str) and file_id:
            ids.append(file_id)
    return ids


async def owned_files(file_ids: Sequence[str], user_id: str) -> tuple[UploadedFile, ...]:
    """Fetch only owned, readable ids through Open WebUI's store, preserving chat order."""
    from open_webui.models.files import Files  # noqa: PLC0415 - see the module docstring
    from open_webui.storage.provider import Storage  # noqa: PLC0415 - see the module docstring

    found: list[UploadedFile] = []
    for file_id in file_ids:
        record = await Files.get_file_by_id_and_user_id(file_id, user_id)
        if record is None:
            continue
        try:
            local_path = await asyncio.to_thread(Storage.get_file, record.path)
            content = await asyncio.to_thread(Path(local_path).read_bytes)
        except Exception:
            logging.getLogger(__name__).debug("Unreadable owned file omitted")
            continue
        found.append(
            UploadedFile(file_id=file_id, path=UPLOAD_DIR + record.filename, content=content)
        )
    return tuple(found)


async def uploaded_files(
    metadata: Mapping[str, object] | None,
    user_id: str,
) -> tuple[UploadedFile, ...]:
    """Resolve chat attachment ids through the same ownership path the filter uses."""
    return await owned_files(attachment_ids(metadata), user_id)
'''

_SOURCES["webui.paste_in.receipt"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""One backend-owned record of the last model-visible tool call.

The generated paste-ins embed this module in separate namespaces. A tagged built-in tuple crosses
their class-identity boundary; the reader validates its shape and accepts no other state value.
"""

from dataclasses import dataclass
from typing import Final

RECEIPT_ATTR: Final = "figure_verification_receipt"
RECEIPT_TAG: Final = "figure-verification-receipt/1"
_RECEIPT_LENGTH = 4


@dataclass(frozen=True, slots=True)
class Receipt:
    """Program and user-owned candidate ids, never a verdict or uploaded bytes."""

    program: str
    file_ids: tuple[str, ...]
    request_text: str | None


def write_receipt(request: object, receipt: Receipt) -> None:
    """Replace the prior call with a tagged, class-identity-independent value."""
    state = getattr(request, "state", None)
    if state is None:
        return
    setattr(
        state,
        RECEIPT_ATTR,
        (RECEIPT_TAG, receipt.program, receipt.file_ids, receipt.request_text),
    )


def read_receipt(request: object) -> Receipt | None:
    """Decode only the backend state's tagged, exactly typed carrier."""
    state = getattr(request, "state", None)
    value = getattr(state, RECEIPT_ATTR, None)
    if type(value) is not tuple or len(value) != _RECEIPT_LENGTH or value[0] != RECEIPT_TAG:
        return None
    _, program, file_ids, request_text = value
    if (
        type(program) is not str
        or type(file_ids) is not tuple
        or any(type(file_id) is not str for file_id in file_ids)
        or (request_text is not None and type(request_text) is not str)
    ):
        return None
    return Receipt(program, file_ids, request_text)
'''

_SOURCES["webui.paste_in.verdicts"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The closed string set the tool returns to the model.

Two members, fixed, and no refusal code among them. Five of the 54 closed codes carry the banned
stem `admit` (`call_target_not_admitted`, `keyword_not_admitted`, `statement_not_admitted`,
`attribute_not_admitted`, `assign_target_not_admitted`), so returning a code would teach admission
vocabulary through exactly the surface ruling 6 keeps clean. Nothing needs it either: the outlet
filter re-derives the verdict from the backend-recorded call, never from this reply.

These strings are MODEL-facing. The strings a USER reads are the filter's (`Intent`, ruling 4), and
no surface may depend on the model narrating a verdict (`.claude/rules/owui.md`).
"""

CHART_PRODUCED = "The chart is ready."
CHART_NOT_PRODUCED = "No chart was produced."

TOOL_VERDICTS = frozenset({CHART_PRODUCED, CHART_NOT_PRODUCED})
'''

_SOURCES["verifier.pysrc.admit"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Positive AST allowlist for `pysrc-0.1`. This IS the pass/fail boundary.

Admission is a closed allowlist over idiom CLASSES, never a denylist of bad constructs: a node type,
call target, attribute chain, keyword or literal kind that is not named here is refused, so a
construct nobody anticipated fails closed. Dispatch is exhaustive by node type with refusal as the
tail -- a `.get(kind, default_admit)` over a variant space is this repo's most-repeated defect
class, and here it would silently widen the boundary.

`plt.subplots` and every multi-panel form are absent BY CONSTRUCTION rather than by a named ban: the
projection targets exactly one chart, so a program producing more than one Axes has nothing to
project onto, and `call_target_not_admitted` is the honest reason.

Two deliberate non-admissions worth naming, because both are calibration levers rather than safety
properties, and M13.6 measurement is what should move them:

- a module docstring (a bare `str` expression statement) refuses, since it plots nothing;
- an empty program admits, since admission answers "may these bytes run", not "do they draw" --
  projection is what demands a chart.

This module parses; it never evaluates. No `eval`, `exec`, `compile` or `getattr` appears, and a
committed search test pins that.
"""

import ast
from dataclasses import dataclass, field
from typing import NoReturn, cast

from verifier.pysrc.errors import PysrcRefusalError, RefusalCode

# Module -> required alias. The alias is fixed, not merely required: admitting an arbitrary alias
# would make every downstream target string depend on model-chosen text.
ADMITTED_IMPORTS: dict[str, str] = {"matplotlib.pyplot": "plt", "numpy": "np", "pandas": "pd"}

# Closed call-target set, spelled `<alias>.<attr>`, grouped by the idiom class each serves.
_GRID_TARGETS = frozenset({"np.linspace", "np.arange"})
_MATH_TARGETS = frozenset({"np.sin", "np.cos", "np.tan", "np.exp", "np.log", "np.sqrt", "np.abs"})
_MARK_TARGETS = frozenset({"plt.plot", "plt.scatter", "plt.bar", "plt.barh"})
_DECOR_TARGETS = frozenset({"plt.title", "plt.xlabel", "plt.ylabel", "plt.legend", "plt.grid"})
# Presentation calls, admitted because the measured proposer writes them in 16 of 25 simple prompts
# and none of them can change a plotted value. `plt.figure` is the exception that proves the class:
# a SECOND one starts a new figure and would orphan whatever was already drawn, so projection binds
# it to a position (`figure_orphans_mark`) rather than treating it as free.
_PRESENTATION_TARGETS = frozenset({"plt.figure", "plt.tight_layout", "plt.xticks"})
_TERMINAL_TARGETS = frozenset({"plt.show"})
# Exactly one reader. `read_table`, `read_excel` and friends stay out: each would need its own
# projection rule for separators, sheets and header handling before the verifier could state what
# the program reads.
_SOURCE_TARGETS = frozenset({"pd.read_csv"})
ADMITTED_CALL_TARGETS = (
    _GRID_TARGETS
    | _MATH_TARGETS
    | _MARK_TARGETS
    | _DECOR_TARGETS
    | _PRESENTATION_TARGETS
    | _TERMINAL_TARGETS
    | _SOURCE_TARGETS
)

# Keywords are closed PER TARGET: a keyword admitted on one call is not thereby admitted on
# another, because each one has to be projectable where it appears.
ADMITTED_KEYWORDS: dict[str, frozenset[str]] = {
    "np.linspace": frozenset({"num"}),
    "np.arange": frozenset(),
    "np.sin": frozenset(),
    "np.cos": frozenset(),
    "np.tan": frozenset(),
    "np.exp": frozenset(),
    "np.log": frozenset(),
    "np.sqrt": frozenset(),
    "np.abs": frozenset(),
    # Style keywords are closed PER TARGET to match matplotlib's own signature: `plot` takes a
    # linestyle, `bar` does not, and admitting one set for every mark would admit calls that would
    # raise when executed. Each carries a string literal and therefore no data. `c=` and `cmap=`
    # stay out: they are the colour-by-category channel, which encodes a column the projection
    # does not state. `s=` stays out: it is G6's area-encoding channel. `alpha=` and
    # `edgecolors=` stay out because nothing measured asks for them.
    "plt.plot": frozenset({"label", "color", "marker", "linestyle"}),
    "plt.scatter": frozenset({"label", "color", "marker"}),
    "plt.bar": frozenset({"label", "color"}),
    "plt.barh": frozenset({"label", "color"}),
    "plt.figure": frozenset({"figsize"}),
    "plt.tight_layout": frozenset(),
    "plt.xticks": frozenset({"rotation"}),
    "plt.title": frozenset(),
    "plt.xlabel": frozenset(),
    "plt.ylabel": frozenset(),
    "plt.legend": frozenset(),
    "plt.grid": frozenset(),
    "plt.show": frozenset(),
    # No `sep`, `header`, `usecols`, `dtype`: each changes what the file MEANS, so admitting one
    # without a projection rule would let the program restate the user's artifact unchecked.
    "pd.read_csv": frozenset(),
}

# Attribute reads that are values rather than call targets.
ADMITTED_CONSTANT_ATTRS = frozenset({"np.pi", "np.e"})
# `<bound name>.index` and `<bound name>.values` -- ONE idiom class, because admission has no types
# and cannot tell an aggregate from a frame. PROJECTION decides: an aggregate's index is its group
# key, while `df.values` is the whole frame as an array and refuses `column_not_from_source` there.
ADMITTED_VALUE_ATTRS = frozenset({"index", "values"})

# `(target, keyword) -> element count`. A tuple display is refused everywhere else by the expression
# tail, so this is the ONLY door a tuple enters the language by, and it is keyed per keyword rather
# than opened globally: `figsize` is the one admitted tuple.
ADMITTED_TUPLE_KEYWORDS: dict[tuple[str, str], int] = {("plt.figure", "figsize"): 2}
# Targets admitting NO positional argument, all refused here with ONE code (user ruling Q26).
# `plt.figure(1)` selects a figure by number, a figure-lifecycle effect the spec does not
# represent; `plt.xticks(ticks)` sets tick locations or labels, restating what the x axis says
# about the data; `plt.tight_layout` takes no argument the spec carries.
_NO_POSITIONAL_TARGETS = frozenset({"plt.figure", "plt.tight_layout", "plt.xticks"})

# The `groupby` idiom, admitted as ONE atomic shape rather than link by link. `_dotted` bounds an
# attribute chain to depth 1 against an `ast.Name`, so the outer `.sum` of a chain -- whose receiver
# is a `Subscript` -- would refuse before the shape could be read at all.
_GROUPBY = "groupby"
_REDUCTIONS = frozenset({"sum", "mean", "min", "max"})

# The pandas plotting ACCESSOR, `<data>.plot(kind="bar"|"line")`, written by 4 of the 25 simple
# `m13-design` captures (bar) and 5 of the 24 simple `m10-design` captures (line). It is its own
# route rather than a dotted target: its receiver is a name the MODEL bound,
# so admitting it through `ADMITTED_CALL_TARGETS` -- which is keyed by a FIXED import alias -- would
# open every `<name>.plot` at once.
_ACCESSOR_ATTR = "plot"
# `kind` is TARGET IDENTITY, not a style keyword: each value names the mark the accessor draws, and
# it maps onto that mark's own target string here so projection never defaults an unlisted spelling
# onto a line the program does not draw.
ADMITTED_ACCESSOR_KINDS: dict[str, str] = {"bar": "plt.bar", "barh": "plt.barh", "line": "plt.plot"}
# Closed exactly as `ADMITTED_KEYWORDS` is per target. `x=`/`y=` stay out: they select columns, and
# the accessor's projection reads its channels from the receiver instead.
ADMITTED_ACCESSOR_KEYWORDS = frozenset({"kind", "color"})
# Trailing calls projection UNWRAPS off an admitted chain, BY NAME. `_admit_aggregation` admits ONE
# trailing no-argument call, so `.sort_values()` arrives ALREADY ADMITTED and is refused only at
# projection; an unwrap taking whatever trailing call it finds would admit a REORDERING with nothing
# red, and both G8's row coverage and G9's ordering read off group-key order.
ADMITTED_UNWRAPPED_ATTRS = frozenset({"reset_index"})
# A fixed import alias is never an accessor receiver: `plt.plot` is a mark target and `pd.plot` /
# `np.plot` are no target at all, so all three keep resolving through `ADMITTED_CALL_TARGETS`.
_IMPORT_ALIASES = frozenset(ADMITTED_IMPORTS.values())

_ADMITTED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
_ADMITTED_UNARYOPS = (ast.USub,)

# `bool` is admitted because `plt.grid(True)` is an ordinary matplotlib idiom; which argument slots
# accept which literal kind is projection's question, not admission's.
#
# The membership test is EXACT type, not `isinstance`, so that this tuple is the whole boundary
# rather than a subclass-closed one: `bool` subclasses `int`, so under `isinstance` removing `bool`
# here would not actually refuse `True`. The two spellings agree on every input today and diverge
# the moment the set is narrowed, which is exactly when the difference has to hold.
_ADMITTED_LITERAL_TYPES = (int, float, str, bool)


@dataclass(slots=True)
class _Scope:
    """Names bound so far. Order matters: a name is admitted only after its binding statement."""

    bound: set[str] = field(default_factory=set)


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


def _dotted(node: ast.Attribute) -> tuple[str, str]:
    """Return `(alias, "alias.attr")` for a depth-1 chain, refusing anything deeper.

    Depth is bounded here rather than at the leaf: `np.random.rand` must refuse because its chain is
    two deep, not because `rand` happens to be unlisted -- otherwise adding one name to the
    allowlist could accidentally admit a whole submodule.
    """
    value = node.value
    if not isinstance(value, ast.Name):
        _refuse("attribute_not_admitted")
    if node.attr.startswith("_"):
        _refuse("attribute_not_admitted")
    return value.id, f"{value.id}.{node.attr}"


def _admit_constant_attr(node: ast.Attribute, scope: _Scope) -> None:
    """Admit a bare attribute READ, as opposed to a call target."""
    alias, dotted = _dotted(node)
    if node.attr not in ADMITTED_VALUE_ATTRS and dotted not in ADMITTED_CONSTANT_ATTRS:
        _refuse("attribute_not_admitted")
    if alias not in scope.bound:
        _refuse("name_not_bound")


def _groupby_root(node: ast.expr) -> tuple[ast.Call, ast.Name] | None:
    """The innermost `<name>.groupby(...)` call an expression is rooted in, with that name.

    Recognizing the aggregation family by its ROOT is what makes the chain admissible atomically.
    A chain rooted in anything else -- `np.random.rand`, whose spine ends at an alias attribute --
    returns `None` and keeps the depth-1 bound that refuses it.
    """
    current = node
    while True:
        if isinstance(current, ast.Call):
            func = current.func
            if not isinstance(func, ast.Attribute):
                return None
            if func.attr == _GROUPBY and isinstance(func.value, ast.Name):
                return current, func.value
            current = func.value
        elif isinstance(current, (ast.Attribute, ast.Subscript)):
            current = current.value
        else:
            return None


@dataclass(frozen=True, slots=True)
class AggregationChain:
    """The canonical `<frame>.groupby("<key>")["<column>"].<reduction>()`, read structurally."""

    frame: str
    key: str
    column: str
    reduction: str


def aggregation_chain(node: ast.expr) -> AggregationChain | None:
    """Read the canonical chain, or `None` for every other shape.

    The spine is written down ONCE, here beside the admission that closes it, and projection reads
    it back instead of restating it: two matchers over one shape drift apart silently, and only one
    of them would be the boundary.
    """
    match node:
        case ast.Call(
            func=ast.Attribute(
                value=ast.Subscript(
                    value=ast.Call(
                        func=ast.Attribute(value=ast.Name(id=frame), attr=str() as grouper),
                        args=[ast.Constant(value=str() as key)],
                        keywords=[],
                    ),
                    slice=ast.Constant(value=str() as column),
                ),
                attr=str() as reduction,
            ),
            args=[],
            keywords=[],
        ) if grouper == _GROUPBY and reduction in _REDUCTIONS:
            return AggregationChain(frame=frame, key=key, column=column, reduction=reduction)
        case _:
            return None


def accessor_receiver(node: ast.Call) -> ast.Name | None:
    """The bound NAME an accessor call draws from, or `None` for every other call shape.

    The shape is written down ONCE, here beside the admission that closes it, and projection reads
    it back instead of restating it: two matchers over one shape drift apart silently, and only one
    of them would be the boundary.

    Shape alone, refusing nothing. `<name>.plot(...)` and `<name>["<col>"].plot(...)` both return
    the ROOT name, because both are receivers the checks below have to price; deciding `kind` or
    the keywords here would land `call_target_not_admitted` on a program whose fault is positional.
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != _ACCESSOR_ATTR:
        return None
    root = func.value
    if isinstance(root, ast.Subscript):
        root = root.value
    if not isinstance(root, ast.Name) or root.id in _IMPORT_ALIASES:
        return None
    return root


def accessor_is_subscripted(node: ast.Call) -> bool:
    """Whether an accessor call's receiver carries a column subscript.

    Split from `accessor_receiver` rather than folded into its return, because the two stages price
    different things about one subscript: admission prices its SLICE, projection prices its EFFECT,
    and the ROOT name is what both have to reach first. Callable only where `accessor_receiver`
    returned a name, which is what makes the cast a postcondition rather than a hope.
    """
    func = cast("ast.Attribute", node.func)
    return isinstance(func.value, ast.Subscript)


def accessor_kind(node: ast.Call) -> str | None:
    """The accessor's `kind=` string literal, or `None` when it is absent or not a string."""
    for keyword in node.keywords:
        if keyword.arg == "kind":
            value = keyword.value
            if isinstance(value, ast.Constant) and type(value.value) is str:
                return value.value
            return None
    return None


def _admit_accessor(node: ast.Call, receiver: ast.Name, scope: _Scope) -> None:
    """`<data>.plot(kind="<mark>")`, closed on its own shape.

    Refusal order is the contract's: the keyword allowlist prices the call's SHAPE, `kind` then
    prices its TARGET, and the receiver's binding is checked last -- the same target-before-bound
    order `_admit_call` keeps, so the two routes tell an author the same thing about one program.
    """
    if node.args:
        # The accessor's positional slot is `x`, which selects a column the projection reads from
        # the receiver instead. Two channel sources for one mark is not a shape it can state.
        _refuse("keyword_not_admitted")
    for keyword in node.keywords:
        # `arg is None` is `**kwargs`, whose keyword set is not statically known at all.
        if keyword.arg is None or keyword.arg not in ADMITTED_ACCESSOR_KEYWORDS:
            _refuse("keyword_not_admitted")
    if accessor_kind(node) not in ADMITTED_ACCESSOR_KINDS:
        # Unlisted, non-literal and ABSENT all land here: `kind` is the target, so a call whose
        # target cannot be read names no admitted target at all. Absent defaults to a line in
        # pandas, and defaulting is what a closed map exists to refuse.
        _refuse("call_target_not_admitted")
    if receiver.id not in scope.bound:
        _refuse("name_not_bound")
    # `accessor_receiver` reached `receiver` by walking `node.func`, so an `ast.Attribute` here is
    # its postcondition rather than a hope.
    func = cast("ast.Attribute", node.func)
    if isinstance(func.value, ast.Subscript):
        _admit_string_index(func.value.slice)
    for keyword in node.keywords:
        _admit_expr(keyword.value, scope)


def _admit_string_index(node: ast.expr) -> None:
    """A string-literal column name. A tuple selection (`[["a", "b"]]`) lands here and refuses."""
    if not isinstance(node, ast.Constant) or type(node.value) is not str:
        _refuse("column_not_literal")


def _admit_reduction_chain(node: ast.Call, root: ast.Call) -> None:
    """The two links above the root: `["<col>"]`, then `.<reduction>()` with no argument."""
    if node.args or node.keywords:
        # A reduction carrying `axis=` or a positional computes something else entirely.
        _refuse("keyword_not_admitted")
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in _REDUCTIONS:
        _refuse("attribute_not_admitted")
    selection = func.value
    if not isinstance(selection, ast.Subscript) or selection.value is not root:
        _refuse("attribute_not_admitted")
    _admit_string_index(selection.slice)


def _admit_aggregation(node: ast.Call, root: ast.Call, frame: ast.Name, scope: _Scope) -> None:
    """Admit the `groupby` idiom as one closed shape. Three spellings pass.

    The bare `<frame>.groupby("<key>")`, the canonical
    `<frame>.groupby("<key>")["<col>"].<reduction>()`, and that chain carrying ONE trailing no-
    argument call. The trailing call is admitted as a CLASS and unwrapped by name: projection reads
    `ADMITTED_UNWRAPPED_ATTRS` and refuses every other spelling, `.sort_values()` included, so
    `aggregation_not_projected` names an unstatable meaning where `attribute_not_admitted` would
    blame the attribute. The bare `groupby` admits for the same reason and reduces nothing.
    """
    if frame.id not in scope.bound:
        _refuse("name_not_bound")
    if len(root.args) != 1 or root.keywords:
        _refuse("column_not_literal")
    _admit_string_index(root.args[0])
    if node is root:
        return
    # `_groupby_root` reached `root` by walking `node.func`, so an `ast.Attribute` here is its
    # postcondition rather than a hope. Casting instead of re-testing keeps the branch out of the
    # module: an arm no input can take is one the coverage gate cannot price.
    func = cast("ast.Attribute", node.func)
    reduction = node
    receiver = func.value
    if isinstance(receiver, ast.Call) and receiver is not root:
        if func.attr.startswith("_") or node.args or node.keywords:
            _refuse("attribute_not_admitted")
        reduction = receiver
    _admit_reduction_chain(reduction, root)


def _admit_call_or_aggregation(node: ast.Call, scope: _Scope) -> None:
    """Route one call: two idioms close on their own shape, everything else by target."""
    receiver = accessor_receiver(node)
    if receiver is not None:
        _admit_accessor(node, receiver, scope)
        return
    rooted = _groupby_root(node)
    if rooted is None:
        _admit_call(node, scope)
        return
    root, frame = rooted
    _admit_aggregation(node, root, frame, scope)


def _admit_number_tuple(node: ast.expr, arity: int) -> None:
    """A fixed-arity tuple of NUMERIC literals, admitted in one keyword slot and nowhere else."""
    if not isinstance(node, ast.Tuple) or len(node.elts) != arity:
        _refuse("literal_not_admitted")
    for element in node.elts:
        # Exact type: `bool` subclasses `int`, and `figsize=(True, 6)` is not a figure size.
        if not isinstance(element, ast.Constant) or type(element.value) not in (int, float):
            _refuse("literal_not_admitted")


def _admit_call(node: ast.Call, scope: _Scope) -> None:
    func = node.func
    if not isinstance(func, ast.Attribute):
        _refuse("call_target_not_admitted")
    alias, target = _dotted(func)
    if target not in ADMITTED_CALL_TARGETS:
        _refuse("call_target_not_admitted")
    if alias not in scope.bound:
        _refuse("name_not_bound")
    admitted = ADMITTED_KEYWORDS[target]
    for keyword in node.keywords:
        # `arg is None` is `**kwargs`, whose keyword set is not statically known at all.
        if keyword.arg is None or keyword.arg not in admitted:
            _refuse("keyword_not_admitted")
        arity = ADMITTED_TUPLE_KEYWORDS.get((target, keyword.arg))
        if arity is None:
            _admit_expr(keyword.value, scope)
        else:
            _admit_number_tuple(keyword.value, arity)
    if node.args and target in _NO_POSITIONAL_TARGETS:
        _refuse("keyword_not_admitted")
    for arg in node.args:
        # `*args` arrives as `ast.Starred`, which the expression tail refuses.
        _admit_expr(arg, scope)


def _admit_expr(node: ast.expr, scope: _Scope) -> None:
    if isinstance(node, ast.Constant):
        if type(node.value) not in _ADMITTED_LITERAL_TYPES:
            _refuse("literal_not_admitted")
    elif isinstance(node, ast.Name):
        if node.id not in scope.bound:
            _refuse("name_not_bound")
    elif isinstance(node, ast.Attribute):
        _admit_constant_attr(node, scope)
    elif isinstance(node, ast.Call):
        _admit_call_or_aggregation(node, scope)
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ADMITTED_BINOPS):
            _refuse("operator_not_admitted")
        _admit_expr(node.left, scope)
        _admit_expr(node.right, scope)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ADMITTED_UNARYOPS):
            _refuse("operator_not_admitted")
        _admit_expr(node.operand, scope)
    elif isinstance(node, ast.Subscript):
        _admit_column(node, scope)
    else:
        # The closed tail: comprehensions, lambdas, f-strings, list/dict/set/tuple displays,
        # starred args, walrus, comparisons, boolean and conditional expressions.
        _refuse("expression_not_admitted")


def _admit_column(node: ast.Subscript, scope: _Scope) -> None:
    """`<bound name>["<literal>"]` and nothing else.

    Narrower than it looks by accident: a slice, a tuple index, `df[cols]` and `df.loc[...]` all
    land on a refusal, because each selects something the projection has no rule for. `.loc`/`.iloc`
    additionally fail at the attribute check, which is the near-miss this shape has to survive.
    """
    if not isinstance(node.value, ast.Name):
        _refuse("expression_not_admitted")
    if node.value.id not in scope.bound:
        _refuse("name_not_bound")
    index = node.slice
    if not isinstance(index, ast.Constant) or type(index.value) is not str:
        _refuse("column_not_literal")


def _admit_import(node: ast.Import, scope: _Scope) -> None:
    for alias in node.names:
        required = ADMITTED_IMPORTS.get(alias.name)
        if required is None or alias.asname != required:
            _refuse("import_not_admitted")
        scope.bound.add(required)


def _admit_assign(node: ast.Assign, scope: _Scope) -> None:
    if len(node.targets) != 1:
        _refuse("assign_target_not_admitted")
    target = node.targets[0]
    if not isinstance(target, ast.Name):
        _refuse("assign_target_not_admitted")
    if target.id.startswith("_"):
        _refuse("assign_target_not_admitted")
    # Right-hand side first, then bind: `x = x + 1` must refuse while `x` is still unbound.
    _admit_expr(node.value, scope)
    scope.bound.add(target.id)


def _admit_stmt(node: ast.stmt, scope: _Scope) -> None:
    if isinstance(node, ast.Import):
        _admit_import(node, scope)
    elif isinstance(node, ast.Assign):
        _admit_assign(node, scope)
    elif isinstance(node, ast.Expr):
        # A bare expression statement is admitted only as a call: a lone name, literal or docstring
        # has no plotting effect, and admitting one would carry statements the projection ignores.
        value = node.value
        if not isinstance(value, ast.Call):
            _refuse("statement_not_admitted")
        _admit_call_or_aggregation(value, scope)
    else:
        # The closed tail: loops, `def`, `class`, `try`, `with`, `del`, `global`, `nonlocal`,
        # `raise`, `assert`, `async`, `from x import y`, annotated and augmented assignment.
        _refuse("statement_not_admitted")


def parse_admitted(text: str) -> ast.Module:
    """Parse and admit `text`, returning the tree. Raises `PysrcRefusalError` on refusal.

    `text` must be what `prescan` returned: the caps it charges are what bound this parse.
    """
    try:
        tree = ast.parse(text)
    # The pre-scan tokenizes but does not parse, so a tokenizable-yet-unparsable program reaches
    # here and must become a verdict rather than a traceback.
    except SyntaxError as exc:
        _refuse("source_not_parsable", exc)

    scope = _Scope()
    for statement in tree.body:
        _admit_stmt(statement, scope)
    return tree
'''

_SOURCES["verifier.pysrc.limits"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Resource ceilings for the portable core.

Every value is a policy bound on UNTRUSTED input, so each is validated fail-closed before use: a
caller that passes a non-positive cap gets `PysrcCallerError`, never a silently disabled check.
"""

from dataclasses import dataclass, fields

from verifier.pysrc.errors import PysrcCallerError


@dataclass(frozen=True, kw_only=True, slots=True)
class PysrcLimits:
    """Ceilings applied before `ast.parse` sees the source.

    Defaults are sized against observed model-authored plotting programs (completion lengths of
    148-470 tokens, `archive/contracts/m12u7.md`), with headroom, not against what the parser can
    survive -- an admitted program is a short chart script or it is not admitted.
    """

    max_source_bytes: int = 20_000
    max_tokens: int = 4_000
    # A title string full of parentheses does not reach this: depth is counted from OP tokens only.
    max_bracket_depth: int = 16
    max_indent_depth: int = 4
    max_line_bytes: int = 400
    # Projection-stage ceiling, not a parse ceiling: a grid is what recomputation must evaluate
    # point by point, so the bound matches the shipped `FormulaDomain.samples` cap rather than
    # anything the parser cares about. Two points is the floor -- one point is not a curve.
    min_grid_samples: int = 2
    max_grid_samples: int = 100_000
    # Recomputation ceilings. Every one bounds work the verifier does on UNTRUSTED bytes, and each
    # is checked BEFORE the work it bounds -- a row cap read after materializing the rows buys
    # nothing. Sized for a chat attachment, not for a data warehouse.
    max_csv_bytes: int = 8_000_000
    max_csv_rows: int = 100_000
    max_csv_columns: int = 128
    max_csv_cell_bytes: int = 512
    max_table_rows: int = 100_000
    max_expr_nodes: int = 1_000
    # Groups are PLOTTED MARKS, so this is a legibility ceiling before it is a cost one: a chart
    # with a thousand bars is already unreadable, and the reduction charges work per group anyway.
    # It binds ahead of the reduction rather than after, so a high-cardinality key column refuses
    # before its groups are materialized.
    max_groups: int = 1_000
    # The binding ceiling in practice: the other caps multiply out to far more evaluation than a
    # demo may spend, so this is what refuses a program that is admissible but not affordable.
    # Measured, not guessed: `tools/bench_pysrc_work.py` on a quiet host of record put the binding
    # rate at 398,458 work/s -- the slowest of both arms, at cell width 31, where `len // 32`
    # surcharges nothing yet the bytes are still read. One second of recomputation, two significant
    # figures. Work binds before `max_table_rows` on purpose: it is size-aware and the row cap is
    # not, so a wide-celled file must refuse on what it actually costs.
    max_work: int = 390_000


DEFAULT_LIMITS = PysrcLimits()


def validate_limits(limits: PysrcLimits) -> None:
    """Refuse a configuration that would disable a ceiling. Raises `PysrcCallerError`."""
    for spec in fields(limits):
        value: int = getattr(limits, spec.name)
        if value < 1:
            message = f"limit {spec.name} must be >= 1"
            raise PysrcCallerError(message)
'''

_SOURCES["verifier.pysrc.numeric"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Binary64 evaluation of a projected expression, and materialization of a projected grid.

Written for this job rather than ported from `verifier.expr`. `expr.py` is exact over `Fraction`
and rounds once at the end; the executed program is numpy float64 and rounds at EVERY operator, so
an exact engine computes a number the program never computes. The more precise engine is the less
faithful one, and faithfulness is the whole claim.

Every node rounds to binary64 before its parent reads it. No exact intermediate exists, and a
`Fraction` literal converts through `float()` so a source `0.1` becomes the float64 `0.1` the
program passes to numpy -- not a rounded `1/10`.

Domain and overflow faults are never raised out of here. They reproduce numpy's IEEE values, so
`x/0` is `+-inf` and `log(0)` is `-inf`, and a single downstream refusal rejects any non-finite
that reaches the table. `pow` is the one operator where reproducing numpy takes real logic; see
`_pow`.
"""

import math
from fractions import Fraction
from typing import Literal, assert_never, cast

from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.spec import Bin, BinOp, Const, ConstName, Expr, Fn, FnName, Grid, Neg, Num, Var

__all__ = ["NUMERIC_PROFILE", "OPERATOR_CLASSES", "evaluate_expr", "materialize_grid"]

# Published in every certificate. The name is load-bearing: the LEGACY JSON formula mode runs
# `rational-half-even-v1` and is exact, and `examples/index.json` ships a sentence about that
# exactness. A reader must never carry one mode's guarantee onto the other, so the profiles are
# separately named and the certificate prints this one verbatim.
NUMERIC_PROFILE = "binary64-libm-v1"
OPERATOR_CLASSES: dict[str, frozenset[str]] = {
    "standard-exact": frozenset(
        {
            "add",
            "sub",
            "mul",
            "div",
            "neg",
            "abs",
            "sqrt",
            "literal",
            "pi",
            "e",
            "linspace",
            "arange",
        }
    ),
    "libm-dependent": frozenset({"sin", "cos", "tan", "exp", "log", "pow"}),
}

_NEGATIVE_NAN = -math.nan


def _fraction_float(value: Fraction) -> float:
    try:
        return float(value)
    except OverflowError:
        return -math.inf if value.numerator < 0 else math.inf


def _divide(left: float, right: float) -> float:
    try:
        return left / right
    except ZeroDivisionError:
        if math.isnan(left):
            return left
        if left == 0.0:
            return _NEGATIVE_NAN
        sign = math.copysign(1.0, left) * math.copysign(1.0, right)
        return math.copysign(math.inf, sign)


def _odd_integer(value: float) -> bool:
    return math.isfinite(value) and value.is_integer() and math.fmod(abs(value), 2.0) == 1.0


def _pow(base: float, exponent: float) -> float:
    """`math.pow` with its exceptions mapped to C99 / numpy values.

    `ValueError` is ambiguous: it covers zero-base poles and negative-base domains, which numpy
    maps to infinities and NaNs respectively. The operands, including negative zero's sign bit,
    decide which result the executed program receives.
    """
    try:
        return math.pow(base, exponent)
    except OverflowError:
        negative = base < 0.0 and _odd_integer(exponent)
        return -math.inf if negative else math.inf
    except ValueError:
        if base == 0.0:
            negative = math.copysign(1.0, base) < 0.0 and _odd_integer(exponent)
            return -math.inf if negative else math.inf
        return math.copysign(math.nan, base)


def _trig(name: Literal["sin", "cos", "tan"], value: float) -> float:
    try:
        if name == "sin":
            return math.sin(value)
        if name == "cos":
            return math.cos(value)
        if name == "tan":
            return math.tan(value)
        raise AssertionError(name)  # pragma: no cover - the literal type is closed
    except ValueError:
        return _NEGATIVE_NAN


def _exp(value: float) -> float:
    try:
        return math.exp(value)
    except OverflowError:
        return math.inf


def _log(value: float) -> float:
    try:
        return math.log(value)
    except ValueError:
        return -math.inf if value == 0.0 else math.nan


def _sqrt(value: float) -> float:
    try:
        return math.sqrt(value)
    except ValueError:
        return math.copysign(math.nan, value)


def _function(name: FnName, value: float) -> float:
    match name:
        case "sin" | "cos" | "tan":
            return _trig(name, value)
        case "abs":
            return abs(value)
        case "exp":
            return _exp(value)
        case "log":
            return _log(value)
        case "sqrt":
            return _sqrt(value)
        case _ as unreachable:  # pragma: no cover - `FnName` is closed
            assert_never(unreachable)


def _binary(operator: BinOp, left: float, right: float) -> float:
    if operator == "add":
        return left + right
    if operator == "sub":
        return left - right
    if operator == "mul":
        return left * right
    if operator == "div":
        return _divide(left, right)
    if operator == "pow":
        return _pow(left, right)
    assert_never(operator)  # pragma: no cover - `BinOp` is closed


type _CompoundExpr = Neg | Fn | Bin


def _constant(name: ConstName) -> float:
    if name == "pi":
        return math.pi
    if name == "e":
        return math.e
    assert_never(name)  # pragma: no cover - `ConstName` is closed


def _start_node(
    node: Expr,
    x: float,
    pending: list[tuple[Expr, bool]],
    values: list[float],
) -> None:
    if isinstance(node, Num):
        values.append(_fraction_float(node.value))
    elif isinstance(node, Var):
        values.append(x)
    elif isinstance(node, Const):
        values.append(_constant(node.name))
    elif isinstance(node, Neg):
        pending.extend(((node, True), (node.operand, False)))
    elif isinstance(node, Fn):
        pending.extend(((node, True), (node.arg, False)))
    elif isinstance(node, Bin):
        pending.extend(((node, True), (node.right, False), (node.left, False)))
    else:  # pragma: no cover - `Expr` is a closed union
        assert_never(node)


def _finish_node(node: _CompoundExpr, values: list[float]) -> None:
    if isinstance(node, Neg):
        values.append(-values.pop())
    elif isinstance(node, Fn):
        values.append(_function(node.name, values.pop()))
    elif isinstance(node, Bin):
        right = values.pop()
        left = values.pop()
        values.append(_binary(node.op, left, right))
    else:  # pragma: no cover - `_CompoundExpr` is a closed union
        assert_never(node)


def _evaluate_expr(
    expr: Expr,
    x: float,
    budget: WorkBudget,
    *,
    charge_nodes: bool,
) -> float:
    pending: list[tuple[Expr, bool]] = [(expr, False)]
    values: list[float] = []
    while pending:
        node, ready = pending.pop()
        if ready:
            _finish_node(cast("_CompoundExpr", node), values)
        else:
            if charge_nodes:
                budget.charge(1)
            _start_node(node, x, pending, values)
    return values[0]


def evaluate_expr(expr: Expr, x: float, budget: WorkBudget) -> float:
    """Evaluate `expr` at `x`, rounding per node and charging each node once."""
    return _evaluate_expr(expr, x, budget, charge_nodes=True)


def materialize_grid(grid: Grid, budget: WorkBudget) -> tuple[float, ...]:
    """Materialize the normalized grid without expression-node charges.

    `Grid.stop` is inclusive for both constructors -- projection already normalized `arange`'s
    excluded bound onto the inclusive triple, and `arange` bounds are integers only (M13.3).
    """
    start = _evaluate_expr(grid.start, 0.0, budget, charge_nodes=False)
    stop = _evaluate_expr(grid.stop, 0.0, budget, charge_nodes=False)
    count = grid.samples
    delta = stop - start
    divisor = count - 1
    step = delta / divisor
    if step == 0.0:
        values = tuple((float(index) / divisor) * delta + start for index in range(count))
    else:
        values = tuple(float(index) * step + start for index in range(count))
    return (*values[:-1], stop)
'''

_SOURCES["verifier.pysrc.table"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The plotted table -- recomputation's static product, and the thing the certificate binds.

The model supplies a program, never values, so no CLAIMED number exists to contradict statically.
What recomputation produces instead is this table: the x and y the verifier says the figure shows.
Whether the EMITTED artifact really shows them is not settled here and is not implied; the
certificate declares that gap open, and M10's observation is what closes it.
"""

from dataclasses import dataclass

from verifier.pysrc.errors import PysrcCallerError

__all__ = ["CellValue", "PlottedTable"]

# A categorical x is a string; every other cell is float64. There is no null and no NaN: the CSV
# profile refuses every NA spelling before a cell reaches here, which is what makes G8 hold.
type CellValue = float | str

_DOMAIN = b"pysrc-table-0.1\n"
_LENGTH_BYTES = 8


def _payload(value: CellValue) -> tuple[bytes, bytes]:
    if isinstance(value, str):
        return b"s", value.encode("utf-8")
    return b"f", value.hex().encode("ascii")


def _field(value: CellValue) -> bytes:
    kind, payload = _payload(value)
    return kind + len(payload).to_bytes(_LENGTH_BYTES, "big") + payload


@dataclass(frozen=True, slots=True)
class PlottedTable:
    """One series: x against y, in the order the figure draws them.

    Row order is the order the SOURCE itself defines: file order for a column pair, grid order in
    the formula arm, sorted key order for an aggregate -- pandas' `sort=True` default, which the
    executed program would draw. The legacy JSON mode's total sort is deliberately not reused over
    a column pair: sorting there would silently redraw a figure whose point order is part of what
    the user submitted.
    """

    x: tuple[CellValue, ...]
    y: tuple[float, ...]

    def __post_init__(self) -> None:
        """Unequal lengths are a CALLER fault, not a verdict about the source."""
        if len(self.x) != len(self.y):
            message = (
                f"plotted table length mismatch: {len(self.x)} x values, {len(self.y)} y values"
            )
            raise PysrcCallerError(message)

    def canonical_bytes(self) -> bytes:
        """One byte encoding per table value, locale-free and `repr`-free.

        Floats as `%a` hex, so a 1-ulp difference in any cell changes the bytes; string cells as
        UTF-8 behind a length prefix, so no cell's text can imitate a delimiter. Two structurally
        equal tables built by different code paths must produce identical bytes.
        """
        encoded = bytearray(_DOMAIN)
        encoded.extend(len(self.x).to_bytes(_LENGTH_BYTES, "big"))
        for x, y in zip(self.x, self.y, strict=True):
            encoded.extend(_field(x))
            encoded.extend(_field(y))
        return bytes(encoded)
'''

_SOURCES["verifier.pysrc.aggregate"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Grouped reduction, reproducing what the EXECUTED program plots.

pandas is not importable here and never will be: the core is stdlib-only so M14 can inline it. So
this module reimplements the reductions pandas performs, and every choice below is fixed by
MEASUREMENT against pandas rather than by what is arithmetically nicest -- the more precise engine
is the less faithful one, exactly as in `expr.py`'s ruling.

The four decisions that carry the module, all measured:

- a float64 `sum` is ORDERED binary64 Kahan compensation in file-row order. Naive left-to-right
  differs on 2,761 of 4,000 admitted-profile CSV groups, `math.fsum` on 1,483; Kahan matches on
  0 of 16,062.
- an int64 `mean` casts each value to float64 BEFORE summing, so it is NOT the exact integer mean:
  `[2**53, 1, 0]` splits the two orders by 1 ulp.
- `min` and `max` update on STRICT `<` and `>`, so a tie keeps the FIRST value's bits.
- group key order IS the plotted x-order, and it is pandas' `sort=True` default: ascending, by
  Unicode code point for text keys, measured identical under `C`, `C.utf8` and `en_US.utf8` while
  an `en_US` collation control orders differently.

Host versus both target Pyodide builds: 0 differences over 96,372 reduction rows. Unlike the libm
functions the reduction carries NO measured ulp band, so a disagreement here is a defect rather than
an environment gap.
"""

from dataclasses import dataclass
from typing import Literal, NoReturn, assert_never

from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.spec import Reduction
from verifier.pysrc.table import CellValue

__all__ = ["Aggregated", "ColumnDtype", "aggregate_series", "column_dtype"]

# The dtype `pd.read_csv` infers for a column inside the admitted cell profile. There is no third
# member: the profile refuses every NA spelling, every boolean text and every non-fixed-point token
# before a cell reaches here, so a selected value column is one of these two.
type ColumnDtype = Literal["int64", "float64"]

# `mean` is the one reduction that does not retain an integer dtype: pandas produces float64 for it,
# which is also why the renderer's integer bound never binds an integer mean.
_DTYPE_RETAINING = frozenset({"sum", "min", "max"})


@dataclass(frozen=True, slots=True)
class Aggregated:
    """One reduced series in PLOTTED order, with the evidence G11 publishes beside it.

    `counts` is aligned with `keys` and sums to the data-row count of the file for every input,
    because every row joins exactly one group. That totality is what keeps G7's range claim and
    G8's ROW COVERAGE unconditional while aggregation is admitted: a `groupby` drops no row. It
    does collapse rows into fewer points than the file has rows, which is why G8 is coverage rather
    than point-count equality and why `counts` is published rather than merely computed.
    """

    keys: tuple[CellValue, ...]
    values: tuple[float, ...]
    counts: tuple[int, ...]
    dtype: ColumnDtype


def _refuse(code: RefusalCode) -> NoReturn:
    raise PysrcRefusalError(code)


def column_dtype(texts: tuple[str, ...]) -> ColumnDtype:
    """`int64` only when NO cell carries a decimal point, which is pandas' own inference.

    Reading the TEXT rather than the parsed float is what makes this exact: `5` and `5.0` parse to
    the same float64 and pandas types their columns differently.
    """
    return "float64" if any("." in text for text in texts) else "int64"


def _kahan_sum(values: tuple[float, ...]) -> float:
    """Ordered binary64 Kahan compensation. Not naive, not `fsum`, not Neumaier.

    The compensation reset pandas performs for NaN is absent because NaN cannot arrive: the cell
    profile refuses every NA spelling ahead of this call, so the arm would be an unreachable branch.
    """
    total = 0.0
    compensation = 0.0
    for value in values:
        adjusted = value - compensation
        running = total + adjusted
        compensation = (running - total) - adjusted
        total = running
    return total


def _extremum[T: (float, int)](values: tuple[T, ...], *, greater: bool) -> T:
    """Strict `<`/`>`, so a tie keeps the FIRST value's bits -- `[-0.0, +0.0]` reduces to `-0.0`."""
    best = values[0]
    for value in values[1:]:
        if (value > best) if greater else (value < best):
            best = value
    return best


def _reduce_float(values: tuple[float, ...], reduction: Reduction) -> float:
    match reduction:
        case "sum":
            return _kahan_sum(values)
        case "mean":
            # Sum THEN divide, in that order. A running mean and a compensated divide each land on a
            # different last bit, and this is the order pandas takes.
            return _kahan_sum(values) / len(values)
        case "min":
            return _extremum(values, greater=False)
        case "max":
            return _extremum(values, greater=True)
        case _ as unreachable:  # pragma: no cover - `Reduction` is closed
            assert_never(unreachable)


def _reduce_int(values: tuple[int, ...], reduction: Reduction) -> float:
    match reduction:
        case "sum":
            # Exact: Python integers do not wrap where pandas' int64 would, and the profile makes
            # that difference unreachable -- int32 cells times `max_table_rows` stays under 2**48,
            # so the result is also exactly representable in the float64 the table carries.
            return float(sum(values))
        case "mean":
            # Per-value float cast, THEN Kahan, THEN divide. Not the exact integer mean: pandas
            # rounds each value into float64 first, and `[2**53, 1, 0]` is where the two split.
            return _kahan_sum(tuple(float(value) for value in values)) / len(values)
        case "min":
            return float(_extremum(values, greater=False))
        case "max":
            return float(_extremum(values, greater=True))
        case _ as unreachable:  # pragma: no cover - `Reduction` is closed
            assert_never(unreachable)


def _sort_key(value: CellValue) -> tuple[int, float, str]:
    """Total over one column's key class, and code-point ordered for text.

    Python compares `str` by code point, so ascending `sorted` IS pandas' `sort=True` order with no
    locale in the path. The leading discriminator keeps the function total without ever comparing a
    number against a string, which would raise.
    """
    if isinstance(value, str):
        return (1, 0.0, value)
    return (0, value, "")


def aggregate_series(  # noqa: PLR0913 - six independent inputs, none derivable from another
    keys: tuple[CellValue, ...],
    value_texts: tuple[str, ...],
    values: tuple[float, ...],
    reduction: Reduction,
    *,
    budget: WorkBudget,
    max_groups: int,
) -> Aggregated:
    """Reduce `values` by `keys`, in the order and to the bits the executed program would plot.

    `keys` and `value_texts` are the two selected columns in FILE order, already swept against the
    cell profile by the caller. `value_texts` decides the dtype; `values` carries the parsed
    float64 the float path reduces.

    Row order inside each group is file order, which is what makes the ordered summation
    well defined; group order is sorted key order, which is what the figure draws along x.
    """
    budget.charge(len(keys))
    members: dict[CellValue, list[int]] = {}
    for index, key in enumerate(keys):
        members.setdefault(key, []).append(index)
    # Checked BEFORE the reduction it bounds: a high-cardinality key column must refuse on what it
    # would cost rather than after paying it.
    if len(members) > max_groups:
        _refuse("work_budget_exceeded")
    budget.charge(len(members))

    dtype = column_dtype(value_texts)
    integers = tuple(int(text) for text in value_texts) if dtype == "int64" else ()
    ordered = sorted(members, key=_sort_key)
    reduced: list[float] = []
    counts: list[int] = []
    for key in ordered:
        rows = members[key]
        counts.append(len(rows))
        if dtype == "int64":
            reduced.append(_reduce_int(tuple(integers[index] for index in rows), reduction))
        else:
            reduced.append(_reduce_float(tuple(values[index] for index in rows), reduction))
    result_dtype: ColumnDtype = (
        "int64" if dtype == "int64" and reduction in _DTYPE_RETAINING else "float64"
    )
    return Aggregated(
        keys=tuple(ordered),
        values=tuple(reduced),
        counts=tuple(counts),
        dtype=result_dtype,
    )
'''

_SOURCES["verifier.pysrc.prescan"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Bound untrusted bytes BEFORE the CPython parser sees them.

`ast.parse` executes nothing, but it recurses: deeply nested source is answered by a C-stack
failure rather than by an exception a verdict can be built from. A post-parse depth check is
therefore too late, and this module is what runs first. It imports no `ast` at all -- a committed
search test pins that -- so no path here can reach the parser early.

`tokenize` is a TCB addition for this package alone. It is chosen over a hand-rolled character scan
because it understands Python string literals: a naive scan counting `(` would refuse
`plt.title("f(x) = sin(x)")`, which is ordinary matplotlib code. It recurses nowhere, and the byte
cap is charged before it runs, so its worst case is bounded by that cap.

Order is load-bearing and cheapest-first: every step assumes its predecessors held.
"""

import io
import tokenize
from tokenize import TokenInfo
from typing import NoReturn

from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import PysrcLimits, validate_limits

_OPENERS = frozenset("([{")
_CLOSERS = frozenset(")]}")


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


def _decode(source: bytes) -> str:
    try:
        return source.decode("utf-8")
    except UnicodeDecodeError as exc:
        _refuse("source_not_utf8", exc)


def _tokenize(text: str) -> list[TokenInfo]:
    try:
        return list(tokenize.generate_tokens(io.StringIO(text).readline))
    # A malformed program must produce a verdict, never a tokenizer traceback. `TokenError` is the
    # actual shape on 3.13 (measured: unterminated string, unterminated triple-quote, trailing
    # backslash) and derives straight from `Exception`, so catching `ValueError` alone would have
    # caught nothing; `SyntaxError` is what the 3.12+ f-string tokenizer raises instead.
    except (tokenize.TokenError, SyntaxError) as exc:
        _refuse("source_not_tokenizable", exc)


def _check_bracket_depth(tokens: list[TokenInfo], limit: int) -> None:
    depth = 0
    for token in tokens:
        if token.type != tokenize.OP:
            continue
        if token.string in _OPENERS:
            depth += 1
            if depth > limit:
                _refuse("nesting_too_deep")
        elif token.string in _CLOSERS:
            depth -= 1
            # A closer with no opener never balances later; refusing here keeps the counter from
            # going negative and masking a genuinely deep region further on.
            if depth < 0:
                _refuse("unbalanced_brackets")


def _check_indent_depth(tokens: list[TokenInfo], limit: int) -> None:
    depth = 0
    for token in tokens:
        if token.type == tokenize.INDENT:
            depth += 1
            if depth > limit:
                _refuse("indent_too_deep")
        elif token.type == tokenize.DEDENT:
            depth -= 1


def prescan(source: bytes, limits: PysrcLimits) -> str:
    """Return the decoded source, or raise `PysrcRefusalError`.

    The returned text is what the caller may hand to `ast.parse`; nothing else in this package
    should parse bytes that did not come back from here.
    """
    validate_limits(limits)

    # First and unconditional: everything below is bounded by this cap, so it may not be skipped
    # or reordered. Charging it against the raw bytes also keeps a decode bomb out of memory.
    if len(source) > limits.max_source_bytes:
        _refuse("source_too_large")

    text = _decode(source)

    # The parser rejects NUL too, but only after accepting the buffer; refusing here keeps the
    # closed refusal vocabulary total over inputs the parser would answer with its own error.
    if "\x00" in text:
        _refuse("source_has_nul")

    for line in text.splitlines():
        if len(line.encode("utf-8")) > limits.max_line_bytes:
            _refuse("line_too_long")

    tokens = _tokenize(text)
    if len(tokens) > limits.max_tokens:
        _refuse("too_many_tokens")

    _check_bracket_depth(tokens, limits.max_bracket_depth)
    _check_indent_depth(tokens, limits.max_indent_depth)
    return text
'''

_SOURCES["verifier.pysrc.project"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Admitted AST -> core plot spec. This is where the projection gap is closed.

Admission answers "may these bytes run". Projection answers "what do they draw", and the verifier
stakes every downstream claim on that answer, so the gap -- *what the projection says the script
plots* vs *what the script plots when executed* -- is closed BY CONSTRUCTION here rather than
declared trusted: every admitted statement must contribute to the returned spec, and a statement
whose effect the spec cannot represent is refused. Nothing is silently ignored. A construct added
to `admit.py` without a projection rule therefore fails closed instead of vanishing from the claim.

Bound names are SUBSTITUTED away, so the spec depends on what the program computes and not on what
the model chose to call it. Two programs differing only in variable names project to equal specs.

Scope is the formula arm. `plt.bar` is refused here rather than in `admit.py` because it is
admissible in the dataset arm: what refuses it is the arm, not the call.
"""

import ast
import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import NoReturn, assert_never, cast

from verifier.pysrc.admit import (
    ADMITTED_ACCESSOR_KINDS,
    ADMITTED_UNWRAPPED_ATTRS,
    accessor_is_subscripted,
    accessor_kind,
    accessor_receiver,
    aggregation_chain,
)
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits, validate_limits
from verifier.pysrc.spec import (
    MAX_EXPR_DEPTH,
    Bin,
    BinOp,
    Column,
    Const,
    ConstName,
    CorePlotSpec,
    DatasetMark,
    DatasetPlot,
    DatasetRef,
    Expr,
    Fn,
    FnName,
    FormulaMark,
    FormulaPlot,
    Grid,
    Labels,
    Neg,
    Num,
    Reduction,
    Var,
    expr_height,
)

_GRID_CALLS = frozenset({"np.linspace", "np.arange"})
# Source spelling -> projected meaning. Exhaustive over `admit.ADMITTED_CALL_TARGETS`' math group;
# a target admitted but missing here reaches the closed tail and refuses.
_FUNCTIONS: dict[str, FnName] = {
    "np.sin": "sin",
    "np.cos": "cos",
    "np.tan": "tan",
    "np.exp": "exp",
    "np.log": "log",
    "np.sqrt": "sqrt",
    "np.abs": "abs",
}
_CONSTANTS: dict[str, ConstName] = {"np.pi": "pi", "np.e": "e"}
_MARKS: dict[str, FormulaMark] = {"plt.plot": "line", "plt.scatter": "scatter"}
# The same three targets, read under the other arm. Bar appears here and not above: G5 bans bar for
# SAMPLED FUNCTIONS, not for CSV columns.
_DATASET_MARKS: dict[str, DatasetMark] = {
    "plt.plot": "line",
    "plt.scatter": "scatter",
    "plt.bar": "bar",
    "plt.barh": "barh",
}
# Source spelling -> reduced meaning, mirroring `admit._REDUCTIONS`: admission decides which chains
# exist, projection names what each one computes.
_REDUCTIONS: dict[str, Reduction] = {"sum": "sum", "mean": "mean", "min": "min", "max": "max"}
_SOURCE_CALL = "pd.read_csv"
# A mark resolved at its own statement, still owing the decorations that may follow it. Holding the
# builder rather than the node is what keeps LOCAL-before-GLOBAL true for channels and arity.
type _MarkBuilder = Callable[[Labels], CorePlotSpec]


@dataclass(frozen=True, slots=True)
class _Aggregate:
    """A projected `groupby` chain: the frame it reads, its two columns, and the reduction."""

    frame: str
    key: Column
    column: Column
    reduction: Reduction


def _reset_index_inner(node: ast.Call) -> ast.Call | None:
    """The aggregation call under a trailing `.reset_index()`, or `None` for every other shape.

    The unwrap is BY NAME against `admit.ADMITTED_UNWRAPPED_ATTRS`. Admission closes the trailing
    link as a CLASS -- one no-argument, non-underscore call -- so `.sort_values()` arrives here
    already admitted; unwrapping whatever it finds would read a REORDERED series as the chain
    beneath it, and both G8's row coverage and G9's ordering are read off group-key order.
    """
    func = node.func
    if (
        not isinstance(func, ast.Attribute)
        or func.attr not in ADMITTED_UNWRAPPED_ATTRS
        or not isinstance(func.value, ast.Call)
    ):
        return None
    return func.value


def _uses_grid(tree: ast.Module) -> bool:
    """Whether a grid call appears anywhere -- the formula arm's structural selector.

    Reads the spelling INLINE and refuses nothing. This runs before any statement does, so a
    refusal here would decide the ARM for every program merely holding a call whose receiver is not
    a bare name -- and an aggregation chain is exactly that call.
    """
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and f"{node.func.value.id}.{node.func.attr}" in _GRID_CALLS
        for node in ast.walk(tree)
    )


# Admissible source, inadmissible for THIS arm: a sampled function has no categorical magnitude to
# encode as a length from a zero baseline (G5). Both bar spellings live here and in NEITHER
# `_MARKS`, so the wrong arm can never index a formula mark that does not exist.
_WRONG_ARM_MARKS = frozenset({"plt.bar", "plt.barh"})
_TERMINAL = "plt.show"
_TEXT_LABELS = frozenset({"plt.title", "plt.xlabel", "plt.ylabel"})
_FLAG_LABELS = frozenset({"plt.legend", "plt.grid"})
_FIGURE = "plt.figure"
_TIGHT_LAYOUT = "plt.tight_layout"
_XTICKS = "plt.xticks"
# Cosmetic calls: none can move a plotted number, so each projects onto a `Labels` field and the
# figure it describes is the same figure. Carrying them is what keeps "nothing is silently ignored"
# true once they are admitted.
_PRESENTATION = frozenset({_FIGURE, _TIGHT_LAYOUT, _XTICKS})

# A mark draws one series: x and y, never an implicit x and never a third positional.
_MARK_ARITY = 2
# Width and height, the only tuple the language admits at all.
_FIGSIZE_ARITY = 2
_LINSPACE_BOUNDS_ARITY = 2
_LINSPACE_FULL_ARITY = 3
_ARANGE_MAX_ARITY = 3
# Every integer up to 2**53 is exactly representable in float64; 2**52 leaves the difference of
# two bounds inside that range, which is what makes `arange`'s float64 sizing provably exact.
_EXACT_INT = 2**52

# The exact folder a grid bound and a declared target bound share (user rulings Q9 + Q17): `+ - * /`
# over literals and negations, `**` only with an integer-literal exponent of magnitude at most
# `_POW_EXPONENT_MAX`. EVERY node must also be exact in binary64 and at most `_FOLD_MAX` in
# magnitude: there Python's exact ints, numpy's float64 and IEEE's correctly rounded `+ - * /` all
# agree with the exact value, so the fold is what the executed program computes. `1/49*49` (exact
# 1, binary64 0.9999999999999999) would otherwise shift an `arange` start and change its sample
# count. A zero divisor, a wider power or an inexact node folds to None.
_POW_EXPONENT_MAX = 64
_FOLD_MAX = 2**53


def _exact_node(value: Fraction) -> Fraction | None:
    if abs(value) > _FOLD_MAX or Fraction(float(value)) != value:
        return None
    return value


def _computed(value: Fraction | None) -> Fraction | None:
    """A COMPUTED zero has a sign `Fraction` cannot carry: `0 / -1` and `-0.0` execute as -0.0,
    a different number downstream (`-1 / x` is +inf there, -inf at +0.0). Only a literal zero
    folds."""
    return None if value == 0 else value


def _fold_pow(base: Fraction, exponent_node: Expr, exponent: Fraction) -> Fraction | None:
    literal = isinstance(exponent_node, Num) or (
        isinstance(exponent_node, Neg) and isinstance(exponent_node.operand, Num)
    )
    if not literal or exponent.denominator != 1 or abs(exponent) > _POW_EXPONENT_MAX:
        return None
    if base == 0 and exponent < 0:
        return None
    return _exact_node(base ** int(exponent))


def same_bound(program: Expr, declared: Expr) -> bool:
    """Two grid bounds agree by EXACT value when both fold (user ruling Q17), else by tree.

    Shared by target binding (`verify.bind_target`) and the certificate's provenance
    (`certificate._target_consumed`), so the two can never disagree on whether a target bound.

    `np.arange(-5, 6)` projects its start to `Num(-5)` while the request keeps `-5` as `Neg(Num)`;
    both fold to -5. `fold_exact` folds only a tree binary64 computes exactly, so a bound the
    program rounds (`1/49*49`) still compares by tree and refuses.
    """
    if expr_height(declared) > MAX_EXPR_DEPTH:
        return False  # deeper than any tree projection admits: no program bound equals it
    left, right = fold_exact(program), fold_exact(declared)
    if left is not None and right is not None:
        return left == right
    return program == declared


def _fold_bin(op: BinOp, left: Fraction, right: Fraction, right_node: Expr) -> Fraction | None:
    match op:
        case "add":
            return _computed(_exact_node(left + right))
        case "sub":
            return _computed(_exact_node(left - right))
        case "mul":
            return _computed(_exact_node(left * right))
        case "div":
            return None if right == 0 else _computed(_exact_node(left / right))
        case "pow":
            return _computed(_fold_pow(left, right_node, right))
        case _:  # pragma: no cover - `BinOp` is closed
            assert_never(op)


def fold_exact(expr: Expr) -> Fraction | None:
    """The exact value of a closed arithmetic tree every node of which binary64 computes exactly."""
    if isinstance(expr, Num):
        return _exact_node(expr.value)
    if isinstance(expr, Neg):
        operand = _computed(fold_exact(expr.operand))
        return None if operand is None else -operand
    if not isinstance(expr, Bin):
        return None  # `Var`, `Const`, `Fn`: no exact rational
    left, right = fold_exact(expr.left), fold_exact(expr.right)
    if left is None or right is None:
        return None
    return _fold_bin(expr.op, left, right, expr.right)


_BINOPS: dict[type[ast.operator], BinOp] = {
    ast.Add: "add",
    ast.Sub: "sub",
    ast.Mult: "mul",
    ast.Div: "div",
    ast.Pow: "pow",
}


def _refuse(code: RefusalCode) -> NoReturn:
    raise PysrcRefusalError(code)


def _dotted(node: ast.Attribute) -> str:
    """`alias.attr` for a chain admission has already bounded to depth 1."""
    value = node.value
    if not isinstance(value, ast.Name):  # pragma: no cover - admission refuses deeper chains
        _refuse("expression_not_projected")
    return f"{value.id}.{node.attr}"


def _target(node: ast.Call) -> str | None:
    """`alias.attr` for a call on a bare name, `None` for every other receiver.

    Non-refusing on purpose. An aggregation chain calls its reduction on a SUBSCRIPT, so every
    caller here has to be able to recognize that shape and refuse it with its own stage's code --
    a refusal inside this function would land the wrong one, or land it too early.
    """
    func = node.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return None
    return f"{func.value.id}.{func.attr}"


def _exact(node: ast.expr) -> Fraction:
    """A numeric literal's exact value. Non-finite refuses rather than raising inside `Fraction`.

    Exact type, never `isinstance`: `bool` subclasses `int`, and `figsize=(True, 6)` is not a size.
    """
    if not isinstance(node, ast.Constant):  # pragma: no cover - admission requires the literal
        _refuse("label_not_literal")
    value = node.value
    if type(value) is int:
        return Fraction(value)
    if type(value) is not float or not math.isfinite(value):
        _refuse("label_not_literal")
    return Fraction(value)


def _figsize(node: ast.Call) -> tuple[Fraction, Fraction] | None:
    """`figsize=(w, h)` exactly, or `None` for the bare call that opens a default-sized figure."""
    if not node.keywords:
        return None
    size = node.keywords[0].value
    if (
        not isinstance(size, ast.Tuple) or len(size.elts) != _FIGSIZE_ARITY
    ):  # pragma: no cover - admission requires the 2-tuple
        _refuse("label_not_literal")
    return _exact(size.elts[0]), _exact(size.elts[1])


class _Projector:
    """One projection. Mutable only for the duration of a single `project` call."""

    def __init__(self, limits: PysrcLimits) -> None:
        self._limits = limits
        self._aliases: set[str] = set()
        self._grids: dict[str, Grid] = {}
        self._exprs: dict[str, ast.expr] = {}
        self._depth = 0
        self._used: set[str] = set()
        self._mark: _MarkBuilder | None = None
        self._frames: dict[str, DatasetRef] = {}
        self._cols: dict[str, tuple[str, Column]] = {}
        self._aggs: dict[str, _Aggregate] = {}
        # A chain re-spelled by `.reset_index()`, kept in its OWN table rather than flagged inside
        # `_aggs`: the reset frame's `.index` is a fresh RangeIndex and not the group key, so the
        # two spellings must not cross, and separate tables make that structural instead of a
        # conjunct every later reader has to remember.
        self._resets: dict[str, _Aggregate] = {}
        self._pandas = False
        # Decorations are collected keyed by their source target and assembled into `Labels` once,
        # so every field has exactly one origin and no branch has to guess which field it is.
        self._decorated: set[str] = set()
        self._text: dict[str, str] = {}
        self._flags: dict[str, bool] = {}
        self._series: str | None = None
        self._figsize: tuple[Fraction, Fraction] | None = None
        self._tick_rotation: Fraction | None = None
        self._tight_layout = False
        # Anything already ON the figure -- a mark, a decoration, a layout call. `plt.figure` is
        # the only call that reads it, and it is what makes that call positional rather than free.
        self._drawn = False
        self._grid_in_scope: Grid | None = None
        self._terminal = False

    # --- expressions ---------------------------------------------------------

    def _literal(self, node: ast.Constant) -> Expr:
        value = node.value
        # Exact type, never `isinstance`: `bool` subclasses `int`, and `True` is a flag for
        # `plt.grid`, never a number to plot.
        if type(value) is int:
            return Num(Fraction(value))
        if type(value) is float:
            # The executed program hands numpy the float64, so the projection carries the float64.
            if not math.isfinite(value):
                _refuse("expression_not_projected")
            return Num(Fraction(value))
        _refuse("expression_not_projected")

    def _expr(self, node: ast.expr, grid_name: str | None) -> Expr:
        """Project one admitted expression, substituting bound names away.

        `grid_name` is the only free name the result may carry; `None` means none may. Nesting --
        operators and the alias chains substitution follows -- is bounded at `MAX_EXPR_DEPTH`
        (Q34): an unbounded chain (`a1 = a0`, `a2 = a1`, ...) recursed until Python raised.
        """
        self._depth += 1
        try:
            if self._depth > MAX_EXPR_DEPTH:
                _refuse("expression_not_projected")
            return self._expr_node(node, grid_name)
        finally:
            self._depth -= 1

    def _expr_node(self, node: ast.expr, grid_name: str | None) -> Expr:
        if isinstance(node, ast.Constant):
            return self._literal(node)
        if isinstance(node, ast.Name):
            return self._name(node.id, grid_name)
        if isinstance(node, ast.Attribute):
            constant = _CONSTANTS.get(_dotted(node))
            if constant is None:  # pragma: no cover - `ADMITTED_CONSTANT_ATTRS` == `_CONSTANTS`
                _refuse("expression_not_projected")
            return Const(constant)
        if isinstance(node, ast.Call):
            return self._call_expr(node, grid_name)
        if isinstance(node, ast.BinOp):
            operator = _BINOPS.get(type(node.op))
            if operator is None:  # pragma: no cover - admission closes the operator set
                _refuse("expression_not_projected")
            left = self._expr(node.left, grid_name)
            return Bin(operator, left, self._expr(node.right, grid_name))
        if isinstance(node, ast.UnaryOp):
            return Neg(self._expr(node.operand, grid_name))
        _refuse("expression_not_projected")  # pragma: no cover - admission closes the tail

    def _call_expr(self, node: ast.Call, grid_name: str | None) -> Expr:
        target = _target(node)
        if target in _GRID_CALLS:
            # The grid call written twice -- once as x, once inside y -- names the same sample
            # points, so it projects to the grid variable exactly when the two grids are equal.
            if self._grid(node) != self._grid_in_scope:
                _refuse("y_not_over_grid")
            return Var()
        if target is None:
            # An aggregation chain in value position. It reduces a column rather than naming a
            # number, and no formula-arm expression can hold one.
            _refuse("expression_not_projected")
        function = _FUNCTIONS.get(target)
        if function is None or len(node.args) != 1 or node.keywords:
            _refuse("expression_not_projected")
        return Fn(function, self._expr(node.args[0], grid_name))

    def _name(self, name: str, grid_name: str | None) -> Expr:
        if name == grid_name:
            return Var()
        bound_grid = self._grids.get(name)
        if bound_grid is not None:
            # A grid reached by a route other than the mark's x argument. Structural equality
            # decides it: the same sample points ARE the grid variable, however the model spelled
            # them, and different points mean y is not a function of THE grid.
            if bound_grid != self._grid_in_scope:
                _refuse("y_not_over_grid")
            self._used.add(name)
            return Var()
        bound = self._exprs.get(name)
        if bound is None:
            # An alias (`np`, `plt`) in value position, or a name admission bound but projection
            # never saw -- neither denotes a number.
            _refuse("expression_not_projected")
        self._used.add(name)
        return self._expr(bound, grid_name)

    def _rational(self, node: ast.expr) -> Fraction:
        """A grid bound that arithmetic must reach: `fold_exact` or `grid_not_representable`."""
        value = fold_exact(self._expr(node, None))
        if value is None:
            _refuse("grid_not_representable")
        return value

    # --- grids ---------------------------------------------------------------

    def _samples(self, count: int) -> int:
        if not (self._limits.min_grid_samples <= count <= self._limits.max_grid_samples):
            _refuse("grid_not_representable")
        return count

    def _linspace(self, node: ast.Call) -> Grid:
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        num_node = keywords.get("num")
        if len(node.args) == _LINSPACE_FULL_ARITY:
            if num_node is not None:
                _refuse("grid_not_representable")
            num_node = node.args[2]
        elif len(node.args) != _LINSPACE_BOUNDS_ARITY:
            _refuse("grid_not_representable")
        if num_node is None:
            count = 50  # numpy's own default; a program omitting `num` still draws 50 points.
        elif isinstance(num_node, ast.Constant) and type(num_node.value) is int:
            count = num_node.value
        else:
            # A bound name resolving to 10 is still not a literal: the count has to be readable
            # from the source, or the grid's size depends on evaluation.
            _refuse("grid_not_representable")
        return Grid(
            start=self._expr(node.args[0], None),
            stop=self._expr(node.args[1], None),
            samples=self._samples(count),
        )

    def _arange(self, node: ast.Call) -> Grid:
        if node.keywords or not 1 <= len(node.args) <= _ARANGE_MAX_ARITY:
            _refuse("grid_not_representable")
        bounds = [self._rational(arg) for arg in node.args]
        start, stop = (Fraction(0), bounds[0]) if len(bounds) == 1 else (bounds[0], bounds[1])
        step = bounds[2] if len(bounds) == _ARANGE_MAX_ARITY else Fraction(1)
        # INTEGERS ONLY, and it is a faithfulness bound rather than a taste. numpy sizes `arange`
        # as ceil((stop - start) / step) in float64 and accumulates its samples in float64, so a
        # non-integer step makes the EXECUTED array disagree with the exact-rational grid by a
        # whole step: measured, `arange(0, 3, 0.3)` draws 10 points ending at 2.6999999999999997
        # where the exact grid says 11 ending at 3, and `arange(1, 2, 0.1)` ends at
        # 1.9000000000000008, not 1.9. numpy's own reference calls non-integer steps inconsistent
        # and points at `linspace`, which is the admitted tool for real-valued sampling and whose
        # residual is a per-sample rounding rather than a different number of samples. Under
        # `_EXACT_INT` every operation above is exact in float64, so the projection stays faithful
        # BY CONSTRUCTION; over it, `ceil` could misround.
        if any(value.denominator != 1 for value in (start, stop, step)) or any(
            abs(value.numerator) > _EXACT_INT for value in (start, stop, step)
        ):
            _refuse("grid_not_representable")
        if step == 0:
            _refuse("grid_not_representable")
        span = (stop - start) / step
        if span <= 0:
            _refuse("grid_not_representable")
        # Half-open: `arange(0, 10)` is 0..9. Normalizing onto an inclusive stop is what makes one
        # `Grid` shape serve both call forms, and it is why this form needs exact arithmetic.
        count = self._samples(math.ceil(span))
        return Grid(start=Num(start), stop=Num(start + (count - 1) * step), samples=count)

    def _grid(self, node: ast.Call) -> Grid:
        return self._linspace(node) if _target(node) == "np.linspace" else self._arange(node)

    # --- dataset arm ---------------------------------------------------------

    def _source(self, node: ast.Call) -> DatasetRef:
        if len(node.args) != 1 or node.keywords:
            _refuse("source_not_literal")
        arg = node.args[0]
        if not isinstance(arg, ast.Constant) or type(arg.value) is not str:
            _refuse("source_not_literal")
        return DatasetRef(path=arg.value)

    def _column_parts(self, node: ast.Subscript) -> tuple[str, Column]:
        """`<frame>["<literal>"]` split into the frame it reads and the column it names."""
        value = node.value
        if not isinstance(value, ast.Name):  # pragma: no cover - admission refuses other bases
            _refuse("column_not_from_source")
        index = node.slice
        if not isinstance(index, ast.Constant) or type(index.value) is not str:
            _refuse("column_not_literal")  # pragma: no cover - admission refuses non-literal keys
        return value.id, Column(name=index.value)

    def _channel(self, node: ast.expr) -> tuple[str, Column]:
        """One mark channel, from the inline subscript or the name a subscript was bound to."""
        if isinstance(node, ast.Subscript):
            frame, column = self._column_parts(node)
        elif isinstance(node, ast.Name) and node.id in self._cols:
            frame, column = self._cols[node.id]
            self._used.add(node.id)
        else:
            _refuse("column_not_from_source")
        if frame not in self._frames:
            _refuse("column_not_from_source")
        self._used.add(frame)
        return frame, column

    # --- statements ----------------------------------------------------------

    def _assign(self, node: ast.Assign) -> None:
        target = node.targets[0]
        if not isinstance(target, ast.Name):  # pragma: no cover - admission refuses other targets
            _refuse("statement_not_projected")
        name = target.id
        if (
            name in self._aliases
            or name in self._grids
            or name in self._exprs
            or name in self._frames
            or name in self._cols
            or name in self._aggs
            or name in self._resets
        ):
            _refuse("name_rebound")
        value = node.value
        if isinstance(value, ast.Call):
            self._assign_call(name, value)
            return
        if isinstance(value, ast.Subscript):
            self._cols[name] = self._column_parts(value)
            return
        # Held unprojected: a bound expression is only meaningful once the grid it reads is known,
        # and that is decided at the mark.
        self._exprs[name] = value

    def _assign_call(self, name: str, node: ast.Call) -> None:
        target = _target(node)
        if target in _GRID_CALLS:
            self._grids[name] = self._grid(node)
            return
        if target == _SOURCE_CALL:
            if self._frames:
                _refuse("multiple_sources")
            self._frames[name] = self._source(node)
            return
        if target is None:
            # `None` is exactly the LINKED aggregation shapes: a reduction called on a subscript,
            # or a trailing call on a reduction. A bare `<frame>.groupby("<key>")` keeps its target
            # and falls through to `_exprs`, where it reduces nothing and is never used.
            inner = _reset_index_inner(node)
            if inner is None:
                self._aggs[name] = self._aggregate(node)
            else:
                # Same reduction, DIFFERENT spelling of its channels: the reset re-publishes the
                # series as a two-column frame, so it binds a reset name rather than an aggregate.
                self._resets[name] = self._aggregate(inner)
            return
        self._exprs[name] = node

    def _aggregate(self, node: ast.Call) -> _Aggregate:
        """Decompose the one chain shape that HAS a projection."""
        chain = aggregation_chain(node)
        if chain is None:
            _refuse("aggregation_not_projected")
        if chain.frame not in self._frames:
            _refuse("column_not_from_source")
        return _Aggregate(
            frame=chain.frame,
            key=Column(name=chain.key),
            column=Column(name=chain.column),
            reduction=_REDUCTIONS[chain.reduction],
        )

    def _label_call(self, target: str, node: ast.Call) -> None:
        if target in self._decorated:
            # The earlier call ran, and its text would vanish from the spec.
            _refuse("statement_not_projected")
        self._decorated.add(target)
        if target in _TEXT_LABELS:
            if len(node.args) != 1 or node.keywords:
                _refuse("label_not_literal")
            text = node.args[0]
            if not isinstance(text, ast.Constant) or type(text.value) is not str:
                _refuse("label_not_literal")
            self._text[target] = text.value
            return
        if node.keywords or len(node.args) > 1:
            _refuse("label_not_literal")
        flag = True
        if node.args:
            arg = node.args[0]
            if not isinstance(arg, ast.Constant) or type(arg.value) is not bool:
                _refuse("label_not_literal")
            flag = arg.value
        self._flags[target] = flag

    def _presentation_call(self, target: str, node: ast.Call) -> None:
        """The three cosmetic calls. Each fills a `Labels` field and none moves a number."""
        if target == _FIGURE:
            # The one cosmetic call bound to a POSITION: a new figure is a new canvas, so whatever
            # was already drawn -- a mark, a title, a layout call -- is not in the artifact this
            # program emits, and the spec would describe a chart the PNG does not contain. A second
            # `plt.figure` orphans the first for the same reason.
            if self._drawn:
                _refuse("figure_orphans_mark")
            self._drawn = True
            self._figsize = _figsize(node)
            return
        if target in self._decorated:
            # The earlier call ran, and its effect would vanish from the spec.
            _refuse("statement_not_projected")
        self._decorated.add(target)
        self._drawn = True
        if target == _TIGHT_LAYOUT:
            # Admission refuses every argument here: a positional (`_NO_POSITIONAL_TARGETS`) and
            # every keyword (an empty allowlist), so the call is bare.
            self._tight_layout = True
            return
        if target == _XTICKS:
            # A bare `plt.xticks()` READS the current ticks and changes nothing, so there is
            # nothing to represent. A positional, which SETS ticks, never gets here: admission
            # refuses it (`_NO_POSITIONAL_TARGETS`).
            if not node.keywords:
                _refuse("statement_not_projected")
            self._tick_rotation = _exact(node.keywords[0].value)
            return
        _refuse("statement_not_projected")  # pragma: no cover - `_PRESENTATION` is closed

    def _labels(self) -> Labels:
        return Labels(
            title=self._text.get("plt.title"),
            xlabel=self._text.get("plt.xlabel"),
            ylabel=self._text.get("plt.ylabel"),
            series=self._series,
            legend=self._flags.get("plt.legend", False),
            grid=self._flags.get("plt.grid", False),
            figsize=self._figsize,
            tick_rotation=self._tick_rotation,
            tight_layout=self._tight_layout,
        )

    def _call_statement(self, node: ast.Call) -> None:
        receiver = accessor_receiver(node)
        if receiver is not None:
            # The accessor enters the SAME seam `plt.bar` enters, count included. A parallel route
            # would leave `multiple_marks` unfired, so an accessor beside a `plt.bar` would publish
            # one of two figures with no refusal -- and the spec cannot say which one the PNG holds.
            build = self._accessor_mark(receiver, node)
            if self._mark is not None:
                _refuse("multiple_marks")
            self._mark = build
            self._drawn = True
            return
        target = _target(node)
        if target is None:
            # An aggregation chain as a bare statement: admitted, computed, and discarded without
            # drawing anything. Representing it is impossible; ignoring it would widen the gap.
            _refuse("statement_not_projected")
        if target == _TERMINAL:
            if node.args or node.keywords:
                _refuse("statement_not_projected")
            self._terminal = True
            return
        if target in _DATASET_MARKS:
            # EVERYTHING local to this statement -- arm, arity, keywords, channels -- decides before
            # the program-wide mark count, because that is what LOCAL before GLOBAL means. Deferring
            # channel resolution to assembly made a first mark naming a bad column refuse on the
            # SECOND mark's existence instead. Only labels wait, since decorations may follow.
            if not self._pandas and target in _WRONG_ARM_MARKS:
                _refuse("mark_not_valid_for_arm")
            build = (
                self._resolve_dataset_mark(target, node)
                if self._pandas
                else self._resolve_mark(_MARKS[target], node)
            )
            if self._mark is not None:
                _refuse("multiple_marks")
            self._mark = build
            self._drawn = True
            return
        if target in _TEXT_LABELS or target in _FLAG_LABELS:
            self._label_call(target, node)
            self._drawn = True
            return
        if target in _PRESENTATION:
            self._presentation_call(target, node)
            return
        # An admitted call with no drawing effect -- `np.sin(x)` as a statement computes and
        # discards. Representing it is impossible; ignoring it would widen the gap.
        _refuse("statement_not_projected")

    def _statement(self, node: ast.stmt) -> None:
        if self._terminal:
            _refuse("statement_after_terminal")
        if isinstance(node, ast.Import):
            for alias in node.names:
                self._aliases.add(alias.asname or alias.name)
            return
        if isinstance(node, ast.Assign):
            self._assign(node)
            return
        if isinstance(node, ast.Expr):
            value = node.value
            if not isinstance(value, ast.Call):  # pragma: no cover - admission refuses non-calls
                _refuse("statement_not_projected")
            self._call_statement(value)
            return
        _refuse("statement_not_projected")  # pragma: no cover - admission closes the tail

    # --- assembly ------------------------------------------------------------

    def _mark_shape(self, node: ast.Call) -> None:
        """Arity plus the keywords -- identical under both arms, so stated once."""
        if len(node.args) != _MARK_ARITY:
            _refuse("mark_arity_not_projected")
        self._style_keywords(node)

    def _style_keywords(self, node: ast.Call) -> None:
        """Every mark keyword routed BY NAME; only `label` names the series.

        Style keywords are validated as text and then discarded: they carry no data, so the figure
        they describe is the same figure. Routing every keyword into the series is what would
        publish `steelblue` as the legend text of a chart whose legend says something else entirely.
        The accessor reaches this WITHOUT an arity check -- it takes no positional argument at all
        -- and its `kind` passes through as the literal it is, having already named the mark.
        """
        for keyword in node.keywords:
            text = keyword.value
            if not isinstance(text, ast.Constant) or type(text.value) is not str:
                # `color=df["city"]` is the colour-by-category channel in disguise: a data effect
                # wearing a cosmetic keyword's name.
                _refuse("label_not_literal")
            if keyword.arg == "label":
                self._series = text.value

    def _aggregate_bound(self, node: ast.expr, attribute: str) -> str | None:
        """The bound name behind `<name>.<attribute>`, when it names a projected aggregate."""
        if not isinstance(node, ast.Attribute) or node.attr != attribute:
            return None
        base = node.value
        if not isinstance(base, ast.Name) or base.id not in self._aggs:
            return None
        return base.id

    def _aggregate_channels(self, node: ast.Call) -> _Aggregate | None:
        """One mark reads ONE reduction: an `.index` x demands the SAME name's values as y.

        Mixing a reduced channel with a raw column, or reading `.values` as x, would draw a figure
        whose two axes come from different tables -- and their lengths would agree often enough for
        it to look right.
        """
        name = self._aggregate_bound(node.args[0], "index")
        if name is None:
            return None
        y = node.args[1]
        if self._aggregate_bound(y, "values") != name and not (
            isinstance(y, ast.Name) and y.id == name
        ):
            _refuse("column_not_from_source")
        self._used.add(name)
        return self._aggs[name]

    def _reset_subscript(self, node: ast.expr) -> tuple[str, Column] | None:
        """`<name>["<column>"]` over a RESET frame, split into that name and the column."""
        if not isinstance(node, ast.Subscript):
            return None
        name, column = self._column_parts(node)
        if name not in self._resets:
            return None
        return name, column

    def _reset_channels(self, node: ast.Call) -> _Aggregate | None:
        """A reset frame's two channels: x is the chain KEY, y is the chain's reduced COLUMN.

        The reset publishes one reduced series as a two-column frame, so the pair of channels is
        FULLY determined: `(<name>["<key>"], <name>["<column>"])` and nothing else. Swapping them
        draws the key as a magnitude, the key on both axes draws a chart of its own labels, and a
        third column names one the reset frame does not carry. One predicate over the whole pair,
        because every way of missing it is the same fault -- a channel the chain did not compute.
        """
        x = self._reset_subscript(node.args[0])
        if x is None:
            return None
        name = x[0]
        aggregate = self._resets[name]
        if (x, self._reset_subscript(node.args[1])) != (
            (name, aggregate.key),
            (name, aggregate.column),
        ):
            _refuse("column_not_from_source")
        self._used.add(name)
        return aggregate

    def _resolve_dataset_mark(self, target: str, node: ast.Call) -> _MarkBuilder:
        # The arm's precondition reads first: with no source bound, no channel can name a column,
        # so `column_not_from_source` would report a symptom where `no_source` names the cause.
        if not self._frames:
            _refuse("no_source")
        self._mark_shape(node)
        mark = _DATASET_MARKS[target]
        aggregate = self._aggregate_channels(node)
        if aggregate is None:
            aggregate = self._reset_channels(node)
        if aggregate is not None:
            return self._aggregate_mark(mark, aggregate)
        x_frame, x = self._channel(node.args[0])
        y_frame, y = self._channel(node.args[1])
        if x_frame != y_frame:  # pragma: no cover - `multiple_sources` keeps `_frames` a singleton
            # Dead while exactly one source binds, and kept anyway: the day a second source is
            # admitted, this is the line that stops the figure being a join no projection states.
            _refuse("column_not_from_source")
        source = self._frames[x_frame]
        return lambda labels: DatasetPlot(mark=mark, source=source, x=x, y=y, labels=labels)

    def _aggregate_mark(self, mark: DatasetMark, aggregate: _Aggregate) -> _MarkBuilder:
        """The ONE builder every aggregate spelling ends at.

        `plt.bar(g.index, g.values)`, the `.reset_index()` re-spelling and the accessor all reach
        it, which is what makes the three project EQUAL rather than merely alike: the spelling is
        decided in the resolution above and appears nowhere on the spec below.
        """
        self._used.add(aggregate.frame)
        grouped = self._frames[aggregate.frame]
        return lambda labels: DatasetPlot(
            mark=mark,
            source=grouped,
            x=aggregate.key,
            y=aggregate.column,
            labels=labels,
            group=aggregate.reduction,
        )

    def _accessor_mark(self, receiver: ast.Name, node: ast.Call) -> _MarkBuilder:
        """`<reduced series>.plot(kind="<mark>")`, resolved at its own statement.

        `kind` named the mark at ADMISSION, against a closed map onto `plt.bar`/`plt.barh`/
        `plt.plot`, so the two lookups below are total rather than defaulted. The receiver carries
        the channels, and only a reduced series states both of them: a frame, a raw column, a reset
        frame and a SELECTED ELEMENT of a reduced series each name a table whose x and y the
        projection would have to guess, so each refuses on the channel it cannot read.
        """
        # The arm's precondition reads first, exactly as `_resolve_dataset_mark` reads it: with no
        # source bound, `column_not_from_source` would report a symptom where `no_source` names
        # the cause. It carries the ARM too, and needs no `_pandas` test of its own: only
        # `pd.read_csv` binds a frame, so the formula arm reaches this with `_frames` empty and an
        # arm check would be a branch no program can take.
        if not self._frames:
            _refuse("no_source")
        self._style_keywords(node)
        # A receiver subscript is admitted as SHAPE and priced HERE: `g["revenue"]` selects one
        # element of the reduced series BY GROUP KEY, never a column, so the executed receiver is a
        # scalar and the spec this would state describes a figure the program never draws. Reading
        # the root alone verifies `g` for a program that plots something else.
        if accessor_is_subscripted(node) or receiver.id not in self._aggs:
            _refuse("column_not_from_source")
        self._used.add(receiver.id)
        # Admission refused every unreadable `kind`, so casting rather than re-testing keeps the
        # branch out of the module: an arm no input can take is one the coverage gate cannot price.
        kind = cast("str", accessor_kind(node))
        mark = _DATASET_MARKS[ADMITTED_ACCESSOR_KINDS[kind]]
        return self._aggregate_mark(mark, self._aggs[receiver.id])

    def _resolve_mark(self, mark: FormulaMark, node: ast.Call) -> _MarkBuilder:
        self._mark_shape(node)
        x_node = node.args[0]
        grid_name: str | None = None
        if isinstance(x_node, ast.Name) and x_node.id in self._grids:
            grid_name = x_node.id
            grid = self._grids[grid_name]
            self._used.add(grid_name)
        elif isinstance(x_node, ast.Call) and _target(x_node) in _GRID_CALLS:
            grid = self._grid(x_node)
        else:
            _refuse("x_not_a_grid")
        self._grid_in_scope = grid
        y = self._expr(node.args[1], grid_name)
        return lambda labels: FormulaPlot(mark=mark, grid=grid, y=y, labels=labels)

    def run(self, tree: ast.Module) -> CorePlotSpec:
        # The arm is settled from the tree BEFORE any statement runs, because a mark statement's own
        # validity depends on it. Both selectors present is a refusal, never a precedence.
        self._pandas = any(
            isinstance(node, ast.Import) and any(alias.name == "pandas" for alias in node.names)
            for node in tree.body
        )
        if self._pandas and _uses_grid(tree):
            _refuse("arm_ambiguous")
        for statement in tree.body:
            self._statement(statement)
        if self._mark is None:
            _refuse("no_mark")
        if not self._terminal:
            _refuse("no_terminal")
        # The mark resolved at its own statement; only the decorations, which may follow it, wait.
        plot = self._mark(self._labels())
        unused = (
            self._grids.keys()
            | self._exprs.keys()
            | self._frames.keys()
            | self._cols.keys()
            | self._aggs.keys()
            | self._resets.keys()
        ) - self._used
        if unused:
            # Bound, admitted, executed, and absent from the spec: exactly the gap this module
            # exists to close.
            _refuse("statement_not_projected")
        return plot


def project(tree: ast.Module, limits: PysrcLimits = DEFAULT_LIMITS) -> CorePlotSpec:
    """Project an ADMITTED tree onto the core plot spec, or raise `PysrcRefusalError`.

    `tree` must be what `parse_admitted` returned: every guarantee here rests on the allowlist
    having run first, and the closed tails below are unreachable only under that precondition.
    """
    validate_limits(limits)
    return _Projector(limits).run(tree)
'''

_SOURCES["verifier.pysrc.request"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Extract a formula target from the user's request, independently of program bytes.

The expression lexer consumes one maximal run at a time. Each carrier is visited once; the
Japanese interval probe skips starts inside a run it has already scanned. Nothing from a model
program or chat history enters this parser.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction
from typing import cast

from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits
from verifier.pysrc.spec import (
    MAX_EXPR_DEPTH,
    Bin,
    Const,
    Expr,
    Fn,
    FnName,
    FormulaTarget,
    Grid,
    Interval,
    Neg,
    Num,
    Var,
    expr_height,
)

REQUEST_GRAMMAR = "pyexpr-0.1"

_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FUNCTIONS = frozenset({"sin", "cos", "tan", "exp", "log", "sqrt", "abs"})
_CONSTANTS = frozenset({"pi", "e"})
_OPERATORS = frozenset({"+", "-", "*", "/", "(", ")"})


class _InvalidError(Exception):
    """A carrier cannot supply a target, never a verdict about the submitted program."""


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    text: str


def _word(char: str) -> bool:
    return "A" <= char <= "Z" or "a" <= char <= "z" or "0" <= char <= "9" or char == "_"


def _japanese(char: str) -> bool:
    return "　" <= char <= "ヿ" or "一" <= char <= "鿿"


def _start_boundary(text: str, index: int) -> bool:
    if index == 0:
        return True
    preceding = text[index - 1]
    return preceding.isspace() or _japanese(preceding) or preceding in ",;:="


def _prose_boundary(text: str, index: int) -> bool:
    if index == len(text):
        return True
    current = text[index]
    if current in " \t\r\n" or _japanese(current):
        return True
    if current in ",;:.?":
        next_index = index + 1
        return (
            next_index == len(text) or text[next_index] in " \t\r\n" or _japanese(text[next_index])
        )
    return False


def _spaces(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t":
        index += 1
    return index


def _lex(text: str, start: int, *, allow_x: bool) -> tuple[list[_Token], int]:
    """Return the maximal run; `end` excludes trailing blanks before a prose boundary."""
    tokens: list[_Token] = []
    index = start
    end = start
    while index < len(text):
        index = _spaces(text, index)
        if index == len(text):
            break
        char = text[index]
        if "0" <= char <= "9":
            matched = _NUMBER.match(text, index)
            if matched is None:  # pragma: no cover - every ASCII digit starts a number
                raise _InvalidError
            tokens.append(_Token("number", matched.group()))
            end = index = matched.end()
        elif ("A" <= char <= "Z") or ("a" <= char <= "z") or char == "_":
            matched = _IDENTIFIER.match(text, index)
            if matched is None:  # pragma: no cover - every ASCII letter starts an identifier
                raise _InvalidError
            name = matched.group()
            if name not in _FUNCTIONS and name not in _CONSTANTS and not (allow_x and name == "x"):
                break
            tokens.append(_Token("name", name))
            end = index = matched.end()
        elif text.startswith("**", index):
            tokens.append(_Token("operator", "**"))
            end = index = index + 2
        elif char in _OPERATORS:
            tokens.append(_Token("operator", char))
            end = index = index + 1
        else:
            break
    return tokens, end


class _Expression:
    def __init__(self, tokens: list[_Token], limits: PysrcLimits) -> None:
        self.tokens = tokens
        self.index = 0
        self.nodes = 0
        self.limits = limits

    def _node(self, value: Expr) -> Expr:
        self.nodes += 1
        if self.nodes > self.limits.max_expr_nodes:
            raise _InvalidError
        return value

    def _nest(self, depth: int) -> int:
        if depth >= self.limits.max_bracket_depth:
            raise _InvalidError
        return depth + 1

    def _peek(self) -> str | None:
        return self.tokens[self.index].text if self.index < len(self.tokens) else None

    def _take(self, expected: str) -> None:
        if self._peek() != expected:
            raise _InvalidError
        self.index += 1

    def parse(self) -> Expr:
        result = self._sum(0)
        if self.index != len(self.tokens) or expr_height(result) > MAX_EXPR_DEPTH:
            raise _InvalidError
        return result

    def _sum(self, depth: int) -> Expr:
        value = self._product(depth)
        while (operator := self._peek()) in ("+", "-"):
            self.index += 1
            right = self._product(depth)
            value = self._node(Bin("add" if operator == "+" else "sub", value, right))
        return value

    def _product(self, depth: int) -> Expr:
        value = self._unary(depth)
        while (operator := self._peek()) in ("*", "/"):
            self.index += 1
            right = self._unary(depth)
            value = self._node(Bin("mul" if operator == "*" else "div", value, right))
        return value

    def _unary(self, depth: int) -> Expr:
        sign = self._peek()
        if sign in ("+", "-"):
            self.index += 1
            operand = self._unary(self._nest(depth))
            return self._node(Neg(operand)) if sign == "-" else operand
        return self._power(depth)

    def _power(self, depth: int) -> Expr:
        value = self._primary(depth)
        if self._peek() == "**":
            self.index += 1
            sign = self._peek()
            if sign in ("+", "-"):
                self.index += 1
                self._nest(depth)
            if self.index == len(self.tokens):
                raise _InvalidError
            token = self.tokens[self.index]
            if token.kind != "number" or not token.text.isdecimal():
                raise _InvalidError
            self.index += 1
            exponent = self._node(Num(Fraction(int(token.text))))
            if sign == "-":
                exponent = self._node(Neg(exponent))
            value = self._node(Bin("pow", value, exponent))
        return value

    def _primary(self, depth: int) -> Expr:
        if self.index == len(self.tokens):
            raise _InvalidError
        token = self.tokens[self.index]
        self.index += 1
        if token.kind == "number":
            if "." in token.text or "e" in token.text.lower():
                float_value = float(token.text)
                if not math.isfinite(float_value):
                    raise _InvalidError
                return self._node(Num(Fraction(float_value)))
            return self._node(Num(Fraction(int(token.text))))
        if token.text == "x":
            return self._node(Var())
        if token.text in _CONSTANTS:
            return self._node(Const("pi" if token.text == "pi" else "e"))
        if token.text in _FUNCTIONS:
            self._take("(")
            argument = self._sum(self._nest(depth))
            self._take(")")
            # The lexer, not the model, chooses the name from the closed function vocabulary.
            return self._node(Fn(cast("FnName", token.text), argument))
        if token.text == "(":
            value = self._sum(self._nest(depth))
            self._take(")")
            return value
        raise _InvalidError


def _expression(text: str, index: int, limits: PysrcLimits, *, allow_x: bool) -> tuple[Expr, int]:
    tokens, end = _lex(text, index, allow_x=allow_x)
    if not tokens:
        raise _InvalidError
    return _Expression(tokens, limits).parse(), end


def _bracket_interval(text: str, start: int, limits: PysrcLimits) -> tuple[Interval, int]:
    left, index = _expression(text, start, limits, allow_x=False)
    index = _spaces(text, index)
    if index == len(text) or text[index] != ",":
        raise _InvalidError
    right, index = _expression(text, index + 1, limits, allow_x=False)
    index = _spaces(text, index)
    if index == len(text) or text[index] != "]":
        raise _InvalidError
    return Interval(left, right), index + 1


def _formula_start(text: str, index: int) -> int | None:
    if index and _word(text[index - 1]):
        return None
    if text.startswith("f(x)", index):
        end = index + 4
    elif text[index] == "y":
        end = index + 1
    else:
        return None
    end = _spaces(text, end)
    return end + 1 if end < len(text) and text[end] == "=" else None


def _bracket_start(text: str, index: int) -> int | None:
    if text[index] != "x" or (index and _word(text[index - 1])):
        return None
    end = _spaces(text, index + 1)
    if text.startswith("∈", end):
        end += 1
    elif text[end : end + 2].lower() == "in":
        end += 2
    else:
        return None
    end = _spaces(text, end)
    return end + 1 if end < len(text) and text[end] == "[" else None


def _count_start(text: str, index: int) -> int | None:
    if text[index] != "n" or (index and _word(text[index - 1])):
        return None
    end = _spaces(text, index + 1)
    return end + 1 if end < len(text) and text[end] == "=" else None


def _from_interval(text: str, index: int, limits: PysrcLimits) -> tuple[Interval, int] | None:
    if (
        (index and _word(text[index - 1]))
        or text[index : index + 4].lower() != "from"
        or text[index + 4 : index + 5] not in (" ", "\t")
    ):
        return None
    try:
        left, end = _expression(text, index + 4, limits, allow_x=False)
        next_word = _spaces(text, end)
        if (
            next_word == end
            or text[next_word : next_word + 2].lower() != "to"
            or text[next_word + 2 : next_word + 3] not in (" ", "\t")
        ):
            return None
        right, end = _expression(text, next_word + 2, limits, allow_x=False)
        if not _prose_boundary(text, end):
            return None
    except _InvalidError:
        return None
    return Interval(left, right), end


def _japanese_interval(text: str, index: int, limits: PysrcLimits) -> tuple[Interval | None, int]:
    tokens, end = _lex(text, index, allow_x=False)
    separator = _spaces(text, end)
    if not tokens or not text.startswith("から", separator):
        return None, end
    try:
        left = _Expression(tokens, limits).parse()
        right, finish = _expression(text, separator + 2, limits, allow_x=False)
    except _InvalidError:
        return None, end
    finish = _spaces(text, finish)
    if not text.startswith("まで", finish):
        return None, end
    return Interval(left, right), finish + 2


def formula_target(  # noqa: PLR0911, PLR0912 - each carrier fails closed in one linear pass
    text: str, limits: PysrcLimits = DEFAULT_LIMITS
) -> FormulaTarget | None:
    """Extract one user-authored formula and interval; any ambiguity leaves no target."""
    normalized = unicodedata.normalize("NFKC", text)
    try:
        if (
            limits.max_source_bytes < 1
            or limits.max_expr_nodes < 1
            or limits.max_bracket_depth < 1
            or len(normalized.encode("utf-8")) > limits.max_source_bytes
        ):
            return None
        formula: Expr | None = None
        interval: Interval | None = None
        samples: int | None = None
        spans: list[tuple[int, int]] = []
        japanese_scanned = 0
        for index in range(len(normalized)):
            if (start := _formula_start(normalized, index)) is not None:
                if formula is not None:
                    return None
                formula, finish = _expression(normalized, start, limits, allow_x=True)
                if not _prose_boundary(normalized, finish):
                    return None
                spans.append((index, finish))
            if (start := _bracket_start(normalized, index)) is not None:
                if interval is not None:
                    return None
                interval, finish = _bracket_interval(normalized, start, limits)
                spans.append((index, finish))
            if (start := _count_start(normalized, index)) is not None:
                if samples is not None:
                    return None
                finish = _spaces(normalized, start)
                begin = finish
                while finish < len(normalized) and "0" <= normalized[finish] <= "9":
                    finish += 1
                if finish == begin or not _prose_boundary(normalized, finish):
                    return None
                samples = int(normalized[begin:finish])
                spans.append((index, finish))
            if (found := _from_interval(normalized, index, limits)) is not None:
                if interval is not None:
                    return None
                interval, finish = found
                spans.append((index, finish))
            if index >= japanese_scanned and _start_boundary(normalized, index):
                japanese_candidate, japanese_scanned = _japanese_interval(normalized, index, limits)
                if japanese_candidate is not None:
                    if interval is not None:
                        return None
                    interval = japanese_candidate
                    spans.append((index, japanese_scanned))
        if formula is None or interval is None:
            return None
        spans.sort()
        if any(spans[index][1] > spans[index + 1][0] for index in range(len(spans) - 1)):
            return None
        grid: Grid | Interval = (
            Grid(interval.start, interval.stop, samples) if samples is not None else interval
        )
        return FormulaTarget(formula, grid)
    except (_InvalidError, UnicodeError, ValueError, OverflowError, RecursionError):
        return None
'''

_SOURCES["verifier.pysrc.certificate"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The core certificate: what was verified, in hashes and in plain words.

Stdlib-only, so this is NOT `verifier.vcert` -- that one is msgspec and belongs to the shipped
service. Where reuse conflicts with the paste-in's isolation, isolation wins.

Two disciplines the shape enforces. `checks` is all-pass BY CONSTRUCTION, mirroring v0.3's
`Literal["pass"]`: anything the verifier did not establish goes in `declared_open` and never into
`checks` as a failure. `interpretation` publishes the tier-3 gap in plain words; fidelity to what
the user meant is never claimed.
"""

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal, assert_never, cast

from verifier.pysrc.errors import PysrcCallerError
from verifier.pysrc.numeric import NUMERIC_PROFILE
from verifier.pysrc.project import same_bound
from verifier.pysrc.spec import (
    Bin,
    Const,
    CorePlotSpec,
    DatasetMark,
    DatasetPlot,
    DatasetTarget,
    DeclaredTarget,
    Expr,
    Fn,
    FormulaPlot,
    FormulaTarget,
    Grid,
    Interval,
    Labels,
    Neg,
    Num,
    Reduction,
    Var,
)
from verifier.pysrc.table import PlottedTable

__all__ = ["CERTIFICATE_VERSION", "CertifiedCheck", "CoreCertificate", "certify"]

CERTIFICATE_VERSION = "pysrc-cert-0.1"

type Provenance = Literal["artifact", "internal"]


@dataclass(frozen=True, slots=True)
class CertifiedCheck:
    """One established property. `status` has one admitted value on purpose."""

    id: str
    status: Literal["pass"]


@dataclass(frozen=True, slots=True)
class CoreCertificate:
    """Field set is exact and pinned. A new field is a claim, so it moves the pin deliberately."""

    version: str
    source_sha256: str
    spec_sha256: str
    table_sha256: str
    # G11: one member count per plotted group, aligned with the table's x, and `None` when the plot
    # is not an aggregate. The interpretation sentence carries the two TOTALS a human reads at a
    # glance; the per-group detail lives here, where a machine consumer can check it row by row.
    group_counts: tuple[int, ...] | None
    provenance: Provenance
    artifact_sha256: str | None
    numeric_profile: str
    checks: tuple[CertifiedCheck, ...]
    declared_open: tuple[str, ...]
    interpretation: str


_CHECKS = tuple(
    CertifiedCheck(check, "pass")
    for check in (
        "prescan",
        "admission",
        "projection",
        "target_binding",
        "recomputation",
        "integrity",
    )
)
_ARTIFACT_GAP = "The emitted image is not compared against this table."
_INTENT_GAP = (
    "The plotted values are the submitted program's own expression, not a target the user stated."
)
_NO_ARTIFACT = (
    "No user artifact was consumed. The plotted values come from the submitted program alone."
)
_SAMPLES_GAP = "The request states no sample count. The submitted program sets it."
_INTERVAL_GAP = (
    "The request states no x interval. "
    "The submitted program sets the interval and the sample count."
)
_SPEC_DOMAIN = b"pysrc-spec-0.1\n"
# Reduction -> the word a person reads. `min`/`max` are abbreviations a reader has to expand;
# `sum` and `mean` are already the English words for what they do.
_REDUCTION_WORDS: dict[Reduction, str] = {
    "sum": "sum",
    "mean": "mean",
    "min": "minimum",
    "max": "maximum",
}

# (first channel's axis, second channel's axis) as RENDERED, per mark.
_AXIS_LETTERS: dict[DatasetMark, tuple[str, str]] = {
    "line": ("X", "Y"),
    "scatter": ("X", "Y"),
    "bar": ("X", "Y"),
    "barh": ("Y", "X"),
}


def _expr_value(expr: Expr) -> list[object]:
    if isinstance(expr, Num):
        return ["num", expr.value.numerator, expr.value.denominator]
    if isinstance(expr, Var):
        return ["var"]
    if isinstance(expr, Const):
        return ["const", expr.name]
    if isinstance(expr, Neg):
        return ["neg", _expr_value(expr.operand)]
    if isinstance(expr, Fn):
        return ["fn", expr.name, _expr_value(expr.arg)]
    if isinstance(expr, Bin):
        return ["bin", expr.op, _expr_value(expr.left), _expr_value(expr.right)]
    assert_never(expr)  # pragma: no cover - `Expr` is a closed union


def _grid_value(grid: Grid) -> dict[str, object]:
    return {
        "samples": grid.samples,
        "start": _expr_value(grid.start),
        "stop": _expr_value(grid.stop),
    }


def _fraction_value(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


def _labels_value(labels: Labels) -> dict[str, object]:
    # The cosmetic fields are hashed like every other one. A figure size changes no plotted number,
    # but a spec digest that ignores a projected field is not a binding on that field, and the one
    # thing this digest exists to say is "the spec you read is the spec that was verified".
    figsize = labels.figsize
    return {
        "figsize": None if figsize is None else [_fraction_value(part) for part in figsize],
        "grid": labels.grid,
        "legend": labels.legend,
        "series": labels.series,
        "tick_rotation": (
            None if labels.tick_rotation is None else _fraction_value(labels.tick_rotation)
        ),
        "tight_layout": labels.tight_layout,
        "title": labels.title,
        "xlabel": labels.xlabel,
        "ylabel": labels.ylabel,
    }


def _spec_value(spec: CorePlotSpec) -> dict[str, object]:
    if isinstance(spec, FormulaPlot):
        return {
            "grid": _grid_value(spec.grid),
            "labels": _labels_value(spec.labels),
            "mark": spec.mark,
            "y": _expr_value(spec.y),
        }
    if isinstance(spec, DatasetPlot):
        return {
            "group": spec.group,
            "labels": _labels_value(spec.labels),
            "mark": spec.mark,
            "path": spec.source.path,
            "x": spec.x.name,
            "y": spec.y.name,
        }
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def _json_bytes(value: object) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return encoded.encode("utf-8") + b"\n"


def canonical_spec_bytes(spec: CorePlotSpec) -> bytes:
    """One byte encoding per projected spec, domain- and arm-tagged, stdlib-only."""
    if isinstance(spec, FormulaPlot):
        arm = b"formula\n"
    elif isinstance(spec, DatasetPlot):
        arm = b"dataset\n"
    else:
        assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union
    return _SPEC_DOMAIN + arm + _json_bytes(_spec_value(spec))


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _target_consumed(spec: CorePlotSpec, target: DeclaredTarget | None) -> bool:
    if isinstance(spec, DatasetPlot):
        return isinstance(target, DatasetTarget) and target.path == spec.source.path
    if isinstance(spec, FormulaPlot):
        if not isinstance(target, FormulaTarget) or target.y != spec.y:
            return False
        if target.grid is None:
            return True
        if isinstance(target.grid, Grid) and target.grid.samples != spec.grid.samples:
            return False
        return same_bound(spec.grid.start, target.grid.start) and same_bound(
            spec.grid.stop, target.grid.stop
        )
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _number_text(number: Num) -> str:
    if number.value.denominator == 1:
        return str(number.value.numerator)
    # Projection creates non-integral fractions only from finite source float64 values.
    return repr(float(number.value))


def _expr_text(expr: Expr) -> str:
    if isinstance(expr, Num):
        return _number_text(expr)
    if isinstance(expr, Var):
        return "x"
    if isinstance(expr, Const):
        return expr.name
    if isinstance(expr, Neg):
        return f"-({_expr_text(expr.operand)})"
    if isinstance(expr, Fn):
        return f"{expr.name}({_expr_text(expr.arg)})"
    if isinstance(expr, Bin):
        operators = {"add": "+", "sub": "-", "mul": "*", "div": "/", "pow": "**"}
        return f"({_expr_text(expr.left)} {operators[expr.op]} {_expr_text(expr.right)})"
    assert_never(expr)  # pragma: no cover - `Expr` is a closed union


def _append_labels(text: str, labels: Labels) -> str:
    sentences: list[str] = []
    if labels.xlabel is not None:
        sentences.append(f"X label: {_quote(labels.xlabel)}.")
    if labels.ylabel is not None:
        sentences.append(f"Y label: {_quote(labels.ylabel)}.")
    if labels.title is not None:
        sentences.append(f"Title: {_quote(labels.title)}.")
    return " ".join((text, *sentences))


def _dataset_text(
    spec: DatasetPlot, table: PlottedTable, group_counts: tuple[int, ...] | None
) -> str:
    # `plt.barh` draws its first positional on the VERTICAL axis and its second on the horizontal
    # one, so the axis letters swap with the mark. The sentence is a tier-3 claim about the figure
    # a person is looking at, and naming the wrong axis misdescribes exactly the mark this width
    # added. Closed on `DatasetMark`, never a default, so a fifth mark fails at the lookup.
    first, second = _AXIS_LETTERS[spec.mark]
    source = f"Chart type: {spec.mark}. The data comes from the file {_quote(spec.source.path)}."
    if spec.group is None:
        return (
            f"{source} {first} shows the column {_quote(spec.x.name)}. "
            f"{second} shows the column {_quote(spec.y.name)}. "
            f"The chart draws {len(table.x)} rows. Numbers follow the profile {NUMERIC_PROFILE}."
        )
    # G11's human half: the group count and the row count behind it, in the sentence a person
    # actually reads. Two numbers that disagree are what tells a reader rows went missing.
    # `certify` has already refused a grouped spec whose counts are absent, so the cast is that
    # guard's postcondition rather than a hope.
    counts = cast("tuple[int, ...]", group_counts)
    return (
        f"{source} {first} shows the groups of the column {_quote(spec.x.name)}. "
        f"{second} shows the {_REDUCTION_WORDS[spec.group]} of the column "
        f"{_quote(spec.y.name)} in each group. "
        f"The chart draws {len(table.x)} groups from {sum(counts)} rows. "
        f"Numbers follow the profile {NUMERIC_PROFILE}."
    )


def _interpretation(
    spec: CorePlotSpec,
    table: PlottedTable,
    group_counts: tuple[int, ...] | None,
    target: DeclaredTarget | None,
) -> str:
    if isinstance(spec, FormulaPlot):
        bound = ""
        if isinstance(target, FormulaTarget):
            if isinstance(target.grid, Grid):
                bound = "The formula, the x interval and the sample count match the request. "
            elif isinstance(target.grid, Interval):
                bound = "The formula and the x interval match the request. "
            else:
                bound = "The formula matches the request. "
        text = (
            f"Chart type: {spec.mark}. The data comes from the submitted program. "
            f"{bound}Y computes {_expr_text(spec.y)}. X runs from {_expr_text(spec.grid.start)} to "
            f"{_expr_text(spec.grid.stop)} in {spec.grid.samples} samples. Numbers follow the "
            f"profile {NUMERIC_PROFILE}."
        )
        return _append_labels(text, spec.labels)
    if isinstance(spec, DatasetPlot):
        return _append_labels(_dataset_text(spec, table, group_counts), spec.labels)
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is a closed union


def certify(
    spec: CorePlotSpec,
    table: PlottedTable,
    source: bytes,
    target: DeclaredTarget | None,
    group_counts: tuple[int, ...] | None,
) -> CoreCertificate:
    """Bind the submitted bytes, projected spec and recomputed table into one statement.

    `group_counts` is REQUIRED to agree with the spec: G11 publishes per-group counts beside every
    aggregate, and a branch that reads a grouped spec with absent counts as ungrouped would ship a
    G11-less certificate for an aggregate figure instead of failing. That is a caller defect, not
    an input fault, so it raises rather than refusing.
    """
    grouped = isinstance(spec, DatasetPlot) and spec.group is not None
    if grouped is not (group_counts is not None):
        message = (
            f"group counts disagree with the spec: grouped={grouped}, "
            f"counts={'absent' if group_counts is None else 'present'}"
        )
        raise PysrcCallerError(message)
    consumed = _target_consumed(spec, target)
    provenance: Provenance = "artifact" if consumed else "internal"
    declared_open = [_ARTIFACT_GAP]
    if isinstance(spec, FormulaPlot):
        if not isinstance(target, FormulaTarget):
            declared_open.extend((_INTENT_GAP, _NO_ARTIFACT))
        elif isinstance(target.grid, Interval):
            declared_open.append(_SAMPLES_GAP)
        elif target.grid is None:
            declared_open.append(_INTERVAL_GAP)
    return CoreCertificate(
        version=CERTIFICATE_VERSION,
        source_sha256=_digest(source),
        spec_sha256=_digest(canonical_spec_bytes(spec)),
        table_sha256=_digest(table.canonical_bytes()),
        group_counts=group_counts,
        provenance=provenance,
        artifact_sha256=None,
        numeric_profile=NUMERIC_PROFILE,
        checks=_CHECKS,
        declared_open=tuple(declared_open),
        interpretation=_interpretation(spec, table, group_counts, target),
    )
'''

_SOURCES["verifier.pysrc.csvread"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The safe CSV profile: what the verifier parses with stdlib `csv` + `float`, and what it refuses.

The verifier may not depend on pandas, but the SANDBOX calls plain `pd.read_csv`, whose default
float parser is not correctly rounded. Measured against stdlib `float` over 1,000,000 adversarial
cells, 326,834 disagree, 12,053 of them by 2 to 7,262 ulp, and no significant-digit cap repairs it.
So the profile RESTRICTS rather than reimplementing `xstrtod`: it admits only a region measured at
0 bit mismatches out of 4,000,000 against the target sandbox, and refuses the exact complement.

Two admitted-region clauses are about the RENDERER, not the parser: Pyodide's `plt.bar` keeps
integer heights as `int32` and RAISES outside signed 32 bits, and matplotlib bar erases the sign of
`-0.0`. Both are excluded here so the drawn figure cannot differ from the recomputed table.

Full six-clause profile + its evidence = `.agent/archive/contracts/m13u5.md`.
"""

import csv
import io
import math
import re
from dataclasses import dataclass
from typing import Literal, NoReturn, assert_never

from verifier.pysrc.aggregate import Aggregated, aggregate_series, column_dtype
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import PysrcLimits
from verifier.pysrc.spec import DatasetMark, DatasetPlot
from verifier.pysrc.table import CellValue

__all__ = ["NA_SPELLINGS", "DatasetSeries", "read_columns"]

# Every default NA spelling pandas recognises, measured on the target build. A cell matching one of
# these -- quoted or plain -- refuses rather than becoming a null: the verifier has no null, and
# that absence is what makes G8's row coverage true by construction. Coverage, not point-count
# equality: an aggregate collapses its rows into one point per group and G11 publishes the counts.
NA_SPELLINGS: frozenset[str] = frozenset(
    {
        "",
        "#N/A",
        "#N/A N/A",
        "#NA",
        "-1.#IND",
        "-1.#QNAN",
        "-NaN",
        "-nan",
        "1.#IND",
        "1.#QNAN",
        "<NA>",
        "N/A",
        "NA",
        "NULL",
        "NaN",
        "None",
        "n/a",
        "nan",
        "null",
    }
)

_UTF8_BOM = b"\xef\xbb\xbf"
_CR = ord("\r")
_LF = ord("\n")
_INT32_MIN = -(2**31)
_INT32_MAX = 2**31 - 1
# Float64 heights `plt.bar` draws bit-exactly, measured on both pinned Pyodide builds and the
# installed bundle (Q12: 0/2,364 changed). A float64 CELL never reaches it -- the 15-digit cap keeps
# every cell below 10**15 -- so it binds a float64 REDUCTION alone.
_FLOAT_HEIGHT_MAX = 2**53
# The marks whose magnitude is drawn as a LENGTH, which is the Pyodide integer path C10 bounds.
_INT_HEIGHT_MARKS = frozenset({"bar", "barh"})
_MAX_SIGNIFICANT_DIGITS = 15
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?")
_BOOLEAN_TEXT = frozenset({"true", "false"})
type _ColumnClass = Literal["numeric", "categorical", "mixed"]
type _RawTable = tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


def _check_record_endings(content: bytes) -> None:
    for index, byte in enumerate(content):
        if byte == _CR and (index + 1 == len(content) or content[index + 1] != _LF):
            _refuse("csv_not_parsable")


def _check_cell_sizes(row: list[str], limit: int) -> None:
    if any(len(cell.encode("utf-8")) > limit for cell in row):
        _refuse("csv_too_large")


def header_names(content: bytes, limits: PysrcLimits) -> tuple[str, ...] | None:
    """The first record as column names; None wherever `read_columns` refuses by the header.

    That is every whole-file gate (size, BOM, NUL, record endings, UTF-8) and every header-record
    check (`_check_header`, and its work charge against a fresh meter -- the header is the first
    charge `read_columns` makes). Request anchoring (Q8) reads the header ahead of recomputation,
    so a file it cannot read anchors nothing and recomputation's own refusal still names the fault;
    a malformed LATER row is recomputation's to refuse, after binding.
    """
    try:
        if (
            len(content) > limits.max_csv_bytes
            or content.startswith(_UTF8_BOM)
            or b"\x00" in content
        ):
            return None
        _check_record_endings(content)
        text = content.decode("utf-8")
        header = next(csv.reader(io.StringIO(text, newline=""), strict=True))
        WorkBudget(limits.max_work).charge(_record_work(header))
        _check_header(header, limits)
    except (
        PysrcRefusalError,
        WorkBudgetExceededError,
        UnicodeDecodeError,
        StopIteration,
        csv.Error,
    ):
        return None
    return tuple(header)


def _record_work(row: list[str]) -> int:
    return sum(1 + len(cell) // 32 for cell in row)


def _check_header(header: list[str], limits: PysrcLimits) -> None:
    _check_cell_sizes(header, limits.max_csv_cell_bytes)
    if len(header) > limits.max_csv_columns:
        _refuse("csv_too_large")
    if not header or any(not cell for cell in header) or len(set(header)) != len(header):
        _refuse("csv_not_parsable")


def _read_csv(content: bytes, limits: PysrcLimits, budget: WorkBudget) -> _RawTable:
    if len(content) > limits.max_csv_bytes:
        _refuse("csv_too_large")
    if content.startswith(_UTF8_BOM) or b"\x00" in content:
        _refuse("csv_not_parsable")
    _check_record_endings(content)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        _refuse("csv_not_parsable", exc)

    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=",",
        quotechar='"',
        doublequote=True,
        escapechar=None,
        skipinitialspace=False,
        strict=True,
    )
    try:
        header_row = next(reader)
        budget.charge(_record_work(header_row))
        _check_header(header_row, limits)

        rows: list[tuple[str, ...]] = []
        for row_number, row in enumerate(reader, start=1):
            if row_number > limits.max_csv_rows:
                _refuse("csv_too_large")
            if row_number > limits.max_table_rows:
                _refuse("work_budget_exceeded")
            _check_cell_sizes(row, limits.max_csv_cell_bytes)
            if len(row) != len(header_row):
                _refuse("csv_not_parsable")
            budget.charge(_record_work(row))
            rows.append(tuple(row))
    except StopIteration:
        _refuse("csv_not_parsable")
    except csv.Error as exc:
        _refuse("csv_not_parsable", exc)

    if not rows:
        _refuse("csv_not_parsable")
    return tuple(header_row), tuple(rows)


def _column_indices(header: tuple[str, ...], plot: DatasetPlot) -> tuple[int, int]:
    try:
        return header.index(plot.x.name), header.index(plot.y.name)
    except ValueError as exc:
        _refuse("column_not_present", exc)


def _significant_digits(text: str) -> int:
    digits = text.lstrip("-").replace(".", "").lstrip("0")
    return len(digits) if digits else 1


def _profile_float(text: str, value: float, *, integer_column: bool) -> float:
    if (
        _NUMBER.fullmatch(text) is None
        or _significant_digits(text) > _MAX_SIGNIFICANT_DIGITS
        or not math.isfinite(value)
        or (integer_column and not _INT32_MIN <= value <= _INT32_MAX)
        or (value == 0.0 and math.copysign(1.0, value) < 0.0)
    ):
        _refuse("value_not_in_profile")
    # The range and signed-zero clauses bind the renderer, not parsing. Pyodide's integer bar
    # raises outside int32 -- an INTEGER column alone reaches that path; a column pandas infers
    # float64 (any token with a decimal point) draws through the float path, measured bit-exact to
    # 2**53 (Q12) -- while matplotlib bar turns -0.0 into +0.0; either would make the emitted mark
    # differ from this recomputation even though pandas parsed the token correctly.
    return value


def _check_selected_text(text: str) -> None:
    if text in NA_SPELLINGS or text.casefold() in _BOOLEAN_TEXT:
        # pandas infers bool and matplotlib renders it as 1/0; the verifier has no bool cell type.
        _refuse("value_not_in_profile")


def _classify_column(texts: tuple[str, ...]) -> _ColumnClass:
    parsed = 0
    for text in texts:
        try:
            float(text)
        except ValueError:
            continue
        parsed += 1
    if parsed == len(texts):
        return "numeric"
    if parsed == 0:
        return "categorical"
    return "mixed"


def _numeric_value(text: str, integer_column: bool) -> float:  # noqa: FBT001 - the one seam
    try:
        value = float(text)
    except ValueError as exc:
        _refuse("value_not_in_profile", exc)
    return _profile_float(text, value, integer_column=integer_column)


def _numeric_values(texts: tuple[str, ...]) -> tuple[float, ...]:
    """A numeric column's cells; its inferred dtype picks the range clause (user ruling Q12)."""
    integer_column = column_dtype(texts) == "int64"
    return tuple(_numeric_value(text, integer_column) for text in texts)


def _x_values(
    texts: tuple[str, ...], mark: DatasetMark, *, grouped: bool = False
) -> tuple[CellValue, ...]:
    """The x column as cells. `grouped` reads it as a GROUP KEY rather than as an axis.

    That is the whole difference, and it is one clause: a raw x column refuses `mixed` because half
    a numeric axis cannot be drawn, while a key column has no axis until it is reduced and pandas
    groups `['2', 'a', '10', '2']` perfectly well -- measured, as the text keys `['10', '2', 'a']`.
    `scatter` is unmoved either way, since its x IS a coordinate however it was produced.
    """
    column_class = _classify_column(texts)
    match mark:
        case "scatter":
            if column_class == "categorical":
                _refuse("column_not_numeric")
            return _numeric_values(texts)
        case "line" | "bar" | "barh":
            if column_class == "mixed" and not grouped:
                _refuse("column_not_numeric")
            if column_class == "numeric":
                return _numeric_values(texts)
            return texts
        case _ as unreachable:  # pragma: no cover - `DatasetMark` is closed
            assert_never(unreachable)


def _y_values(texts: tuple[str, ...]) -> tuple[float, ...]:
    if _classify_column(texts) == "categorical":
        _refuse("column_not_numeric")
    return _numeric_values(texts)


@dataclass(frozen=True, kw_only=True, slots=True)
class DatasetSeries:
    """The plotted columns, plus the per-group evidence G11 publishes when there is any.

    `group_counts` is `None` for an ungrouped plot and never an empty tuple: "this figure draws no
    groups" and "this figure draws zero groups" are different statements, and the certificate says
    only the first one.
    """

    x: tuple[CellValue, ...]
    y: tuple[float, ...]
    group_counts: tuple[int, ...] | None


def _check_renderer_bound(reduced: Aggregated, mark: DatasetMark) -> None:
    """C10's int32 clause, re-asserted on the REDUCTION rather than on the cells it came from.

    A sum of in-profile cells leaves the range easily. Measured on both target Pyodide builds:
    `bar` and `barh` raise `OverflowError: Python int too large to convert to C long` on the int64
    heights `[4294967294, -4294967296]`, while in-range controls render. Dtype retention is what
    keeps this narrow -- an integer `mean` is float64 and never reaches the renderer's integer
    branch, and `plot`/`scatter` preserve their float64 bits either way. A float64 reduction under
    `bar`/`barh` stays within 2**53, the span measured bit-exact through the float path (Q12):
    float64 cells sum past it, and nothing was measured beyond.
    """
    if mark not in _INT_HEIGHT_MARKS:
        return
    low, high = (
        (_INT32_MIN, _INT32_MAX)
        if reduced.dtype == "int64"
        else (-_FLOAT_HEIGHT_MAX, _FLOAT_HEIGHT_MAX)
    )
    if any(not low <= value <= high for value in reduced.values):
        _refuse("value_not_in_profile")


def read_columns(
    content: bytes,
    plot: DatasetPlot,
    limits: PysrcLimits,
    budget: WorkBudget,
) -> DatasetSeries:
    """The two selected columns of the user's CSV, in file order, or a refusal.

    Takes the whole projected `DatasetPlot` rather than loose names: the column names and the mark
    all come from one projection, and splitting them into separate arguments invites a caller to
    pair a column with the wrong mark.

    Every ceiling is checked BEFORE the work it bounds: a row cap read after materializing the rows
    buys nothing. Each read cell costs `1 + len(cell_text) // 32`; emitted cells stay flat.

    Both selected columns are swept for inadmissible text before classification. stdlib `float`
    success decides numeric, categorical or mixed. The mark decides which class its role admits.

    A projected `group` reduces the pair instead of plotting it: x becomes the sorted group keys
    and y their reduced values. Every cell still passes the profile FIRST, so aggregation reduces
    admitted numbers only.
    """
    header, rows = _read_csv(content, limits, budget)
    x_index, y_index = _column_indices(header, plot)
    selected = tuple((row[x_index], row[y_index]) for row in rows)
    for x_text, y_text in selected:
        _check_selected_text(x_text)
        _check_selected_text(y_text)
    x_texts = tuple(x_text for x_text, _ in selected)
    y_texts = tuple(y_text for _, y_text in selected)
    if plot.group is not None:
        reduced = aggregate_series(
            _x_values(x_texts, plot.mark, grouped=True),
            y_texts,
            _y_values(y_texts),
            plot.group,
            budget=budget,
            max_groups=limits.max_groups,
        )
        _check_renderer_bound(reduced, plot.mark)
        return DatasetSeries(x=reduced.keys, y=reduced.values, group_counts=reduced.counts)
    return DatasetSeries(x=_x_values(x_texts, plot.mark), y=_y_values(y_texts), group_counts=None)
'''

_SOURCES["verifier.pysrc.verify"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The public entry: submitted source in, verdict out.

Seven stages, in order, each refusing before the next runs: prescan -> admit -> project -> bind
target -> recompute -> integrity -> certify. Ordering is a claim, not an implementation detail -- a
later stage that runs after an earlier refusal would be doing work on bytes already rejected, and
a stage's refusal code would stop identifying which check caught what.

A refusal is RETURNED, never raised. A `PysrcCallerError` still propagates: an operator who
configured the verifier wrongly has no verdict about the source, and collapsing the two would let
a misconfiguration read as a refused program.

The entry is PURE. No filesystem, no network, no clock, no RNG, no environment. The user's CSV
arrives as bytes inside `declared_target`, so the core never opens a path -- which is also what
lets M14 inline this package into a sandbox that has neither.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from typing import NoReturn, assert_never

from verifier.pysrc.admit import parse_admitted
from verifier.pysrc.budget import WorkBudget, WorkBudgetExceededError
from verifier.pysrc.certificate import CoreCertificate, certify
from verifier.pysrc.csvread import header_names, read_columns
from verifier.pysrc.errors import PysrcRefusalError, RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits, validate_limits
from verifier.pysrc.numeric import evaluate_expr, materialize_grid
from verifier.pysrc.prescan import prescan
from verifier.pysrc.project import project, same_bound
from verifier.pysrc.spec import (
    Bin,
    Const,
    CorePlotSpec,
    DatasetPlot,
    DatasetTarget,
    DeclaredTarget,
    Expr,
    Fn,
    FormulaPlot,
    FormulaTarget,
    Grid,
    Interval,
    Neg,
    Num,
    Reduction,
    Var,
)
from verifier.pysrc.table import CellValue, PlottedTable

__all__ = ["Refused", "Verdict", "Verified", "verify_python_source"]


@dataclass(frozen=True, slots=True)
class Verified:
    """Carries the projection, the recomputation and the certificate -- and nothing else.

    Deliberately holds NO byte derived from the source beyond the certificate's `source_sha256`:
    no line number, no AST node, no source text. The one place this project must never let the
    model write is the operator surface, and a verdict is on that surface.
    """

    spec: CorePlotSpec
    table: PlottedTable
    certificate: CoreCertificate


@dataclass(frozen=True, slots=True)
class Refused:
    """The closed code IS the whole verdict. There is no free text and no echoed input."""

    code: RefusalCode


@dataclass(frozen=True, slots=True)
class Recomputation:
    """The plotted table, plus the per-group counts G11 publishes when the plot is an aggregate.

    Kept OUT of `PlottedTable` deliberately: the table is what the figure draws and what every
    comparison surface compares against, while the counts are evidence about how those rows were
    produced. A field on the comparison surface that no comparison reads is how a claim rots.
    """

    table: PlottedTable
    group_counts: tuple[int, ...] | None


type Verdict = Verified | Refused


def _refuse(code: RefusalCode, cause: BaseException | None = None) -> NoReturn:
    raise PysrcRefusalError(code) from cause


# --- request anchoring (Q8) ----------------------------------------------------------------------
# Which CSV columns a user's request names: lexical term anchoring (user ruling Q8).
#
# A refinement over the three verification tiers, never a prerequisite: a request that names no
# column anchors nothing, and the verdict proceeds exactly as before. Matching is lexical only --
# no synonyms, no translation -- so a request names a column only by spelling its header; `売上`
# never names `revenue`, while a Japanese request that writes `revenue` does.
#
# Both sides fold through NFKC (full-width forms become ASCII) and `casefold`, then split into
# words at every non-word character, `_` included, and wherever ASCII meets another script: so
# `unit_price` reads as `unit price`, and `regionごとのrevenue` names both columns. An ASCII header
# matches a request word sequence exactly; a Japanese one matches inside the request's words, since
# Japanese text carries no spaces between words. Two characters already make a Japanese word
# (`売上`), while an ASCII name needs three (`x`, `id` are ordinary request words). A one-word name
# of at least `_FUZZY_MIN` characters also matches a request span within Levenshtein distance 1: a
# word for ASCII, a stretch of near length for Japanese. A span close to TWO names, or a name two
# headers fold to, is a tie and is refused: the request does not say which column it means.
_FUZZY_MIN = 5
_ASCII_ANCHOR_MIN = 3
_OTHER_ANCHOR_MIN = 2
_WORD = re.compile(r"[a-z0-9]+|[^\Wa-z0-9_]+")


class _AmbiguousTermError(ValueError):
    """One request word sits within edit distance 1 of two different headers."""


def _words(text: str) -> str:
    """`text` as its folded words, one space apart."""
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", text).casefold()))


def _within_one(left: str, right: str) -> bool:
    """Levenshtein distance at most 1, in one pass."""
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            tail = index + 1 if len(left) == len(right) else index
            return left[tail:] == right[index + 1 :]
    return True


def _near_names(rest: str, keys: list[str]) -> list[set[str]]:
    """The names within one edit of each place in the request, overlapping stretches merged.

    A stretch is a whole word for an ASCII name, and a substring one character shorter, as long or
    longer for a Japanese one. Overlapping stretches are one place in the request, so a place within
    one edit of two names is a tie even where no single stretch fits both (`収張期血圧`).
    """
    runs = [run for run in rest.split() if run != "\0"]
    hits: list[tuple[int, int, int, str]] = []
    for key in keys:
        for index, run in enumerate(runs):
            if run.isascii() != key.isascii():
                continue
            windows = (
                [(0, len(run))]
                if key.isascii()
                else [
                    (start, start + width)
                    for width in (len(key) - 1, len(key), len(key) + 1)
                    for start in range(len(run) - width + 1)
                ]
            )
            hits += [(index, s, e, key) for s, e in windows if _within_one(run[s:e], key)]
    places: list[set[str]] = []
    place_run, place_end = -1, 0
    for index, start, end, key in sorted(hits):
        if index != place_run or start >= place_end:
            places.append(set())
            place_run, place_end = index, end
        places[-1].add(key)
        place_end = max(place_end, end)
    return places


def _named_columns(
    text: str, header: tuple[str, ...], *, ignore_ties: bool = False
) -> frozenset[str]:
    """The header names `text` names; a tie raises `_AmbiguousTermError`, or names nothing."""
    by_key: dict[str, list[str]] = {}
    for column in header:
        by_key.setdefault(_words(column), []).append(column)
    rest = f" {_words(text)} "
    named: set[str] = set()
    # Exact names first, longest first, each consuming its span: `unit price` never also names
    # `price`, and `収縮期血圧値` never also names `収縮期血圧`.
    for key in sorted(by_key, key=len, reverse=True):
        needle = f" {key} " if key.isascii() else key
        floor = _ASCII_ANCHOR_MIN if key.isascii() else _OTHER_ANCHOR_MIN
        if len(key) >= floor and needle in rest:
            named.add(key)
            while needle in rest:  # adjacent occurrences share a space; one pass skips every second
                rest = rest.replace(needle, " \0 ")
    # Then one edit, over what exact names left, against every one-word name of 5+ characters.
    near = _near_names(rest, [key for key in by_key if " " not in key and len(key) >= _FUZZY_MIN])
    named |= {key for keys in near if len(keys) == 1 for key in keys}
    # A tie: one place in the request within one edit of two names, or one name two headers fold to.
    tied = [sorted(keys) for keys in near if len(keys) > 1]
    tied += [[key] for key in named if len(by_key[key]) > 1]
    if tied and not ignore_ties:
        message = f"request places {sorted(tied)} each fit more than one header"
        raise _AmbiguousTermError(message)
    return frozenset(by_key[key][0] for key in named if len(by_key[key]) == 1)


def _check_anchoring(spec: DatasetPlot, request: str, content: bytes, limits: PysrcLimits) -> None:
    """Q8: refuse a substitution -- the program drops a column the request names AND plots one it
    never names (`revenue by region`, drawn over `month`).

    Either half alone is no substitution: a request naming only the measure (`chart revenue`)
    leaves the x column to the program, and a request naming three columns lets a two-column chart
    pick two of them.

    Anchoring is a refinement: an unreadable header, a plotted column absent from it (recompute's
    own refusals) or a request naming no column leaves the verdict to the checks that follow.
    """
    header = header_names(content, limits)
    plotted = {spec.x.name, spec.y.name}
    if header is None or not plotted <= set(header):
        return
    try:
        named = _named_columns(request, header)
    except _AmbiguousTermError as exc:
        _refuse("column_not_requested", exc)
    if named - plotted and plotted - named:
        _refuse("column_not_requested")


# --- label consistency (G10, Q16) ----------------------------------------------------------------
# A label is the figure's own claim about what it shows, and G10 checks that claim against the
# projection with the request-anchoring matcher above. It refuses a POSITIVE mismatch alone: a
# title, axis label or legend label naming a CSV column the chart does not draw, or -- over a
# reduction -- the summary word of a different reduction (`Total` over a mean). A label naming
# nothing checkable passes; a word tied between two headers names nothing. Without a reduction a
# summary word goes unread, since a raw column may itself hold totals or averages; and a summary
# word that is also a word of some header (`total_revenue`) names that column, never a summary.
# ASCII summary words match whole words; Japanese ones match inside the label's words.
_SUMMARY_WORDS: dict[str, Reduction | None] = {
    "sum": "sum",
    "sums": "sum",
    "summed": "sum",
    "total": "sum",
    "totals": "sum",
    "mean": "mean",
    "means": "mean",
    "average": "mean",
    "averages": "mean",
    "avg": "mean",
    "min": "min",
    "minimum": "min",
    "max": "max",
    "maximum": "max",
    # A summary no admitted reduction computes: naming it is a mismatch under every reduction.
    "median": None,
    "合計": "sum",
    "総計": "sum",
    "平均": "mean",
    "最小": "min",
    "最大": "max",
    "中央値": None,
}


def _summaries(text: str, header: tuple[str, ...]) -> set[Reduction | None]:
    """The reductions `text` names by a summary word no header uses."""
    joined = _words(text)
    words = set(joined.split())
    header_text = " ".join(_words(column) for column in header)
    header_words = set(header_text.split())
    found: set[Reduction | None] = set()
    for word, reduction in _SUMMARY_WORDS.items():
        if word.isascii():
            if word in words and word not in header_words:
                found.add(reduction)
        elif word in joined and word not in header_text:
            found.add(reduction)
    return found


def _check_labels(spec: DatasetPlot, header: tuple[str, ...]) -> None:
    drawn = {spec.x.name, spec.y.name}
    labels = spec.labels
    for text in (labels.title, labels.xlabel, labels.ylabel, labels.series):
        if text is None:
            continue
        if _named_columns(text, header, ignore_ties=True) - drawn:
            _refuse("label_not_consistent")
        if spec.group is not None and _summaries(text, header) - {spec.group}:
            _refuse("label_not_consistent")


def bind_target(
    spec: CorePlotSpec, target: DeclaredTarget | None, limits: PysrcLimits = DEFAULT_LIMITS
) -> DeclaredTarget | None:
    """Check the submitted program against the artifact the USER supplied.

    One refusal code, `target_mismatch`, covers both arms' artifact comparison: the fault shape is
    "this program is not about your artifact", and which artifact is evident from the program.
    The dataset arm's path comparison is
    byte-for-byte -- no normalization, no `Path` resolution, no case folding -- because normalizing
    would let two different files answer to one name.
    """
    if isinstance(spec, DatasetPlot):
        if not isinstance(target, DatasetTarget):
            _refuse("source_not_supplied")
        if spec.source.path != target.path:
            _refuse("target_mismatch")
        if target.request is not None:
            _check_anchoring(spec, target.request, target.content, limits)
        return target
    if isinstance(spec, FormulaPlot):
        if isinstance(target, FormulaTarget):
            if spec.y != target.y:
                _refuse("target_mismatch")
            grid = target.grid
            if isinstance(grid, Grid) and spec.grid.samples != grid.samples:
                _refuse("target_mismatch")
            if isinstance(grid, Grid | Interval) and not (
                same_bound(spec.grid.start, grid.start) and same_bound(spec.grid.stop, grid.stop)
            ):
                _refuse("target_mismatch")
            return target
        if target is None:
            return None
        if isinstance(target, DatasetTarget):
            _refuse("target_mismatch")
        assert_never(target)  # pragma: no cover - `DeclaredTarget` is closed
    assert_never(spec)  # pragma: no cover - `CorePlotSpec` is closed


def _check_expr_size(expr: Expr, limit: int) -> None:
    pending = [expr]
    count = 0
    while pending:
        node = pending.pop()
        count += 1
        if count > limit:
            _refuse("work_budget_exceeded")
        if isinstance(node, Bin):
            pending.extend((node.right, node.left))
        elif isinstance(node, Neg):
            pending.append(node.operand)
        elif isinstance(node, Fn):
            pending.append(node.arg)
        elif isinstance(node, (Num, Var, Const)):
            continue
        else:  # pragma: no cover - `Expr` is closed
            assert_never(node)


def _finish_table(
    x: tuple[CellValue, ...],
    y: tuple[float, ...],
    budget: WorkBudget,
) -> PlottedTable:
    if any(not math.isfinite(value) for value in x if isinstance(value, float)) or any(
        not math.isfinite(value) for value in y
    ):
        _refuse("value_not_finite")
    budget.charge(len(x) + len(y))
    return PlottedTable(x=x, y=y)


def _formula_table(spec: FormulaPlot, limits: PysrcLimits, budget: WorkBudget) -> PlottedTable:
    if spec.grid.samples > limits.max_table_rows:
        _refuse("work_budget_exceeded")
    for expr in (spec.grid.start, spec.grid.stop, spec.y):
        _check_expr_size(expr, limits.max_expr_nodes)
    x = materialize_grid(spec.grid, budget)
    y = tuple(evaluate_expr(spec.y, sample, budget) for sample in x)
    return _finish_table(x, y, budget)


def _dataset_table(
    spec: DatasetPlot,
    target: DeclaredTarget | None,
    limits: PysrcLimits,
    budget: WorkBudget,
) -> Recomputation:
    if not isinstance(target, DatasetTarget):  # pragma: no cover - binding closes it
        _refuse("source_not_supplied")
    series = read_columns(target.content, spec, limits, budget)
    return Recomputation(
        table=_finish_table(series.x, series.y, budget),
        group_counts=series.group_counts,
    )


def recompute(
    spec: CorePlotSpec,
    target: DeclaredTarget | None,
    limits: PysrcLimits,
) -> Recomputation:
    """Every plotted number, derived from the source rather than read from the program."""
    validate_limits(limits)
    budget = WorkBudget(limits.max_work)
    try:
        if isinstance(spec, FormulaPlot):
            return Recomputation(table=_formula_table(spec, limits, budget), group_counts=None)
        if isinstance(spec, DatasetPlot):
            return _dataset_table(spec, target, limits, budget)
        assert_never(spec)  # pragma: no cover - `CorePlotSpec` is closed
    except WorkBudgetExceededError as exc:
        _refuse("work_budget_exceeded", exc)


def _check_line_order(x: tuple[CellValue, ...]) -> None:
    text = tuple(value for value in x if isinstance(value, str))
    if text:
        if len(text) != len(x):  # pragma: no cover - recomputation emits one cell class
            _refuse("x_not_ordered")
        if len(set(text)) != len(text):
            _refuse("category_not_unique")
        return
    numeric = tuple(value for value in x if isinstance(value, float))
    if len(numeric) != len(x) or any(
        numeric[index] > numeric[index + 1] for index in range(len(numeric) - 1)
    ):
        _refuse("x_not_ordered")


def _formula_integrity(spec: FormulaPlot, table: PlottedTable) -> None:
    match spec.mark:
        case "line":
            _check_line_order(table.x)
        case "scatter":
            return
        case _ as unreachable:  # pragma: no cover - the mark union is closed
            assert_never(unreachable)


def _dataset_integrity(spec: DatasetPlot, table: PlottedTable, header: tuple[str, ...]) -> None:
    match spec.mark:
        case "bar" | "barh":
            categories = tuple(value for value in table.x if isinstance(value, str))
            if len(categories) == len(table.x) and len(set(categories)) != len(categories):
                _refuse("category_not_unique")
        case "line":
            _check_line_order(table.x)
        case "scatter":
            pass
        case _ as unreachable:  # pragma: no cover - the mark union is closed
            assert_never(unreachable)
    _check_labels(spec, header)


def check_integrity(spec: CorePlotSpec, table: PlottedTable, header: tuple[str, ...] = ()) -> None:
    """The G-rules that become decidable only once the table exists. Raises, or returns.

    `header` = the dataset's column names, which G10 matches labels against; empty for a formula.
    """
    if isinstance(spec, FormulaPlot):
        _formula_integrity(spec, table)
    elif isinstance(spec, DatasetPlot):
        _dataset_integrity(spec, table, header)
    else:  # pragma: no cover - `CorePlotSpec` is closed
        assert_never(spec)


def _header(target: DeclaredTarget | None, limits: PysrcLimits) -> tuple[str, ...]:
    # Recomputation already read this header, so `None` (unreadable) cannot reach here; `()`
    # would name nothing.
    if isinstance(target, DatasetTarget):
        return header_names(target.content, limits) or ()
    return ()


def verify_python_source(
    source: str,
    *,
    declared_target: DeclaredTarget | None = None,
    limits: PysrcLimits = DEFAULT_LIMITS,
) -> Verdict:
    """Verify model-authored Python that draws one chart.

    Total over the admitted subset: every admitted program either verifies or refuses with a closed
    code. `source` is `str` because that is what an LLM completion is; it is encoded once here, and
    a lone surrogate -- which no UTF-8 encoder accepts -- refuses like any other non-UTF-8 input
    rather than escaping as a `UnicodeEncodeError`.
    """
    try:
        try:
            source_bytes = source.encode("utf-8")
        except UnicodeEncodeError as exc:
            _refuse("source_not_utf8", exc)
        text = prescan(source_bytes, limits)
        tree = parse_admitted(text)
        spec = project(tree, limits)
        bound_target = bind_target(spec, declared_target, limits)
        recomputation = recompute(spec, bound_target, limits)
        table = recomputation.table
        check_integrity(spec, table, _header(bound_target, limits))
        certificate = certify(spec, table, source_bytes, bound_target, recomputation.group_counts)
        return Verified(spec=spec, table=table, certificate=certificate)
    except PysrcRefusalError as exc:
        return Refused(code=exc.code)
'''

_SOURCES["verifier.pysrc"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Portable verification core for `pysrc-0.1` (model-authored Python).

Stdlib-only and importing no `verifier` sibling on purpose: M14 inlines this package into a
single file an admin pastes into an Open WebUI instance that has no outside network access, so a
dependency here becomes a dependency there. Where reuse of the shipped service code conflicts with
that isolation, isolation wins (`.claude/rules/pysrc.md`).

`verify_python_source` is the ONLY entry a consumer calls; everything else exported here is a
value it returns or a policy it accepts. The stage functions stay reachable by module path for
ordering tests, but they are not part of this surface.
"""

from verifier.pysrc.certificate import (
    CertifiedCheck as CertifiedCheck,
)
from verifier.pysrc.certificate import (
    CoreCertificate as CoreCertificate,
)
from verifier.pysrc.errors import (
    PysrcCallerError as PysrcCallerError,
)
from verifier.pysrc.errors import (
    PysrcRefusalError as PysrcRefusalError,
)
from verifier.pysrc.errors import (
    RefusalCode as RefusalCode,
)
from verifier.pysrc.limits import DEFAULT_LIMITS as DEFAULT_LIMITS
from verifier.pysrc.limits import PysrcLimits as PysrcLimits
from verifier.pysrc.spec import DatasetTarget as DatasetTarget
from verifier.pysrc.spec import DeclaredTarget as DeclaredTarget
from verifier.pysrc.spec import FormulaTarget as FormulaTarget
from verifier.pysrc.table import CellValue as CellValue
from verifier.pysrc.table import PlottedTable as PlottedTable
from verifier.pysrc.verify import Refused, Verdict, Verified, verify_python_source

__all__ = ["Refused", "Verdict", "Verified", "verify_python_source"]
'''

_SOURCES["webui.paste_in.selection"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""One candidate order and one verdict selection shared by tool and outlet.

Only a target mismatch means a later user-owned artifact might answer the same program. Every
other refusal is final. The formula target comes from the user's request, after attached files.
"""

from verifier.pysrc.request import formula_target
from verifier.pysrc.spec import DatasetTarget, FormulaTarget
from verifier.pysrc.verify import Refused, Verdict, verify_python_source
from webui.paste_in.owui_files import UploadedFile

_TARGET_MISMATCH = "target_mismatch"


def first_verdict(
    program: str, attachments: tuple[UploadedFile, ...], request_text: str | None
) -> tuple[Verdict | None, UploadedFile | None]:
    """Return the first final verdict and the attachment it consumed, if any."""
    formula = formula_target(request_text) if request_text is not None else None
    candidates: tuple[tuple[DatasetTarget | FormulaTarget, UploadedFile | None], ...] = tuple(
        (DatasetTarget(path=file.path, content=file.content, request=request_text), file)
        for file in attachments
    ) + (((formula, None),) if formula is not None else ())
    outcome: Verdict | None = None
    consumed: UploadedFile | None = None
    for candidate, consumed in candidates:
        outcome = verify_python_source(program, declared_target=candidate)
        if not (isinstance(outcome, Refused) and outcome.code == _TARGET_MISMATCH):
            return outcome, consumed
    return outcome, consumed
'''

_SOURCES["webui.paste_in.tool"] = r'''
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The one model-visible operation: a program in, a fixed string out.

Transport, never authority. The method hands the model's exact bytes and the user's exact uploaded
bytes to `verify_python_source` and reports what that returns. It re-parses nothing, normalizes
nothing and decides nothing -- a second opinion here would be a pass/fail boundary outside the
verifier, which ruling 5 forbids.

Target selection is the one choice it makes, and it moves no boundary because every candidate is a
user artifact and the core decides each one. Owned attachments are tried in chat order; the formula
target parsed from the user's own request follows them. The first verdict other than
a `target_mismatch` wins. No program byte or assistant message supplies the formula target.

`Tools` is Open WebUI's fixed entry name; it instantiates the class once and exposes every public
method to the model (`utils/plugin.py`, `utils/tools.py`), so a helper here must stay private or it
becomes a second operation. The reserved `__…__` parameters are injected by Open WebUI and are
absent from the model-facing schema: pydantic's `create_model` drops a leading-underscore field
name, and `get_tools()` strips the same names again before the spec reaches the model.

Publication is the outlet filter's, not this return value: only a backend-recorded tool call may
publish a figure (transport ruling), and the filter re-derives the verdict from that record.
"""

from verifier.pysrc.verify import Verified
from webui.paste_in.owui_files import uploaded_files
from webui.paste_in.receipt import Receipt, write_receipt
from webui.paste_in.selection import first_verdict
from webui.paste_in.verdicts import CHART_NOT_PRODUCED, CHART_PRODUCED


def _request_text(metadata: dict[str, object] | None) -> str | None:
    user_message = (metadata or {}).get("user_message")
    if not isinstance(user_message, dict):
        return None
    content = user_message.get("content")
    return content if isinstance(content, str) else None


class Tools:
    """The pasted tool. One public method, so the model sees one operation."""

    async def draw_figure(
        self,
        program: str,
        __metadata__: dict[str, object] | None = None,
        __user__: dict[str, object] | None = None,
        __request__: object | None = None,
    ) -> str:
        """Draw a chart from a complete Python program over the attached CSV file.

        :param program: The complete Python program that draws the chart.
        """
        user_id = (__user__ or {}).get("id")
        request_text = _request_text(__metadata__)
        attachments = (
            await uploaded_files(__metadata__, user_id) if isinstance(user_id, str) else ()
        )
        if __request__ is not None:
            write_receipt(
                __request__,
                Receipt(
                    program,
                    tuple(attachment.file_id for attachment in attachments),
                    request_text,
                ),
            )
        if not isinstance(user_id, str):
            return CHART_NOT_PRODUCED
        verdict, _consumed = first_verdict(program, attachments, request_text)
        return CHART_PRODUCED if isinstance(verdict, Verified) else CHART_NOT_PRODUCED
'''

_ROOT = "webui.paste_in.tool"


def _load() -> types.ModuleType:
    """Execute each embedded module in its own namespace and restore the embedded module slots.

    Registration comes first for every name, which is what lets a submodule import resolve before
    its package `__init__` has run; the blobs then execute in dependency order, so each `from X
    import Y` finds `Y` already bound. Each source is stored with one leading newline, stripped
    here so the executed bytes equal the tracked file's.

    The embedded-name registration is undone in `finally`; newly imported standard-library
    modules remain loaded. This file runs inside Open WebUI's process, so an embedded-name residue
    would shadow, or be shadowed by, whatever else that process imports.
    """
    saved = {name: sys.modules.get(name) for name in _SOURCES}
    modules = {}
    for name in _SOURCES:
        module = types.ModuleType(name)
        module.__path__ = []  # treat every name as a package so submodule lookups resolve
        modules[name] = module
        sys.modules[name] = module
    try:
        for name, source in _SOURCES.items():
            code = compile(source[1:], f"<paste-in:{name}>", "exec")
            exec(code, modules[name].__dict__)  # noqa: S102 - embedding IS this file's job
        return modules[_ROOT]
    finally:
        for name, previous in saved.items():
            if previous is None:
                del sys.modules[name]
            else:
                sys.modules[name] = previous


Tools = _load().Tools
