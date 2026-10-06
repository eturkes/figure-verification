# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Failure-eval entry point -- `python -m bench`.

Drives the running verifier (and, for provenance, the model backend's /models + /health) over
HTTP and writes two artifacts: a report.json (the guarantee block plus observational rates) and a
details.jsonl (one row per prompt). Exits non-zero only on an INVALID run -- the guarantee
violated (a bad golden accepted, a good golden rejected, or transport errors) or NOT exercised
(either corpus short or off-identity), a prompt-policy refusal, a harness-side bad request, or no
judgeable reply collected -- never because the weak model failed prompts (that is expected).
Gate-dependent: it needs both servers up (see bench/README.md for the run recipe); the harness
build itself is gate-free.
"""

import argparse
import hashlib
import logging
import math
import shutil
import subprocess
from pathlib import Path
from typing import Literal, assert_never

import httpx

from bench.harness import (
    DATASET_MODE,
    FORMULA_MODE,
    BenchMode,
    Report,
    RunProvenance,
    encode_details,
    encode_report,
    fetch_backend_provenance,
    fetch_model_name,
    run_eval,
)
from bench.prompts import FORMULA_PROMPTS, PROMPTS, Prompt

_LOGGER = logging.getLogger(__name__)

_DEFAULT_VERIFIER_URL = "http://127.0.0.1:8000"
_DEFAULT_MODEL_URL = "http://127.0.0.1:8001/v1"
_DEFAULT_EXAMPLES_DIR = "examples"
_DEFAULT_OUT = "bench/reports/report.json"
_DEFAULT_DETAILS = "bench/reports/details.jsonl"
_DEFAULT_TIMEOUT = 180.0
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "vplot-0.1.schema.json"
_FORMULA_SCHEMA_PATH = _SCHEMA_PATH.with_name("vplot-formula-0.1.schema.json")

# The corpora are exactly 18 bad + 10 good goldens (examples/index.json). Pinning each count
# makes the guarantee fail LOUD on a missing or truncated corpus, so a short corpus is never
# mistaken for "all goldens judged". Grows only by a conscious edit here.
_EXPECTED_BAD_CORPUS_SIZE = 18
_EXPECTED_GOOD_CORPUS_SIZE = 10
# The SHA-256 IDENTITY of each corpus (sorted filename + content-hash pairs; see bench's
# _corpus_digest). Pinning identity, not just size, stops the guarantee passing vacuously against
# a wrong --examples-dir that happens to hold same-sized sets of other specs
# F1). Recompute here after any deliberate corpus edit (tests/test_bench_harness.py re-derives
# both from the tree, so a drift fails the portable gate too).
_EXPECTED_BAD_CORPUS_DIGEST = "da1dfbff5d974fa53255d2e6b826040d2d5c3825d642a79f6efdb626b4366940"
_EXPECTED_GOOD_CORPUS_DIGEST = "72b15d1cb95b8e21440c2b6c5413a37298b3060f8d423bfe5e63f825e518f245"
# Formula mode's corpora (examples/formula_{bad,good}_specs), pinned the same way.
_EXPECTED_FORMULA_BAD_CORPUS_SIZE = 20
_EXPECTED_FORMULA_GOOD_CORPUS_SIZE = 6
_EXPECTED_FORMULA_BAD_CORPUS_DIGEST = (
    "57e6118702c1a065e2d7f96d23eac76c9f02772e55e33dd842e50f9f699b4bce"
)
_EXPECTED_FORMULA_GOOD_CORPUS_DIGEST = (
    "79702b19ea19cdb093df0f857a4b17f1d66ccab4cf25cfaf6e9810cfa0abdbac"
)
_MODES: dict[str, tuple[BenchMode, tuple[Prompt, ...]]] = {
    "dataset": (DATASET_MODE, PROMPTS),
    "formula": (FORMULA_MODE, FORMULA_PROMPTS),
}


def _expected_pins(mode: Literal["dataset", "formula"]) -> tuple[int, str, int, str]:
    """(bad size, bad digest, good size, good digest) the mode's guarantee must exercise."""
    match mode:
        case "dataset":
            return (
                _EXPECTED_BAD_CORPUS_SIZE,
                _EXPECTED_BAD_CORPUS_DIGEST,
                _EXPECTED_GOOD_CORPUS_SIZE,
                _EXPECTED_GOOD_CORPUS_DIGEST,
            )
        case "formula":
            return (
                _EXPECTED_FORMULA_BAD_CORPUS_SIZE,
                _EXPECTED_FORMULA_BAD_CORPUS_DIGEST,
                _EXPECTED_FORMULA_GOOD_CORPUS_SIZE,
                _EXPECTED_FORMULA_GOOD_CORPUS_DIGEST,
            )
        case _:
            assert_never(mode)


def _schema_digest(path: Path = _SCHEMA_PATH) -> str | None:
    """Digest one of bench's own committed schema files in backend-compatible form."""
    try:
        schema_bytes = path.read_bytes()
    except OSError:
        return None
    return "sha256:" + hashlib.sha256(schema_bytes).hexdigest()


def _git_provenance() -> tuple[str | None, bool]:
    """Return this checkout's HEAD and tracked-or-untracked dirty state, best-effort.

    Best-effort literally: an OSError launching git (binary gone after which(), fork/ENOMEM)
    degrades to (None, False) rather than aborting the run. `git status` forces
    --untracked-files=normal so an ambient status.showUntrackedFiles=no cannot suppress the
    untracked signal and mislabel a dirty tree as clean.
    """
    git = shutil.which("git")
    if git is None:
        return (None, False)
    try:
        commit = subprocess.run(  # noqa: S603 — fixed argv, which()-resolved git
            [git, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        status = subprocess.run(  # noqa: S603 — fixed argv, which()-resolved git
            [git, "status", "--porcelain", "--untracked-files=normal"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return (None, False)
    git_commit = (commit.stdout.strip() or None) if commit.returncode == 0 else None
    git_dirty = status.returncode == 0 and bool(status.stdout.strip())
    return (git_commit, git_dirty)


def _positive_seconds(token: str) -> float:
    """Admit a finite, strictly positive timeout; every other client path carries this guard."""
    seconds = float(token)
    if not math.isfinite(seconds) or seconds <= 0:
        msg = f"timeout must be a finite positive number of seconds, got {token!r}"
        raise argparse.ArgumentTypeError(msg)
    return seconds


def _parse_args() -> argparse.Namespace:
    """Parse the harness CLI; every argument has a loopback-default so a bare run works."""
    parser = argparse.ArgumentParser(
        prog="bench",
        description="Run the failure eval against a running verifier and model backend.",
    )
    parser.add_argument("--verifier-url", default=_DEFAULT_VERIFIER_URL, help="verifier base URL")
    parser.add_argument("--model-url", default=_DEFAULT_MODEL_URL, help="model backend /v1 URL")
    parser.add_argument(
        "--examples-dir", default=_DEFAULT_EXAMPLES_DIR, help="golden-corpora root (bad + good)"
    )
    parser.add_argument("--out", default=_DEFAULT_OUT, help="report.json output path")
    parser.add_argument("--details", default=_DEFAULT_DETAILS, help="details.jsonl output path")
    parser.add_argument(
        "--timeout", type=_positive_seconds, default=_DEFAULT_TIMEOUT, help="HTTP timeout (s)"
    )
    parser.add_argument(
        "--mode",
        choices=tuple(_MODES),
        default="dataset",
        help="proposer route: dataset (/propose-spec) or formula (/propose-formula)",
    )
    return parser.parse_args()


def _log_summary(report: Report, out_path: Path, details_path: Path) -> None:
    """Log provenance, guarantee, observations, top failures, and written paths."""
    meta = report.meta
    short_commit = meta.git_commit[:7] if meta.git_commit is not None else None
    _LOGGER.info("PROVENANCE mode=%s", meta.mode)
    _LOGGER.info("PROVENANCE git_commit=%s git_dirty=%s", short_commit, meta.git_dirty)
    _LOGGER.info("PROVENANCE vplot_schema_sha256=%s", meta.vplot_schema_sha256)
    _LOGGER.info("PROVENANCE model_probe_url=%s", meta.model_probe_url)
    if meta.backend is not None:
        backend = meta.backend
        _LOGGER.info(
            "PROVENANCE backend model_name=%s device=%s structured_output=%s "
            "vplot_schema_sha256=%s",
            backend.model_name,
            backend.device,
            backend.structured_output,
            backend.vplot_schema_sha256,
        )
        if (
            meta.vplot_schema_sha256 is not None
            and backend.vplot_schema_sha256 is not None
            and meta.vplot_schema_sha256 != backend.vplot_schema_sha256
        ):
            _LOGGER.warning(
                "PROVENANCE schema mismatch: bench=%s backend=%s",
                meta.vplot_schema_sha256,
                backend.vplot_schema_sha256,
            )
    else:
        _LOGGER.warning(
            "PROVENANCE backend unavailable: no /health provenance from %s", meta.model_probe_url
        )

    guarantee = report.guarantee
    overall = report.observations.overall
    _LOGGER.info(
        "GUARANTEE bad_corpus size=%d false_accept=%d transport_errors=%d",
        guarantee.bad_corpus_size,
        guarantee.bad_corpus_false_accept_count,
        guarantee.bad_corpus_transport_errors,
    )
    _LOGGER.info(
        "GUARANTEE good_corpus size=%d false_reject=%d transport_errors=%d",
        guarantee.good_corpus_size,
        guarantee.good_corpus_false_reject_count,
        guarantee.good_corpus_transport_errors,
    )
    bad_size, bad_digest, good_size, good_digest = _expected_pins(meta.mode)
    for label, size, expected_size, digest, expected_digest in (
        ("bad", guarantee.bad_corpus_size, bad_size, guarantee.bad_corpus_digest, bad_digest),
        ("good", guarantee.good_corpus_size, good_size, guarantee.good_corpus_digest, good_digest),
    ):
        if size != expected_size:
            _LOGGER.warning(
                "GUARANTEE NOT EXERCISED: %s-corpus size %d != expected %d (invalid run)",
                label,
                size,
                expected_size,
            )
        if digest != expected_digest:
            _LOGGER.warning(
                "GUARANTEE NOT EXERCISED: %s-corpus digest mismatch (wrong corpus; invalid run)",
                label,
            )
    _LOGGER.info(
        "OBSERVATIONS n=%d json_object=%.4f json_validity=%.4f verified_render=%.4f",
        overall.n,
        overall.json_object_rate,
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
        "faults off_request=%d prompt_policy=%d upstream_fault=%d harness_error=%d",
        overall.off_request_count,
        overall.prompt_policy_count,
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
    """1: guarantee broken/unexercised, pre-generation refusal, harness error, or no 200.

    Broken = a bad golden verified (false accept) OR a good golden failed (false reject) OR
    transport errors kept a golden unjudged. "Not exercised" = either corpus size or identity
    digest does not match the real goldens, so a vacuous guarantee (an empty/truncated corpus,
    or a wrong --examples-dir -- even one holding same-sized sets of other specs) never passes as
    satisfied. A weak model merely failing prompts stays a valid run (exit 0).
    """
    guarantee = report.guarantee
    overall = report.observations.overall
    bad_size, bad_digest, good_size, good_digest = _expected_pins(report.meta.mode)
    invalid = (
        guarantee.bad_corpus_size != bad_size
        or guarantee.bad_corpus_digest != bad_digest
        or guarantee.bad_corpus_false_accept_count > 0
        or guarantee.bad_corpus_transport_errors > 0
        or guarantee.good_corpus_size != good_size
        or guarantee.good_corpus_digest != good_digest
        or guarantee.good_corpus_false_reject_count > 0
        or guarantee.good_corpus_transport_errors > 0
        or overall.prompt_policy_count > 0
        or overall.harness_error_count > 0
        or overall.n == 0
    )
    return 1 if invalid else 0


def main() -> int:
    """Run the eval, write both artifacts, log the summary, and return the process exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()
    mode, prompts = _MODES[args.mode]
    git_commit, git_dirty = _git_provenance()
    with httpx.Client(timeout=args.timeout) as client:
        served_model = fetch_model_name(client, args.model_url)
        provenance = RunProvenance(
            git_commit=git_commit,
            git_dirty=git_dirty,
            vplot_schema_sha256=_schema_digest(),
            formula_schema_sha256=_schema_digest(_FORMULA_SCHEMA_PATH),
            model_probe_url=args.model_url,
            backend=fetch_backend_provenance(client, args.model_url),
        )
        report, records = run_eval(
            client,
            args.verifier_url,
            Path(args.examples_dir),
            served_model,
            prompts,
            provenance,
            mode,
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
