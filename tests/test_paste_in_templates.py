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
    ruling) added the seaborn sentence to the shared rules, and luna F2 (user ruling) scoped the
    inversion rule to numeric and date axes: the live records (q69, q70, deps-u3) describe the bytes
    before them, no MX150 rerun claimed."""
    digests = {
        hashlib.sha256(artifact.file.encode()).hexdigest()
        for artifact in (templates.PRODUCTION_TEMPLATES, templates.DEMO_TEMPLATES)
    }
    assert digests == {
        "5edef42b1d0eb8ca3c8079a505aeb8ce005deb2e5f58d4c775026b3a1b701c78",
        "7f6799e15baaa84659505b59672c1d2c642dd41449213d5d51875d04b16bb65a",
    }


def test_q68_no_file_templates_keep_the_measured_bytes() -> None:
    """T3: the demo's no-file bytes = the ones the selection + the live record
    (`.agent/measurements/q69/`) measured, so an edit there leaves that record describing other
    bytes until the MX150 runs are retaken (Q76's seaborn sentence and luna F2's inversion scope
    did so: the shared rules end every template); production's = the user's Q71 text, unmeasured.
    """
    digests = {
        hashlib.sha256(artifact.no_file.encode()).hexdigest()
        for artifact in (templates.PRODUCTION_TEMPLATES, templates.DEMO_TEMPLATES)
    }
    assert digests == {
        "a4644c9bb7905c7e48597959f770ac58fa35a2d464e7428f1c1e79a6127c518d",
        "ab43aee76b81fc721485fff64c20e1957c71ffd47d520bfea9af9486509be7f2",
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
