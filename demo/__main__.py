# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Entry point for the hardware-free hardening walkthrough: ``python -m demo``."""

import logging
from pathlib import Path

from demo.walkthrough import encode_report, run_walkthrough

_LOGGER = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parent.parent
_REPORT_PATH = _ROOT / "demo" / "reports" / "report.json"


def _configure_logging() -> None:
    """Keep the walkthrough readable even when Litestar configures process-wide logging."""
    logging.basicConfig(level=logging.CRITICAL, force=True)
    formatter = logging.Formatter("%(levelname)s %(message)s")
    for logger in (logging.getLogger("demo"), _LOGGER):
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def main() -> int:
    """Run all scenarios, write the JSON report, and fail if any scenario failed."""
    _configure_logging()
    report = run_walkthrough()
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_bytes(encode_report(report))
    _LOGGER.info("wrote report=%s", _REPORT_PATH.relative_to(_ROOT))
    _LOGGER.info("demo walkthrough: %d/%d scenarios PASS", report.passed, report.total)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
