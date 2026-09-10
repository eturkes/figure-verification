# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The plotted table -- recomputation's static product, and the thing the certificate binds.

The model supplies a program, never values, so no CLAIMED number exists to contradict statically.
What recomputation produces instead is this table: the x and y the verifier says the figure shows.
Whether the EMITTED artifact really shows them is not settled here and is not implied; the
certificate declares that gap open, and M10's observation is what closes it.
"""

from dataclasses import dataclass

from verifier.pysrc.errors import PysrcCallerError

__all__ = ["CellValue", "PlottedTable"]

# A categorical x is a string; every other cell is float64. There is no null and no NaN: the CSV
# profile refuses every NA spelling before a cell reaches here, which is what makes G8 hold.
type CellValue = float | str

_DOMAIN = b"pysrc-table-0.1\n"
_LENGTH_BYTES = 8


def _payload(value: CellValue) -> tuple[bytes, bytes]:
    if isinstance(value, str):
        return b"s", value.encode("utf-8")
    return b"f", value.hex().encode("ascii")


def _field(value: CellValue) -> bytes:
    kind, payload = _payload(value)
    return kind + len(payload).to_bytes(_LENGTH_BYTES, "big") + payload


@dataclass(frozen=True, slots=True)
class PlottedTable:
    """One series: x against y, in the order the figure draws them.

    Row order is SOURCE order -- file order in the dataset arm, grid order in the formula arm. The
    legacy JSON mode's total sort is deliberately not reused: sorting would silently redraw a
    figure whose point order is part of what the user submitted.
    """

    x: tuple[CellValue, ...]
    y: tuple[float, ...]

    def __post_init__(self) -> None:
        """Unequal lengths are a CALLER fault, not a verdict about the source."""
        if len(self.x) != len(self.y):
            message = (
                f"plotted table length mismatch: {len(self.x)} x values, {len(self.y)} y values"
            )
            raise PysrcCallerError(message)

    def canonical_bytes(self) -> bytes:
        """One byte encoding per table value, locale-free and `repr`-free.

        Floats as `%a` hex, so a 1-ulp difference in any cell changes the bytes; string cells as
        UTF-8 behind a length prefix, so no cell's text can imitate a delimiter. Two structurally
        equal tables built by different code paths must produce identical bytes.
        """
        encoded = bytearray(_DOMAIN)
        encoded.extend(len(self.x).to_bytes(_LENGTH_BYTES, "big"))
        for x, y in zip(self.x, self.y, strict=True):
            encoded.extend(_field(x))
            encoded.extend(_field(y))
        return bytes(encoded)
