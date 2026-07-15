# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Backend entry point — `python -m model_backend` (M3.1b).

Reads MODEL_BACKEND_* config, compiles the model, and serves the OpenAI /v1 surface with a
single uvicorn worker (loopback by default). One worker keeps the single compiled pipeline and
its lock coherent. Requires the intel-accel env sourced and the OpenVINO PYTHONPATH present —
hardware-gated, NOT the portable uv gate (authoritative run recipe: bench/README.md).
"""

import uvicorn

from model_backend.app import create_app
from model_backend.settings import Settings


def main() -> None:
    """Build the app from the environment and serve it (blocking)."""
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, workers=1)


if __name__ == "__main__":
    main()
