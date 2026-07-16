# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Service entry point — `python -m verifier.service` (M2.1).

Reads trusted config from the environment, builds the app, and serves it with a single
uvicorn worker bound to the configured host (loopback by default). One worker keeps the
in-memory artifact store coherent and makes the process-local admission gate service-global;
the signing identity is persistent state loaded before serving.
"""

import uvicorn

from verifier.service.app import create_app
from verifier.service.settings import Settings


def main() -> None:
    """Build the app from the environment and serve it (blocking)."""
    settings = Settings.from_env()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        workers=1,
    )


if __name__ == "__main__":
    main()
