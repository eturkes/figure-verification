# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Internal inlet branches not reached by the X1-X3 contract suite."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Coroutine
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from paste_in_support import StoredFile, fake_open_webui, load_filter_module
from verifier.pysrc.limits import DEFAULT_LIMITS


def _inlet(
    body: dict[str, object],
    metadata: dict[str, object] | None,
    user: dict[str, object] | None,
) -> dict[str, object]:
    operation = load_filter_module().Filter().inlet(body, __user__=user, __metadata__=metadata)
    return asyncio.run(cast(Coroutine[Any, Any, dict[str, object]], operation))


@pytest.mark.parametrize(
    ("body", "user"),
    [
        ({"messages": [{"role": "user", "content": "a"}]}, None),
        ({"messages": "not a list"}, {"id": "owner"}),
    ],
    ids=["missing-user", "messages-not-list"],
)
def test_inlet_returns_original_body_before_file_lookup_on_invalid_context(
    body: dict[str, object], user: dict[str, object] | None
) -> None:
    """Neither absent identity nor a malformed message collection reaches the store."""
    assert _inlet(body, {"files": [{"id": "file"}]}, user) is body


def test_inlet_ignores_an_earlier_text_user_when_last_user_content_is_not_text(
    tmp_path: Path,
) -> None:
    """The last user turn owns the request even when it cannot be rendered."""
    first = {"role": "user", "content": "renderable"}
    last = {"role": "user", "content": ["not text"]}
    body: dict[str, object] = {"messages": [first, last]}
    metadata: dict[str, object] = {"user_message": last, "files": [{"id": "owned"}]}
    before = copy.deepcopy(body)
    with fake_open_webui(
        (StoredFile("owned", "owner", "a.csv", b"x,y\na,1\n"),), tmp_path
    ) as calls:
        returned = _inlet(body, metadata, {"id": "owner"})
    assert calls == [("owned", "owner")]
    assert returned is body and body == before
    assert metadata["user_message"] is last


def test_inlet_preserves_body_when_core_work_budget_refuses_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The core's bounded CSV reader, not a parallel parser, decides header availability."""
    module = load_filter_module()
    monkeypatch.setattr(module, "DEFAULT_LIMITS", replace(DEFAULT_LIMITS, max_work=1))
    last = {"role": "user", "content": "draw a chart"}
    body: dict[str, object] = {"messages": [last]}
    metadata: dict[str, object] = {"user_message": last, "files": [{"id": "owned"}]}
    with fake_open_webui((StoredFile("owned", "owner", "a.csv", b"x,y\na,1\n"),), tmp_path):
        returned = _inlet(body, metadata, {"id": "owner"})
    assert returned is body
    assert last["content"] == "draw a chart"
