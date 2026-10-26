# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The code the outlet sends to the browser: the reader, then the model's program, unchanged.

OWUI picks the sandbox packages from literal imports in the RPC source and patches the plotting
library when the source spells that library's name: its prelude replaces `pyplot.show` with one
that prints its own PNG and clears the figure (A5).
So the plotting name is never literal here: the wrapper loads the packages itself, quietly, and
carries the reader and the program as base64, split wherever the encoding spells that name.
"""

import base64
import re
from typing import Final

from webui.paste_in import fonts
from webui.paste_in.reader_text import reader_source

_PLOTTING: Final = "mat" + "plotlib"
# Seaborn sits in the bundle beside the stack and loads only for a program naming it: a word match
# admits every import form, and a comment naming it costs one wheel from the instance.
_SEABORN: Final = re.compile(r"\bseaborn\b")


def _payload(data: bytes) -> str:
    """Base64 source for `data`, split wherever the encoding spells the plotting name."""
    parts = base64.b64encode(data).decode("ascii").split(_PLOTTING)
    return " + 'mat' + 'plotlib' + ".join(repr(part) for part in parts)


def wrapper_code(program: str, font: bytes | None = None) -> str:
    """The RPC code: load the stack, write the font, run the reader over the exact program bytes.

    A `font` becomes matplotlib's fallback after DejaVu Sans inside the reader's run, so ordinary
    text draws its CJK glyphs; without one the reader runs on matplotlib's defaults. The reply's
    stdout is the reader's alone: the description line, then at most one PNG line.
    """
    font_lines = (
        ("_fv_font = None",)
        if font is None
        else (
            f"_fv_font = {fonts.path(font)!r}",
            "with open(_fv_font, 'wb') as _fv_handle:",
            f"    _fv_handle.write(_fv_b64.b64decode({_payload(font)}))",
        )
    )
    source = _payload(reader_source().encode("utf-8"))
    program_bytes = _payload(program.encode("utf-8", "surrogatepass"))
    seaborn = ", 'seaborn'" if _SEABORN.search(program) else ""
    return (
        "\n".join(
            (
                "import pyodide_js as _fv_pyodide",
                f"await _fv_pyodide.loadPackage(['numpy', 'pandas', 'mat' + 'plotlib'{seaborn}],",
                "                              messageCallback=lambda _message: None)",
                "import base64 as _fv_b64",
                "import os as _fv_os",
                "_fv_os.environ['MPLBACKEND'] = 'AGG'",
                *font_lines,
                "_fv_reader = {'__name__': 'figure_verification_reader'}",
                f"_fv_source = _fv_b64.b64decode({source}).decode('utf-8')",
                "exec(compile(_fv_source, '<figure-reader>', 'exec'), _fv_reader)",
                f"_fv_program = _fv_b64.b64decode({program_bytes})",
                "_fv_program = _fv_program.decode('utf-8', 'surrogatepass')",
                "print(_fv_reader['run'](_fv_program, _fv_font), end='')",
            )
        )
        + "\n"
    )
