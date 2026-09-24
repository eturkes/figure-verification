# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.4 request grammar `pyexpr-0.1`.

Contract: `.agent/contracts/m10u4.md` predicate group R. Each docstring carries its
predicate's acceptance check; the check is the test's specification and the contract's wording
wins wherever a body would assert more.

Skeleton: each body is `pytest.skip`, retired at M10.4's close together with this line.
"""

import pytest


def test_r1_request_grammar_pyexpr_0_1_formula() -> None:
    """R1: `REQUEST_GRAMMAR = "pyexpr-0.1"`; `formula_target(text: str, limits: PysrcLimits =
    DEFAULT_LIMITS) -> FormulaTarget | None`. TOTAL: never raises for any `str`.

    Accept: Hypothesis over `st.text()` + the adversarial bank: no exception, result `None` or
    `FormulaTarget`.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_r2_unicodedata_normalize_nfkc_text_first_every() -> None:
    """R2: `unicodedata.normalize("NFKC", text)` first; every later rule reads the normalized text.
    Normalized UTF-8 length > `limits.max_source_bytes` → `None`.

    Accept: the full-width twin of `y=sin(x), x in [0,1]` (every non-space ASCII character
    replaced by its U+FF01-U+FF5E form) binds like the ASCII text; a 20,001-byte message →
    `None`.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_r3_expression_grammar_sum_product_product_product() -> None:
    r"""R3: Expression grammar: `sum := product (('+'|'-') product)*` · `product := unary (('*'|'/')
    unary)*` (both left-assoc → `Bin`) · `unary := '+' unary | '-' unary | power` (`+` dropped, `-`
    → `Neg`) · `power := primary ['**' exponent]`, `exponent := ['+'|'-'] INT` (`-` → `Neg(Num)`, no
    chaining) · `primary := NUMBER | 'x' | CONST | FN '(' sum ')' | '(' sum ')'`; FN = `sin cos tan
    exp log sqrt abs` → `Fn`; CONST = `pi e` → `Const`; `x` → `Var()`. NUMBER =
    `[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?` (ASCII): no `.`/exponent → `Num(Fraction(int(tok)))`, else
    `Num(Fraction(float(tok)))`, non-finite → invalid. Tokens are ASCII; spaces/tabs between tokens
    ignored.

    Accept: Hand-stated trees: `-x**2` = `Neg(Bin(pow, Var, 2))`; `x**-2` = `Bin(pow, Var, Neg(Num
    2))`; `2*x*x` left-assoc; `0.1` = `Fraction(0.1)`; `2pi`, `x^2`, `2**x`, `x**2**2`, `sin x`,
    `1e400` → invalid.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_r4_same_text_same_tree_for_every() -> None:
    """R4: SAME TEXT ⇒ SAME TREE: for every grammar expression `E` whose translated program
    projects, `formula_target(f"y = {E}, x in [0, 1]").y` equals the `y` the projection gives `E`
    written as a program (`sin(`→`np.sin(`…, `abs(`→`np.abs(`, `pi`→`np.pi`, `e`→`np.e`); bounds
    likewise equal the projected `np.linspace(A, B, n)` start/stop.

    Accept: Hypothesis property over drawn `E`, `A`, `B`.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_r5_carriers_keywords_case_sensitive_except_from() -> None:
    r"""R5: Carriers (keywords case-sensitive except `from`/`to`/`in`, which are ASCII
    case-insensitive; every keyword not preceded by `[A-Za-z0-9_]`): FORMULA = every `y` or `f(x)`
    followed by `[ \t]*=`, each needing a valid expression (x allowed) ending on a prose boundary;
    INTERVAL = every `x[ \t]*(∈|in)[ \t]*\[` (each must complete as `A[ \t]*,[ \t]*B[ \t]*\]`),
    plus every COMPLETE `from A to B` (B ending on a prose boundary) and every COMPLETE
    `A[ \t]*から[ \t]*B[ \t]*まで` (A preceded by a start boundary); COUNT = every
    `n[ \t]*=[ \t]*INT` ending on a prose boundary. Bounds A, B = grammar expressions WITHOUT `x`.

    Accept: Per-form witnesses EN + JA; `data from the file` and `ファイルから` alone are not
    interval carriers.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_r6_expression_span_the_maximal_run_of() -> None:
    r"""R6: Expression span = the MAXIMAL run of grammar tokens (per context: formula admits `x`,
    bounds do not) separated only by `[ \t]`; an identifier outside the context's set ends the
    run. Prose boundary after a run = end of text | `[ \t\r\n]` | a Japanese-class char
    (U+3000-U+30FF, U+4E00-U+9FFF) | one of `, ; : . ?` itself followed by end | whitespace |
    Japanese-class. Start boundary (から form) = start of text | whitespace | Japanese-class | one
    of `, ; : =`.

    Accept: `y = x^2 …`, `y = x!`, `y = (x)`, `y = x,x in [0,1]`, `2^3から4まで` → no target;
    `y = sin(x)を0から2*piまで描いて` binds.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_r7_exactly_one_formula_exactly_one_interval() -> None:
    """R7: Exactly one FORMULA, exactly one INTERVAL, at most one COUNT, spans pairwise disjoint; a
    malformed formula/count/bracket carrier counts as a carrier. Result = `FormulaTarget(y, Grid(A,
    B, n))` with a COUNT, else `FormulaTarget(y, Interval(A, B))`.

    Accept: Two identical formula carriers → `None`; formula + no interval → `None`; `from` +
    bracket both present → `None`; overlap (`y = 0から1まで`) → `None`.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")


def test_r8_bounded_nodes_limits_max_expr_nodes() -> None:
    """R8: Bounded: nodes ≤ `limits.max_expr_nodes`, nesting (parens + calls + unary) ≤
    `limits.max_bracket_depth`, else that carrier is invalid; extraction is linear in the text
    length.

    Accept: Over-limit witnesses → `None`; the worst adversarial 20,000-byte message completes < 2 s
    on the host.
    """
    pytest.skip("owned by **M10.4** (`.agent/spec.md` Deferred)")
