import csv
import io
import json
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent
FIXTURES: dict[str, bytes] = {
    "quoted_comma": b'a,b\n"x,y",z\n',
    "escaped_double_quote": b'a,b\n"x""y",z\n',
    "quoted_empty": b'a,b\n"",z\n',
    "unterminated_quote": b'a,b\n"x,y\n',
    "embedded_lf": b'a,b\n"x\ny",z\n',
    "crlf_records": b"a,b\r\nx,y\r\n",
    "embedded_crlf": b'a,b\r\n"x\r\ny",z\r\n',
    "bare_cr_records": b"a,b\rx,y\r",
    "leading_trailing_unquoted_spaces": b"a,b\n  x  , y \n",
    "space_before_quote": b'a,b\n "x",y\n',
    "space_after_quote": b'a,b\n"x" ,y\n',
    "spaces_both_sides_quote": b'a,b\n "x" ,y\n',
    "tab_after_quote": b'a,b\n"x"\t,y\n',
    "junk_after_quote": b'a,b\n"x"q,y\n',
    "quote_inside_unquoted": b'a,b\nx"y,z\n',
    "duplicate_header": b"a,a\n1,2\n",
    "ragged_short_then_full": b"a,b,c\n1,2\n3,4,5\n",
    "ragged_long_then_full": b"a,b\n1,2,3\n4,5\n",
    "utf8_bom": b"\xef\xbb\xbfa,b\n1,2\n",
    "empty_trailing_field": b"a,b,\n1,2,\n",
    "backslash_literal": b"a,b\nx\\y,z\n",
    "backslash_before_comma": b"a,b\nx\\,y,z\n",
    "backslash_before_quote": b'a,b\n"x\\"y",z\n',
    "comment_looking_data": b"a,b\n#not,a-comment\n1,2\n",
    "comment_looking_header": b"#a,b\n1,2\n",
}


def stdlib_rows(data: bytes) -> dict[str, Any]:
    try:
        stream = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8", newline="")
        return {"ok": True, "rows": list(csv.reader(stream, strict=True))}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def pandas_rows(data: bytes, *, minimal: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"engine": "c"}
    if minimal:
        kwargs.update(dtype=str, keep_default_na=False, header=None)
    caught: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as records:
            warnings.simplefilter("always")
            frame = pd.read_csv(io.BytesIO(data), **kwargs)
        caught = [f"{type(item.message).__name__}: {item.message}" for item in records]
        cells = [
            [value.item() if hasattr(value, "item") else value for value in row]
            for row in frame.to_numpy()
        ]
        return {
            "ok": True,
            "columns": [
                value.item() if hasattr(value, "item") else value for value in frame.columns
            ],
            "dtypes": [str(dtype) for dtype in frame.dtypes],
            "rows": cells,
            "warnings": caught,
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "warnings": caught}


results: dict[str, Any] = {}
for name, data in FIXTURES.items():
    standard = stdlib_rows(data)
    minimal = pandas_rows(data, minimal=True)
    default = pandas_rows(data, minimal=False)
    comparable = (
        standard.get("rows") == minimal.get("rows")
        if standard["ok"] and minimal["ok"]
        else standard["ok"] == minimal["ok"]
    )
    results[name] = {
        "bytes": repr(data),
        "stdlib": standard,
        "pandas_minimal": minimal,
        "minimal_same_rows_or_same_rejection": comparable,
        "pandas_default": default,
    }
payload = {
    "python": __import__("sys").version.split()[0],
    "pandas": pd.__version__,
    "fixtures": len(FIXTURES),
    "results": results,
}
(ROOT / "t4.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, sort_keys=True))
