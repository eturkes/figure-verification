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
    templates keep the bytes the banner arms + the stub's matches were measured on. Q76 (user
    ruling) added the seaborn sentence to the shared rules: the live records (q69, q70, deps-u3)
    describe the bytes before it, no MX150 rerun claimed."""
    digests = {
        hashlib.sha256(artifact.file.encode()).hexdigest()
        for artifact in (templates.PRODUCTION_TEMPLATES, templates.DEMO_TEMPLATES)
    }
    assert digests == {
        "2b34fceee4df83049992730f1e6ad10f8772c79545e5b922f8f42cb31cf0eec9",
        "e8c6b43e92ae96ffbb64dc16ca56558e69429fe81d8dc9ff174aae7a0f464d2a",
    }


def test_q68_no_file_templates_keep_the_measured_bytes() -> None:
    """T3: the demo's no-file bytes = the ones the selection + the live record
    (`.agent/measurements/q69/`) measured, so an edit there leaves that record describing other
    bytes until the MX150 runs are retaken (Q76's seaborn sentence did so: the shared rules end
    every template); production's = the user's Q71 text, unmeasured."""
    digests = {
        hashlib.sha256(artifact.no_file.encode()).hexdigest()
        for artifact in (templates.PRODUCTION_TEMPLATES, templates.DEMO_TEMPLATES)
    }
    assert digests == {
        "2219cd46d3a2c0eeaa5f7046a37d25d72fa31b644c55c16acd687d38f3cac009",
        "4ab604abfffbdf9f47eb636fa11aa33eea528b196f9145561b81e1d1e4ee3820",
    }


def test_q76_g1_both_carriers_state_the_seaborn_guidance() -> None:
    """User rulings (Q76): seaborn's default error bars + `sns.histplot` counts block, so the chart
    rules every template ends with and the tool description ask for what passes
    (`.agent/archive/contracts/q76.md` G1)."""
    from webui.paste_in.tool import Tools  # noqa: PLC0415 - the description is the docstring

    description = " ".join((Tools.draw_figure.__doc__ or "").split())
    for text in (templates.RULES, description):
        assert "With seaborn, pass errorbar=None to bar and line charts." in text
        assert "Draw histograms with plt.hist." in text
    for artifact in (templates.PRODUCTION_TEMPLATES, templates.DEMO_TEMPLATES):
        assert templates.RULES in artifact.file
        assert templates.RULES in artifact.no_file
