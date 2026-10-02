# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Strict per-id comparison; measurements emit results/<id>.json independently of expected/."""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def bound_difference(expected, actual, path):
    operator, bound = next(iter(expected.items()))
    if type(bound) not in (int, float) or type(actual) is not type(bound):
        return f"{path}: invalid numeric bound or observed type"
    holds = actual <= bound if operator == "$le" else actual >= bound
    return None if holds else f"{path}: observed {actual!r} violates {operator} {bound!r}"


def container_difference(expected, actual, path):
    if isinstance(expected, dict):
        if expected.keys() != actual.keys():
            return f"{path}: keys {sorted(actual)} != {sorted(expected)}"
        pairs = ((f"{path}.{key}", value, actual[key]) for key, value in expected.items())
    else:
        if len(expected) != len(actual):
            return f"{path}: length {len(actual)} != {len(expected)}"
        pairs = (
            (f"{path}[{index}]", left, right)
            for index, (left, right) in enumerate(zip(expected, actual, strict=True))
        )
    for child, left, right in pairs:
        if mismatch := difference(left, right, child):
            return mismatch
    return None


def difference(expected, actual, path="$"):
    if isinstance(expected, dict) and set(expected) in ({"$le"}, {"$ge"}):
        return bound_difference(expected, actual, path)
    if type(expected) is not type(actual):
        return f"{path}: type {type(actual).__name__} != {type(expected).__name__}"
    if isinstance(expected, (dict, list)):
        return container_difference(expected, actual, path)
    return None if expected == actual else f"{path}: observed {actual!r} != expected {expected!r}"


def main():
    parser = argparse.ArgumentParser(
        description="Compare measurements with their published results."
    )
    parser.add_argument("ids", nargs="+", help="measurement identifiers")
    args = parser.parse_args()
    failures = 0
    for name in args.ids:
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", name) is None:
            print(f"{name}: FAIL invalid measurement id", file=sys.stderr)
            failures += 1
            continue
        try:
            expected = json.loads((ROOT / "expected" / f"{name}.json").read_text())
            actual = json.loads((ROOT / "results" / f"{name}.json").read_text())
            mismatch = difference(expected, actual)
        except (OSError, ValueError) as exc:
            mismatch = str(exc)
        if mismatch is None:
            print(f"{name}: PASS")
        else:
            print(f"{name}: FAIL {mismatch}", file=sys.stderr)
            failures += 1
    return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
