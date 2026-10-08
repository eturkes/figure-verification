# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M18.1 literal witnesses; coordinates follow the contract, not production helpers.

Contract: `.agent/archive/contracts/m18u1.md` P2-P7/P9.
"""

from dataclasses import dataclass, replace

from verifier.pysrc import spec
from verifier.pysrc.errors import RefusalCode
from verifier.pysrc.limits import DEFAULT_LIMITS, PysrcLimits

type Coordinates = tuple[int, int, int, int]
type TraceLiteral = tuple[tuple[str, Coordinates], ...]


@dataclass(frozen=True)
class Witness:
    name: str
    source: str
    code: RefusalCode | None
    at: tuple[Coordinates, ...] = ()
    trace: TraceLiteral = ()
    target: spec.DeclaredTarget | None = None
    limits: PysrcLimits = DEFAULT_LIMITS


FORMULA_IMPORTS = "import numpy as np\nimport matplotlib.pyplot as plt\n"
FORMULA_BODY = "x = np.linspace(0, 1, num=3)\ny = np.sin(x)\nplt.plot(x, y)\n"
FORMULA = FORMULA_IMPORTS + FORMULA_BODY + "plt.show()\n"
FORMULA_TRACE: TraceLiteral = (
    ("import", (1, 0, 1, 18)),
    ("import", (2, 0, 2, 31)),
    ("data", (3, 0, 3, 28)),
    ("data", (4, 0, 4, 13)),
    ("mark", (5, 0, 5, 14)),
    ("show", (6, 0, 6, 10)),
)
DATASET_IMPORTS = "import pandas as pd\nimport matplotlib.pyplot as plt\n"
DATASET_BODY = 'df = pd.read_csv("data.csv")\nplt.bar(df["site"], df["value"])\n'
DATASET = DATASET_IMPORTS + DATASET_BODY + "plt.show()\n"
DATASET_TRACE: TraceLiteral = (
    ("import", (1, 0, 1, 19)),
    ("import", (2, 0, 2, 31)),
    ("source", (3, 0, 3, 28)),
    ("mark", (4, 0, 4, 32)),
    ("show", (5, 0, 5, 10)),
)
CSV = b"site,value,orders\nwest,1,4\neast,2,5\n"
TARGET = spec.DatasetTarget("data.csv", CSV)

PRESCAN = (
    Witness(
        "source-cap",
        "年 = 1",
        "source_too_large",
        limits=replace(DEFAULT_LIMITS, max_source_bytes=1),
    ),
    Witness(
        "token-cap", "年 = 1\n", "too_many_tokens", limits=replace(DEFAULT_LIMITS, max_tokens=4)
    ),
    Witness("surrogate-first", "年 = '\ud800\udfff'", "source_not_utf8", ((1, 7, 1, 10),)),
    Witness("surrogate-crlf", "# 題\r\n年 = '\udfff'", "source_not_utf8", ((2, 7, 2, 10),)),
    Witness("nul-first", "年 = '\x00\x00'\n", "source_has_nul", ((1, 7, 1, 8),)),
    Witness(
        "line-cap",
        "年 = 12\n",
        "line_too_long",
        ((1, 0, 1, 8),),
        limits=replace(DEFAULT_LIMITS, max_line_bytes=7),
    ),
    Witness(
        "line-cap-nel",
        "#年\x85長長",
        "line_too_long",
        ((1, 6, 1, 12),),
        limits=replace(DEFAULT_LIMITS, max_line_bytes=4),
    ),
    Witness("token-error-unicode", '年 = "題', "source_not_tokenizable", ((1, 6, 1, 7),)),
    Witness(
        "token-error-bare-cr",
        '年 = 1\rplt.title("題")\rx = "題',
        "source_not_tokenizable",
        ((3, 4, 3, 5),),
    ),
    Witness("token-error-eof-quote", '年 = "', "source_not_tokenizable", ((1, 6, 1, 7),)),
    Witness("token-error-eof-clamped", "年 = \\\n", "source_not_tokenizable", ((1, 7, 1, 7),)),
    Witness(
        "token-error-indent-position",
        "年 = 1\n  値 = 2\n 値 = 3\n",
        "source_not_tokenizable",
        ((3, 8, 3, 8),),
    ),
    Witness(
        "nesting",
        "年 = ((1))",
        "nesting_too_deep",
        ((1, 7, 1, 8),),
        limits=replace(DEFAULT_LIMITS, max_bracket_depth=1),
    ),
    Witness(
        "nesting-bare-cr",
        '年 = 1\rplt.title("題")\rx = ((1))',
        "nesting_too_deep",
        ((3, 5, 3, 6),),
        limits=replace(DEFAULT_LIMITS, max_bracket_depth=1),
    ),
    Witness("unbalanced", "年 = 1)\n", "unbalanced_brackets", ((1, 7, 1, 8),)),
    Witness(
        "indent-tabs",
        "if 年:\n\tif 年:\n\t\t値 = 1\n",
        "indent_too_deep",
        ((3, 0, 3, 2),),
        limits=replace(DEFAULT_LIMITS, max_indent_depth=1),
    ),
)

ADMISSION = (
    Witness(
        "inner-call",
        "import numpy as np\nx = np.sin(np.sinh(1))\n",
        "call_target_not_admitted",
        ((2, 11, 2, 21),),
    ),
    Witness(
        "comprehension",
        "import numpy as np\nx = np.sin([i for i in (1, 2)])\n",
        "expression_not_admitted",
        ((2, 11, 2, 30),),
    ),
    Witness("unbound-name", "年 = missing\n", "name_not_bound", ((1, 6, 1, 13),)),
    Witness("tuple-assignment", "年, x = 1\n", "assign_target_not_admitted", ((1, 0, 1, 10),)),
    Witness("seaborn-import", "import seaborn as sns\n", "import_not_admitted", ((1, 0, 1, 21),)),
    Witness(
        "bare-multiline-keyword",
        "import matplotlib.pyplot as plt\nplt.plot(\n    1,\n    2,\n    linewidth=2,\n)\n",
        "keyword_not_admitted",
        ((2, 0, 6, 1),),
    ),
    Witness(
        "semicolon-second-statement",
        "年 = 1; import seaborn as sns; x = 2\n",
        "import_not_admitted",
        ((1, 9, 1, 30),),
    ),
    Witness("parse-end", "x = = 1\n", "source_not_parsable", ((1, 4, 1, 5),)),
    Witness("parse-end-non-ascii", "年 = = 1\n", "source_not_parsable", ((1, 6, 1, 7),)),
    Witness("parse-no-end", "if 年:\n", "source_not_parsable", ((1, 7, 1, 7),)),
    Witness("statement", "pass\n", "statement_not_admitted", ((1, 0, 1, 4),)),
    Witness(
        "attribute",
        "import numpy as np\nx = np.__version__\n",
        "attribute_not_admitted",
        ((2, 4, 2, 18),),
    ),
    Witness("operator", "年 = 1 // 2\n", "operator_not_admitted", ((1, 6, 1, 12),)),
    Witness("literal", "年 = ...\n", "literal_not_admitted", ((1, 6, 1, 9),)),
    Witness(
        "column-not-literal",
        'import pandas as pd\ndf = pd.read_csv("data.csv")\nx = df[1]\n',
        "column_not_literal",
        ((3, 4, 3, 9),),
    ),
)

PROJECTION = (
    Witness(
        "multiple-marks",
        FORMULA_IMPORTS + FORMULA_BODY + "plt.scatter(x, y)\nplt.show()\n",
        "multiple_marks",
        ((6, 0, 6, 17),),
    ),
    Witness(
        "label-not-literal",
        FORMULA_IMPORTS + FORMULA_BODY + "plt.title(x)\nplt.show()\n",
        "label_not_literal",
        ((6, 0, 6, 12),),
    ),
    Witness(
        "after-terminal",
        FORMULA + 'plt.title("題")\n',
        "statement_after_terminal",
        ((7, 0, 7, 16),),
    ),
    Witness(
        "orphaned-mark",
        FORMULA_IMPORTS + FORMULA_BODY + "plt.figure()\nplt.show()\n",
        "figure_orphans_mark",
        ((6, 0, 6, 12),),
    ),
    Witness(
        "rebound",
        FORMULA_IMPORTS
        + "x = np.linspace(0, 1, num=3)\nx = np.arange(3)\nplt.plot(x, x)\nplt.show()\n",
        "name_rebound",
        ((4, 0, 4, 16),),
    ),
    Witness(
        "substituted-binding",
        FORMULA_IMPORTS + "x = np.linspace(0, 1, num=3)\n"
        "y = np.sin(np.linspace(0, 2, num=3))\nplt.plot(x, y)\nplt.show()\n",
        "y_not_over_grid",
        ((4, 11, 4, 35), (5, 0, 5, 14)),
    ),
    Witness(
        "ambiguous-arm",
        "import pandas as pd\n"
        + FORMULA_IMPORTS
        + "x = np.linspace(0, 1, num=3)\nz = np.arange(3)\nplt.plot(x, z)\nplt.show()\n",
        "arm_ambiguous",
        ((1, 0, 1, 19), (4, 0, 4, 28), (5, 0, 5, 16)),
    ),
    Witness(
        "first-unused-binding",
        FORMULA_IMPORTS + "年 = 7\nunused = 8\n" + FORMULA_BODY + "plt.show()\n",
        "statement_not_projected",
        ((3, 0, 3, 7),),
    ),
    Witness("no-mark", "import matplotlib.pyplot as plt\nplt.show()\n", "no_mark"),
    Witness("no-terminal", FORMULA_IMPORTS + FORMULA_BODY, "no_terminal"),
    Witness(
        "dataset-multiple-marks",
        DATASET_IMPORTS + DATASET_BODY + 'plt.bar(df["site"], df["value"])\nplt.show()\n',
        "multiple_marks",
        ((5, 0, 5, 32),),
    ),
    Witness(
        "dataset-label-not-literal",
        DATASET_IMPORTS + DATASET_BODY + "plt.title(df)\nplt.show()\n",
        "label_not_literal",
        ((5, 0, 5, 13),),
    ),
    Witness(
        "dataset-after-terminal",
        DATASET + "plt.grid(True)\n",
        "statement_after_terminal",
        ((6, 0, 6, 14),),
    ),
    Witness(
        "dataset-orphaned-mark",
        DATASET_IMPORTS + DATASET_BODY + "plt.figure()\nplt.show()\n",
        "figure_orphans_mark",
        ((5, 0, 5, 12),),
    ),
    Witness(
        "dataset-rebound",
        DATASET_IMPORTS + 'df = pd.read_csv("data.csv")\nx = df["site"]\n'
        'x = df["site"]\nplt.bar(x, df["value"])\nplt.show()\n',
        "name_rebound",
        ((5, 0, 5, 14),),
    ),
)

_TITLE_TRACE: TraceLiteral = (*DATASET_TRACE[:4], ("title", (5, 0, 5, 19)), ("show", (6, 0, 6, 10)))
_XLABEL_TRACE: TraceLiteral = (
    *DATASET_TRACE[:4],
    ("xlabel", (5, 0, 5, 20)),
    ("show", (6, 0, 6, 10)),
)
_YLABEL_TRACE: TraceLiteral = (
    *DATASET_TRACE[:4],
    ("ylabel", (5, 0, 5, 20)),
    ("show", (6, 0, 6, 10)),
)
_SERIES_TRACE: TraceLiteral = (*DATASET_TRACE[:3], ("mark", (4, 0, 4, 48)), ("show", (5, 0, 5, 10)))
_LINE_TRACE: TraceLiteral = (*DATASET_TRACE[:3], ("mark", (4, 0, 4, 33)), ("show", (5, 0, 5, 10)))
_NONFINITE_TRACE: TraceLiteral = (*FORMULA_TRACE[:3], ("data", (4, 0, 4, 9)), *FORMULA_TRACE[4:])

POST_PROJECTION = (
    Witness("source-not-supplied", DATASET, "source_not_supplied", ((3, 0, 3, 28),), DATASET_TRACE),
    Witness(
        "dataset-path-mismatch",
        DATASET,
        "target_mismatch",
        ((3, 0, 3, 28),),
        DATASET_TRACE,
        spec.DatasetTarget("other.csv", CSV),
    ),
    Witness(
        "dataset-arm-mismatch",
        DATASET,
        "source_not_supplied",
        ((3, 0, 3, 28),),
        DATASET_TRACE,
        spec.FormulaTarget(spec.Var()),
    ),
    Witness(
        "inconsistent-title",
        DATASET_IMPORTS + DATASET_BODY + 'plt.title("orders")\nplt.show()\n',
        "label_not_consistent",
        ((5, 0, 5, 19),),
        _TITLE_TRACE,
        TARGET,
    ),
    Witness(
        "inconsistent-xlabel",
        DATASET_IMPORTS + DATASET_BODY + 'plt.xlabel("orders")\nplt.show()\n',
        "label_not_consistent",
        ((5, 0, 5, 20),),
        _XLABEL_TRACE,
        TARGET,
    ),
    Witness(
        "inconsistent-ylabel",
        DATASET_IMPORTS + DATASET_BODY + 'plt.ylabel("orders")\nplt.show()\n',
        "label_not_consistent",
        ((5, 0, 5, 20),),
        _YLABEL_TRACE,
        TARGET,
    ),
    Witness(
        "inconsistent-series",
        DATASET.replace('df["value"])', 'df["value"], label="orders")'),
        "label_not_consistent",
        ((4, 0, 4, 48),),
        _SERIES_TRACE,
        TARGET,
    ),
    Witness(
        "formula-value-mismatch",
        FORMULA,
        "target_mismatch",
        trace=FORMULA_TRACE,
        target=spec.FormulaTarget(spec.Var()),
    ),
    Witness("formula-arm-mismatch", FORMULA, "target_mismatch", trace=FORMULA_TRACE, target=TARGET),
    Witness(
        "column-substitution",
        DATASET,
        "column_not_requested",
        trace=DATASET_TRACE,
        target=spec.DatasetTarget("data.csv", CSV, "orders by site", "substitution"),
    ),
    Witness(
        "column-not-named",
        DATASET,
        "column_not_named",
        trace=DATASET_TRACE,
        target=spec.DatasetTarget("data.csv", CSV, "Chart value"),
    ),
    Witness(
        "csv-broken",
        DATASET,
        "csv_not_parsable",
        trace=DATASET_TRACE,
        target=spec.DatasetTarget("data.csv", b'site,value\n"west,1\n'),
    ),
    Witness(
        "csv-cap",
        DATASET,
        "csv_too_large",
        trace=DATASET_TRACE,
        target=TARGET,
        limits=replace(DEFAULT_LIMITS, max_csv_bytes=1),
    ),
    Witness(
        "column-missing",
        DATASET,
        "column_not_present",
        trace=DATASET_TRACE,
        target=spec.DatasetTarget("data.csv", b"site,other\nwest,1\n"),
    ),
    Witness(
        "column-text",
        DATASET,
        "column_not_numeric",
        trace=DATASET_TRACE,
        target=spec.DatasetTarget("data.csv", b"site,value\nwest,bad\n"),
    ),
    Witness(
        "value-profile",
        DATASET,
        "value_not_in_profile",
        trace=DATASET_TRACE,
        target=spec.DatasetTarget("data.csv", b"site,value\nwest,-0\n"),
    ),
    Witness(
        "value-nonfinite",
        FORMULA.replace("y = np.sin(x)", "y = x / 0"),
        "value_not_finite",
        trace=_NONFINITE_TRACE,
    ),
    Witness(
        "work-cap",
        DATASET,
        "work_budget_exceeded",
        trace=DATASET_TRACE,
        target=TARGET,
        limits=replace(DEFAULT_LIMITS, max_work=1),
    ),
    Witness(
        "category-duplicate",
        DATASET,
        "category_not_unique",
        trace=DATASET_TRACE,
        target=spec.DatasetTarget("data.csv", b"site,value\nwest,1\nwest,2\n"),
    ),
    Witness(
        "x-unordered",
        DATASET.replace("plt.bar", "plt.plot"),
        "x_not_ordered",
        trace=_LINE_TRACE,
        target=spec.DatasetTarget("data.csv", b"site,value\n2,1\n1,2\n"),
    ),
)

_PAIR_DECORATED = (
    DATASET_IMPORTS + "plt.figure(figsize=(6, 4))\n"
    'df = pd.read_csv("data.csv")\n'
    'x = df["site"]\n'
    'y = df["value"]\n'
    'plt.bar(x, y, label="value")\n'
    'plt.title("題")\n'
    'plt.xlabel("site")\n'
    'plt.ylabel("value")\n'
    "plt.legend()\n"
    "plt.grid(True)\n"
    "plt.xticks(rotation=45)\n"
    "plt.tight_layout()\n"
    "plt.show()\n"
)
_PAIR_DECORATED_TRACE: TraceLiteral = (
    ("import", (1, 0, 1, 19)),
    ("import", (2, 0, 2, 31)),
    ("layout", (3, 0, 3, 26)),
    ("source", (4, 0, 4, 28)),
    ("data", (5, 0, 5, 14)),
    ("data", (6, 0, 6, 15)),
    ("mark", (7, 0, 7, 28)),
    ("title", (8, 0, 8, 16)),
    ("xlabel", (9, 0, 9, 18)),
    ("ylabel", (10, 0, 10, 19)),
    ("decoration", (11, 0, 11, 12)),
    ("decoration", (12, 0, 12, 14)),
    ("layout", (13, 0, 13, 23)),
    ("layout", (14, 0, 14, 18)),
    ("show", (15, 0, 15, 10)),
)
_AGGREGATE = (
    DATASET_IMPORTS + 'df = pd.read_csv("data.csv")\n'
    'g = df.groupby("site")["value"].sum()\n'
    'g.plot(kind="line")\n'
    "plt.show()\n"
)
_AGGREGATE_TRACE: TraceLiteral = (
    ("import", (1, 0, 1, 19)),
    ("import", (2, 0, 2, 31)),
    ("source", (3, 0, 3, 28)),
    ("data", (4, 0, 4, 37)),
    ("mark", (5, 0, 5, 19)),
    ("show", (6, 0, 6, 10)),
)
_MULTILINE_FORMULA = FORMULA_IMPORTS + FORMULA_BODY + 'plt.title("""題\n値""")\nplt.show()\n'
_MULTILINE_TRACE: TraceLiteral = (
    *FORMULA_TRACE[:5],
    ("title", (6, 0, 7, 7)),
    ("show", (8, 0, 8, 10)),
)
_COMPACT_FORMULA = (
    "import numpy as np; import matplotlib.pyplot as plt\n"
    "x = np.arange(3); y = x; plt.plot(x, y); plt.show()\n"
)
_COMPACT_TRACE: TraceLiteral = (
    ("import", (1, 0, 1, 18)),
    ("import", (1, 20, 1, 51)),
    ("data", (2, 0, 2, 16)),
    ("data", (2, 18, 2, 23)),
    ("mark", (2, 25, 2, 39)),
    ("show", (2, 41, 2, 51)),
)
PASS = (
    Witness("pair-all-roles", _PAIR_DECORATED, None, trace=_PAIR_DECORATED_TRACE, target=TARGET),
    Witness("aggregate-accessor", _AGGREGATE, None, trace=_AGGREGATE_TRACE, target=TARGET),
    Witness("formula-bindings", FORMULA, None, trace=FORMULA_TRACE),
    Witness("formula-multiline-label", _MULTILINE_FORMULA, None, trace=_MULTILINE_TRACE),
    Witness("formula-semicolon", _COMPACT_FORMULA, None, trace=_COMPACT_TRACE),
    Witness("pair-crlf", DATASET.replace("\n", "\r\n"), None, trace=DATASET_TRACE, target=TARGET),
    Witness("pair-bare-cr", DATASET.replace("\n", "\r"), None, trace=DATASET_TRACE, target=TARGET),
)
ALL_WITNESSES = PRESCAN + ADMISSION + PROJECTION + POST_PROJECTION + PASS
