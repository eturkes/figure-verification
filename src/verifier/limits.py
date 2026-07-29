# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Core logical resource policy shared by verification, rendering, and replay.

`VerificationLimits` is immutable trusted operator policy. Each positive integer is an
upper bound, inclusive: work at the boundary is admitted and boundary+1 fails closed.
M5.1a established the vocabulary-ahead-of-consumers pattern; M9.1 extends it with
formula parse/evaluation/sampling and script-emission bounds before M9.2-M9.5 consume them.
Owner modules consume their relevant fields directly, keeping policy threading explicit and
ambient-state-free. Formula limits are operator policy beneath the schema's wider absolute
wire-shape bounds (`FormulaText` 1024 characters, domain samples 100,000); both layers fail closed.

`read_bounded` performs an unbuffered chunked read capped at `max_bytes + 1`, avoiding
`stat`-then-read races and hidden buffered read-ahead. It preserves filesystem exception
types: `FileNotFoundError` remains distinguishable as genuine absence while directory,
permission, symlink-loop, and other operator faults propagate unchanged.
"""

from pathlib import Path

import msgspec

from verifier.errors import VerificationError

__all__ = ["DEFAULT_LIMITS", "VerificationLimits", "read_bounded"]

_MIB = 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024


class VerificationLimits(msgspec.Struct, frozen=True, kw_only=True):
    """Inclusive upper bounds for one verification job; every field is a positive integer."""

    max_csv_bytes: int = 8 * _MIB
    max_manifest_bytes: int = 256 * 1024
    max_manifest_columns: int = 1_000
    max_source_rows: int = 100_000
    max_source_cells: int = 1_000_000
    max_plotted_cells: int = 1_000_000
    max_eval_work_units: int = 10_000_000
    max_render_rows: int = 10_000
    max_smt_terms: int = 100_000
    max_vega_bytes: int = 16 * _MIB
    max_svg_bytes: int = 32 * _MIB
    max_html_bytes: int = 32 * _MIB
    max_attestation_bytes: int = _MIB
    smt_timeout_ms: int = 1_000

    # Parse one formula (M9.2). digits caps one numeric literal; identifier_bytes caps
    # one name. Every bound is inclusive and deliberately tighter than wire shape.
    max_formula_bytes: int = 512
    max_formula_tokens: int = 256
    max_formula_ast_nodes: int = 256
    max_formula_ast_depth: int = 32
    max_formula_paren_depth: int = 32
    max_formula_digits: int = 32
    # Integer exponent of `**`: exact-rational numerator/denominator growth (M9.2/M9.4).
    max_formula_exponent: int = 64
    max_formula_identifier_bytes: int = 32
    # Sample schedule and exact-rational work/intermediate bit width (M9.3).
    max_formula_samples: int = 10_000
    max_formula_work_units: int = 10_000_000
    max_formula_intermediate_bits: int = 4096
    # Exact verifier-authored matplotlib script bytes (M9.5).
    max_matplotlib_script_bytes: int = _MIB

    def __post_init__(self) -> None:
        for name in self.__struct_fields__:
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                msg = f"{name} must be a positive integer, got {value!r}"
                raise ValueError(msg)


DEFAULT_LIMITS = VerificationLimits()


def read_bounded(path: Path, max_bytes: int) -> bytes:
    """Read at most `max_bytes + 1` bytes; reject an oversized file as resource policy.

    A zero ceiling is useful for generic boundary tests and admits only an empty file.
    VerificationLimits itself requires positive production ceilings. Filesystem errors are
    intentionally uncaught so callers retain the trusted-file absence/fault distinction.
    """
    if type(max_bytes) is not int or max_bytes < 0:
        msg = f"max_bytes must be a non-negative integer, got {max_bytes!r}"
        raise ValueError(msg)

    stop = max_bytes + 1
    payload = bytearray()
    # buffering=0 prevents BufferedReader from pulling bytes beyond the explicit limit+1
    # probe. The loop still handles short raw-file reads without treating one as EOF.
    with path.open("rb", buffering=0) as stream:
        while len(payload) < stop:
            chunk = stream.read(min(_READ_CHUNK_BYTES, stop - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
    if len(payload) > max_bytes:
        msg = f"file exceeds byte limit of {max_bytes}"
        raise VerificationError(msg, check="resource.file_bytes")
    return bytes(payload)
