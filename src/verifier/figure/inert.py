# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Untrusted text made inert for display: program, chart and CSV text (M21.1 F1).

Open WebUI renders a reply as markdown, so a raw name could open an HTML block, a link, emphasis or
KaTeX math under the verdict. A code span is the one construct its renderer never parses inside:
marked lexes the span whole before any extension sees it. So a quoted name is one code span, and
its characters show as they are, an invisible one as a visible symbol.
"""

import re
import unicodedata

_HIDDEN = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})
_TICKS = re.compile("`+")


def visible(character: str) -> str:
    """A character that would draw nothing, or reorder the text around it, as a visible symbol."""
    if character == "\t" or unicodedata.category(character) not in _HIDDEN:
        return character
    code = ord(character)
    if code < 0x20:  # noqa: PLR2004 - the C0 controls map onto U+2400-U+241F
        return chr(0x2400 + code)
    return "\N{SYMBOL FOR DELETE}" if code == 0x7F else "\N{REPLACEMENT CHARACTER}"  # noqa: PLR2004


def code(text: str) -> str:
    """`text` as one markdown code span that shows exactly its characters.

    A line break would end the paragraph and free the rest, so it shows as a symbol. The fence is
    one backtick longer than any run inside. CommonMark drops one space at each end of a span that
    has one at both, and a backtick beside the fence would lengthen it, so either case gets a pad
    space on each side. An empty span would leave a bare fence that pairs with a later one: it
    shows as one space instead.
    """
    shown = "".join(map(visible, text)) or " "
    fence = "`" * (1 + max(map(len, _TICKS.findall(shown)), default=0))
    spaced = shown[0] == shown[-1] == " " and shown.strip(" ") != ""
    pad = " " if spaced or "`" in (shown[0], shown[-1]) else ""
    return f"{fence}{pad}{shown}{pad}{fence}"
