# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.6 the paste-in inlet renders the capture template over the user's own attachment.

Contract: `.agent/contracts/m10u6.md`. Each docstring carries its predicate's acceptance check; the
check is the test's specification and the contract's wording wins wherever a body would assert
more.

Skeleton: each body is `pytest.skip`, retired at M10.6's close together with this line.
"""

import pytest


def test_x1_inlet_renders_the_template_over_the_last_attachment() -> None:
    """X1: `Filter.inlet` (async) reads the owned attachments exactly as the tool does
    (`uploaded_files(__metadata__, <user id from __user__>)`) and takes the LAST one in chat order.
    When the verification core's CSV reader accepts that file's header, the inlet replaces the LAST
    `role == "user"` message of `body["messages"]` with a NEW dict whose `content` = the capture
    template `.format(task=<that message's content>, dataset=<the attachment's file name>,
    columns=", ".join(<header>))`. The body returns `==`-unchanged when there is no owned
    attachment, the reader refuses the header, the last user `content` is not a `str`, or no user
    message exists.

    Accept: a differential over generated (task, name, header) triples, braces in the task
    included, against the `.format` rule; `sentinel-simple` over `data/sales.csv` equals
    `capture.corpus.render_capture_prompt(<sentinel-simple row>)` byte for byte; each unchanged
    case asserts `==`.
    """
    pytest.skip("owned by **M10.6** (`.agent/spec.md` Deferred)")


def test_x2_inlet_leaves_metadata_files_and_history_untouched() -> None:
    """X2: The inlet leaves `__metadata__["user_message"]["content"]`, `__metadata__["files"]` and
    every earlier message untouched, never mutates a message dict in place, and writes no receipt.

    Accept: a deep-equality snapshot test in which `__metadata__["user_message"]` IS the last
    message object (aliasing, as a live request may share it); a mutant that assigns into the
    existing message dict goes red by name; a mutant that renders into
    `__metadata__["user_message"]["content"]` goes red by name.
    """
    pytest.skip("owned by **M10.6** (`.agent/spec.md` Deferred)")


def test_x3_the_template_has_one_authored_copy() -> None:
    """X3: `corpus/python/capture_prompt_v1.txt` is the template's ONE authored copy. Every other
    copy (the paste-in's, and any module the inlet imports at dev time) is written by
    `tools/generate_paste_in.py`, and `--check` names each drifted path.

    Accept: a one-byte template edit makes `--check` exit 1 naming the filter artifact; the
    committed tree `--check` rc 0.
    """
    pytest.skip("owned by **M10.6** (`.agent/spec.md` Deferred)")
