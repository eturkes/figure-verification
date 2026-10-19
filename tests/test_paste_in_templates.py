# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q68 (`.agent/archive/contracts/q68.md`): the no-file templates name no CSV file and keep their
pinned bytes; the file templates keep their pre-Q68 bytes. Imports `templates` alone, so mutation
credit scopes to it."""

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
    """T3: the demo's no-file bytes = the ones the selection + the live record
    (`.agent/measurements/q69/`) measured, so an edit there leaves that record describing other
    bytes until the MX150 runs are retaken; production's = the user's Q71 text, unmeasured."""
    digests = {
        hashlib.sha256(artifact.no_file.encode()).hexdigest()
        for artifact in (templates.PRODUCTION_TEMPLATES, templates.DEMO_TEMPLATES)
    }
    assert digests == {
        "2e652e520c712573e4742be72797a253ffadac80fa326a35cd61a637dc61a7c6",
        "de15937708a331e413b9e0debd0d4953f234b84239f4b05b11d9334bb6c345cc",
    }
