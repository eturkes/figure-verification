# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Backend entry point — `python -m model_backend`.

Reads MODEL_BACKEND_* config, loads the model, and serves the OpenAI /v1 surface with a single
uvicorn worker (loopback by default). One worker keeps the single loaded model and its lock
coherent. Requires the isolated .venv-model runtime project and an accelerator settings.device
resolves to — hardware-gated, NOT the portable uv gate (run recipe:
model_backend/runtime/README.md).
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
