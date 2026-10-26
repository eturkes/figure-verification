# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""S8's two tracker forms, read once for the static check (`test_spec.py` S8) and the CI skip guard
(`conftest.py`, G18): a skip either check admits must name what re-enables it NOW.

A blocker inside an unfinished unit lives with that unit, so a spine id counts; anything off-spine
cites the queue. Spine ids are read in the `**M13.6**` form on an OPEN `- [ ]` row of `Tasks` alone:
a unit named in passing prose -- `Carried forward from M13.4` -- never counts, and a unit stops
counting once its row is ticked `- [x] <sha>`, a row the layout keeps legal until its phase or
MAINTAIN request closes."""

import re

QUEUE = ".agent/deferred.md"
_TASKS = re.compile(r"^## Tasks$\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
_OPEN_ROW = re.compile(r"^- \[ \] (.*)$", re.MULTILINE)
_SPINE_UNIT = re.compile(r"\*\*(M\d+(?:\.\d+)?[a-z]?)\*\*")
_UNIT_CITATION = re.compile(r"M\d+(?:\.\d+)?[a-z]?")


def open_units(spec: str) -> frozenset[str]:
    """The spine ids of `spec`'s open `Tasks` rows; a spec without `Tasks` has none."""
    tasks = _TASKS.search(spec)
    return frozenset(
        unit
        for row in _OPEN_ROW.findall(tasks.group(1) if tasks else "")
        for unit in _SPINE_UNIT.findall(row)
    )


def names_tracker(reason: str, spine: frozenset[str]) -> bool:
    return QUEUE in reason or any(unit in spine for unit in _UNIT_CITATION.findall(reason))
