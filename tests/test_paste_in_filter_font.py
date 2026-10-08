# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M17.1 F1-F6: a figure that can draw non-ASCII text carries Open WebUI's bundled CJK font.

Contract: `.agent/contracts/m17u1.md`. Skeleton: each body is a module-level skip naming M17.1.
"""

import pytest

pytestmark = pytest.mark.skip(reason="M17.1 skeleton: the tester fills each body from the contract")


def test_f1_no_font_wrapper_is_byte_identical_to_the_pre_unit_wrapper() -> None:
    """F1: wrapper_code(p) == wrapper_code(p, None) == the two hand-stated pre-unit sha256 pins."""


def test_f2_font_prelude_registers_the_fallback_before_the_program_runs() -> None:
    """F2: no literal plotting name; two payloads (font, program); fake-executed call order."""


def test_f3_trigger_is_non_ascii_in_labels_or_consumed_csv() -> None:
    """F3: ASCII dataset/formula False; each label field, escaped label, header, cell, Latin-1."""


def test_f4_font_source_reads_owui_fonts_dir_off_the_loop_and_never_raises() -> None:
    """F4: fake open_webui.env present/missing attr/missing file/unreadable/raising; path pinned."""


def test_f5_outlet_reads_the_font_only_on_a_verified_non_ascii_figure() -> None:
    """F5: bomb on cjk_font; RPC code per case; an unavailable font sends the plain wrapper."""


def test_f6_differential_separates_font_and_program_payloads() -> None:
    """F6: oracle's own trigger; font where none expected / none where expected = disagreement."""
