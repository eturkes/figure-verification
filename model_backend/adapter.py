# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The demo adapter's generation parameters and fence reader (demo transport, M10.6).

The demo's 0.5B proposer answers the selector turn with bare source text; the adapter in `app.py`
de-fences it and wraps the program as one `draw_figure` call. The production proposer calls the
tool itself and needs none of this.
"""

import re
from typing import Final

# The backend's own ceiling (`settings._DEFAULT_MAX_TOKENS`); greedy decoding.
ADAPTER_MAX_TOKENS: Final = 512
ADAPTER_TEMPERATURE: Final = 0.0

_FENCE_OPEN_RE: Final = re.compile(r"^[ \t]*```[^\n]*(?:\n|\Z)", re.MULTILINE)
_FENCE_CLOSE_RE: Final = re.compile(r"^[ \t]*```[ \t]*$", re.MULTILINE)


def defence(content: str) -> tuple[bool, str]:
    """Return (fenced, inner block): the program inside the first Markdown fence, else the text.

    An opening fence with no closing one yields the remainder (a truncated reply keeps its
    program). The opener must be the FIRST fence marker in the reply: a closer answering the
    search first would open an empty block and discard the program.
    """
    opened = _FENCE_OPEN_RE.search(content)
    if opened is None or content.find("```") < opened.start():
        return (False, content)
    rest = content[opened.end() :]
    closed = _FENCE_CLOSE_RE.search(rest)
    return (True, rest if closed is None else rest[: closed.start()])
