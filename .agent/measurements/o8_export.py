# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Export the tracked sandbox observer or the production wrapper for the Node replay."""

import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from webui.paste_in.observe import OBSERVER_SOURCE  # noqa: E402


def main() -> None:
    if sys.argv[1:] == ["observer"]:
        sys.stdout.write(OBSERVER_SOURCE)
    elif sys.argv[1:] == ["wrapper"]:
        wrapper_code = import_module("webui.paste_in.filter").wrapper_code
        sys.stdout.write(wrapper_code(sys.stdin.read()))
    else:
        message = "mode must be observer or wrapper"
        raise SystemExit(message)


if __name__ == "__main__":
    main()
