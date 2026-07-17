# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Service + operator-audit entry point — ``python -m verifier.service [audit ...]``.

With no arguments, reads trusted config, builds the app, and serves it with one uvicorn worker.
``audit ATTEMPT_ID`` dispatches the owner-local signed-attempt audit without starting a server.
"""

import sys
from collections.abc import Sequence

import uvicorn

from verifier.service.app import create_app
from verifier.service.audit import main as audit_main
from verifier.service.settings import Settings


def main(argv: Sequence[str] = ()) -> int:
    """Dispatch operator audit, or build the app and serve it when ``argv`` is empty."""
    if argv:
        if argv[0] == "audit":
            return audit_main(tuple(argv[1:]))
        message = "usage: python -m verifier.service [audit ATTEMPT_ID [--reveal-sensitive]]"
        raise SystemExit(message)
    settings = Settings.from_env()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        workers=1,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(tuple(sys.argv[1:])))
