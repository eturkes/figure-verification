# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q68 (`.agent/archive/contracts/q68.md`): the no-file template names no CSV file and keeps its
measured bytes; the file templates keep their pre-Q68 bytes. Imports `templates` alone, so
mutation credit scopes to it."""

import hashlib

from webui.paste_in import templates


def test_q68_no_file_templates_name_no_csv_file() -> None:
    """T1: with no file attached, a template naming a CSV file made the demo's 0.5B model read one
    that does not exist (`pd.read_csv('your_file.csv')` ⇒ `program_error`)."""
    for artifact in (templates.PRODUCTION_TEMPLATES, templates.DEMO_TEMPLATES):
        assert "csv" in artifact.file.casefold()
        assert "csv" not in artifact.no_file.casefold()


def test_q68_file_templates_keep_their_bytes() -> None:
    """T2: the source sentence left the shared rules for the file template's tail, so both file
    templates keep the bytes the banner arms + the stub's matches were measured on."""
    digests = {
        hashlib.sha256(artifact.file.encode()).hexdigest()
        for artifact in (templates.PRODUCTION_TEMPLATES, templates.DEMO_TEMPLATES)
    }
    assert digests == {
        "94815a5137bdf36a00c37fde710784b1584644b119f9f3d7ea92393185940877",
        "9050adc064664392b2d0f0874e82d1412b0e15efd8a5e143449e3f8fe2a18d33",
    }


def test_q68_no_file_templates_keep_the_measured_bytes() -> None:
    """T3: the no-file bytes the selection + the live record (`.agent/measurements/q68/`) measured;
    an edit here leaves that record describing other bytes until the MX150 runs are retaken."""
    digests = {
        hashlib.sha256(artifact.no_file.encode()).hexdigest()
        for artifact in (templates.PRODUCTION_TEMPLATES, templates.DEMO_TEMPLATES)
    }
    assert digests == {
        "6a3f834613ceadb8aff2045e20542e63d07df988dfee53940f426295d6e461e0",
        "1ceee87b3e59c7e14eb3d2e7c0bb41cd45f7bf9cd5e38b1bd55761a85ca16d89",
    }
