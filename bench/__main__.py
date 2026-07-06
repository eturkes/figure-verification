# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Failure-eval entry point -- `python -m bench` (M3.4a).

Drives the running verifier (and, for provenance, the model backend's /models) over HTTP and
writes two artifacts: a report.json (the guarantee block plus observational rates) and a
details.jsonl (one row per prompt). Exits non-zero only on an INVALID run -- the guarantee
violated or NOT exercised (a short/empty bad corpus), a harness-side bad request, or no judgeable
reply collected -- never because the weak model failed prompts (that is the expected observation).
Gate-dependent: it needs both servers up (see bench/README.md for the run recipe); the harness
build itself is gate-free.
"""

import argparse
import logging
from pathlib import Path

import httpx

from bench.harness import Report, encode_details, encode_report, fetch_model_name, run_eval
from bench.prompts import PROMPTS

_LOGGER = logging.getLogger(__name__)

_DEFAULT_VERIFIER_URL = "http://127.0.0.1:8000"
_DEFAULT_MODEL_URL = "http://127.0.0.1:8001/v1"
_DEFAULT_EXAMPLES_DIR = "examples"
_DEFAULT_OUT = "bench/reports/report.json"
_DEFAULT_DETAILS = "bench/reports/details.jsonl"
_DEFAULT_TIMEOUT = 180.0

# The M1 bad-corpus is exactly 18 goldens (examples/index.json bad_specs). Pinning the count makes
# the guarantee fail LOUD on a missing or truncated corpus, so a short corpus is never mistaken
# for "all bad goldens blocked". Grows only by a conscious edit here.
_EXPECTED_BAD_CORPUS_SIZE = 18
# The SHA-256 IDENTITY of those 18 goldens (sorted filename + content-hash pairs; see bench's
# _corpus_digest). Pinning identity, not just size, stops the guarantee passing vacuously against a
# wrong --examples-dir that happens to hold 18 other invalid specs (codex-review M3.4b F1).
# Recompute here after any deliberate bad-corpus edit.
_EXPECTED_BAD_CORPUS_DIGEST = "063cbc7bc11c2c6913b7da6a164a45268cf22e6a59b2d0325f9a3f3a79afca4e"


def _parse_args() -> argparse.Namespace:
    """Parse the harness CLI; every argument has a loopback-default so a bare run works."""
    parser = argparse.ArgumentParser(
        prog="bench",
        description="Run the failure eval against a running verifier and model backend.",
    )
    parser.add_argument("--verifier-url", default=_DEFAULT_VERIFIER_URL, help="verifier base URL")
    parser.add_argument("--model-url", default=_DEFAULT_MODEL_URL, help="model backend /v1 URL")
    parser.add_argument("--examples-dir", default=_DEFAULT_EXAMPLES_DIR, help="bad-corpus dir")
    parser.add_argument("--out", default=_DEFAULT_OUT, help="report.json output path")
    parser.add_argument("--details", default=_DEFAULT_DETAILS, help="details.jsonl output path")
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT, help="HTTP timeout (s)")
    return parser.parse_args()


def _log_summary(report: Report, out_path: Path, details_path: Path) -> None:
    """Log the guarantee line, headline rates, top failing checks, and the written paths."""
    guarantee = report.guarantee
    overall = report.observations.overall
    _LOGGER.info(
        "GUARANTEE bad_corpus size=%d false_accept=%d transport_errors=%d",
        guarantee.bad_corpus_size,
        guarantee.bad_corpus_false_accept_count,
        guarantee.bad_corpus_transport_errors,
    )
    if guarantee.bad_corpus_size != _EXPECTED_BAD_CORPUS_SIZE:
        _LOGGER.warning(
            "GUARANTEE NOT EXERCISED: bad-corpus size %d != expected %d (invalid run)",
            guarantee.bad_corpus_size,
            _EXPECTED_BAD_CORPUS_SIZE,
        )
    if guarantee.bad_corpus_digest != _EXPECTED_BAD_CORPUS_DIGEST:
        _LOGGER.warning(
            "GUARANTEE NOT EXERCISED: bad-corpus digest mismatch (wrong corpus; invalid run)",
        )
    _LOGGER.info(
        "OBSERVATIONS n=%d tool_call=%.4f json_validity=%.4f verified_render=%.4f",
        overall.n,
        overall.tool_call_rate,
        overall.json_validity_rate,
        overall.verified_render_rate,
    )
    _LOGGER.info(
        "failure rates schema=%.4f semantic=%.4f policy=%.4f",
        overall.schema_failure_rate,
        overall.semantic_failure_rate,
        overall.policy_failure_rate,
    )
    _LOGGER.info(
        "faults off_request=%d upstream_fault=%d harness_error=%d",
        overall.off_request_count,
        overall.upstream_fault_count,
        overall.harness_error_count,
    )
    for mode in report.observations.top_failure_modes:
        _LOGGER.info("top failing check %s (%d)", mode.check, mode.count)
    shape = report.observations.reply_shape
    _LOGGER.info(
        "reply shape fenced=%d bare_object=%d empty=%d other=%d defenced_json_valid=%d",
        shape.fenced,
        shape.bare_object,
        shape.empty,
        shape.other,
        shape.defenced_json_valid,
    )
    _LOGGER.info("wrote report=%s details=%s", out_path, details_path)


def _exit_code(report: Report) -> int:
    """1 on an invalid run: guarantee broken or NOT exercised, a harness bad request, or no 200.

    "Not exercised" = the bad-corpus size is not 18 OR its identity digest does not match the real
    M1 goldens, so a vacuous guarantee (an empty/truncated corpus, or a wrong --examples-dir -- even
    one holding 18 other invalid specs) never passes as satisfied. A weak model merely failing
    prompts stays a valid run (exit 0).
    """
    guarantee = report.guarantee
    overall = report.observations.overall
    invalid = (
        guarantee.bad_corpus_size != _EXPECTED_BAD_CORPUS_SIZE
        or guarantee.bad_corpus_digest != _EXPECTED_BAD_CORPUS_DIGEST
        or guarantee.bad_corpus_false_accept_count > 0
        or guarantee.bad_corpus_transport_errors > 0
        or overall.harness_error_count > 0
        or overall.n == 0
    )
    return 1 if invalid else 0


def main() -> int:
    """Run the eval, write both artifacts, log the summary, and return the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()
    with httpx.Client(timeout=args.timeout) as client:
        served_model = fetch_model_name(client, args.model_url)
        report, records = run_eval(
            client, args.verifier_url, Path(args.examples_dir), served_model, PROMPTS
        )
    out_path = Path(args.out)
    details_path = Path(args.details)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(encode_report(report))
    details_path.write_bytes(encode_details(records))
    _log_summary(report, out_path, details_path)
    return _exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
