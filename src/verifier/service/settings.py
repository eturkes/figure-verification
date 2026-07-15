# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Trusted operator configuration for transport, verification, and resource policy.

`Settings` is an immutable startup snapshot, never request-decoded. `from_env` is the sole
ambient-environment boundary. Field defaults and its fallbacks share constants; core defaults
come directly from `DEFAULT_LIMITS`.

M5 resource policy: all resource integers are exact positive signed-64-bit values
(`model_sample_rows` alone admits zero). This common arithmetic domain protects later native and
SQLite boundaries and rejects astronomical values without allocating against them. `limits` is
eagerly derived and cannot be supplied independently, so every service stage receives one frozen
`VerificationLimits` snapshot. Cache budgets admit one conservatively bounded item: render =
attestation + both route-specific spec-input ceilings; chart = HTML. Sums are checked for overflow.

`public_base_url` is the absolute browser-facing origin used in chart `Location`, separate from
the bind host. Its ASCII authority allowlist and exact origin round-trip reject browser/parser
differentials (userinfo, backslash, escapes, controls, IDN, or appended path/query/fragment).
"""

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from verifier.limits import DEFAULT_LIMITS, VerificationLimits

_DEFAULT_DATA_DIR = "data"
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_DEFAULT_MAX_BODY_BYTES = 64 * 1024
_DEFAULT_STORE_CAP = 256
_DEFAULT_HTML_CAP = 16

_DEFAULT_MODEL_BASE_URL = "http://127.0.0.1:8001/v1"
_DEFAULT_MODEL_NAME = "Qwen2-0.5B-Instruct-int4-sym-ov"
_DEFAULT_MODEL_TIMEOUT = 120.0
_DEFAULT_MODEL_SAMPLE_ROWS = 5
_DEFAULT_MODEL_MAX_TOKENS = 512
_DEFAULT_MAX_USER_REQUEST_BYTES = 4 * 1024
_DEFAULT_MAX_PROMPT_BYTES = 32 * 1024
_DEFAULT_MAX_MODEL_RESPONSE_BYTES = 128 * 1024

_DEFAULT_RENDER_CACHE_BYTES = 32 * 1024 * 1024
_DEFAULT_CHART_CACHE_BYTES = 128 * 1024 * 1024
_DEFAULT_MAX_ACTIVE_JOBS = 2
_DEFAULT_WORK_RATE_PER_MINUTE = 120
_DEFAULT_WORK_BURST = 120

_MAX_RESOURCE_INTEGER = 2**63 - 1
_CLEAN_AUTHORITY = re.compile(r"[A-Za-z0-9._:\[\]-]+")
_POSITIVE_RESOURCE_FIELDS = (
    "max_body_bytes",
    "store_cap",
    "html_cap",
    "model_max_tokens",
    "max_user_request_bytes",
    "max_prompt_bytes",
    "max_model_response_bytes",
    "render_cache_bytes",
    "chart_cache_bytes",
    "max_active_jobs",
    "work_rate_per_minute",
    "work_burst",
    *DEFAULT_LIMITS.__struct_fields__,
)


def _require_resource_integer(name: str, value: int, *, minimum: int = 1) -> None:
    if type(value) is not int or not minimum <= value <= _MAX_RESOURCE_INTEGER:
        msg = f"{name} must be an integer in {minimum}..{_MAX_RESOURCE_INTEGER}, got {value!r}"
        raise ValueError(msg)


def _checked_resource_sum(name: str, left: int, right: int) -> int:
    if left > _MAX_RESOURCE_INTEGER - right:
        msg = f"{name} exceeds the signed-64-bit resource ceiling"
        raise ValueError(msg)
    return left + right


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    """Immutable service policy; direct construction and `from_env` share all validation."""

    data_dir: Path
    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    public_base_url: str | None = None
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES
    store_cap: int = _DEFAULT_STORE_CAP
    html_cap: int = _DEFAULT_HTML_CAP

    model_base_url: str = _DEFAULT_MODEL_BASE_URL
    model_name: str = _DEFAULT_MODEL_NAME
    model_timeout: float = _DEFAULT_MODEL_TIMEOUT
    model_sample_rows: int = _DEFAULT_MODEL_SAMPLE_ROWS
    model_max_tokens: int = _DEFAULT_MODEL_MAX_TOKENS
    max_user_request_bytes: int = _DEFAULT_MAX_USER_REQUEST_BYTES
    max_prompt_bytes: int = _DEFAULT_MAX_PROMPT_BYTES
    max_model_response_bytes: int = _DEFAULT_MAX_MODEL_RESPONSE_BYTES

    render_cache_bytes: int = _DEFAULT_RENDER_CACHE_BYTES
    chart_cache_bytes: int = _DEFAULT_CHART_CACHE_BYTES
    max_active_jobs: int = _DEFAULT_MAX_ACTIVE_JOBS
    work_rate_per_minute: int = _DEFAULT_WORK_RATE_PER_MINUTE
    work_burst: int = _DEFAULT_WORK_BURST

    max_csv_bytes: int = DEFAULT_LIMITS.max_csv_bytes
    max_manifest_bytes: int = DEFAULT_LIMITS.max_manifest_bytes
    max_manifest_columns: int = DEFAULT_LIMITS.max_manifest_columns
    max_source_rows: int = DEFAULT_LIMITS.max_source_rows
    max_source_cells: int = DEFAULT_LIMITS.max_source_cells
    max_plotted_cells: int = DEFAULT_LIMITS.max_plotted_cells
    max_eval_work_units: int = DEFAULT_LIMITS.max_eval_work_units
    max_render_rows: int = DEFAULT_LIMITS.max_render_rows
    max_smt_terms: int = DEFAULT_LIMITS.max_smt_terms
    max_vega_bytes: int = DEFAULT_LIMITS.max_vega_bytes
    max_svg_bytes: int = DEFAULT_LIMITS.max_svg_bytes
    max_html_bytes: int = DEFAULT_LIMITS.max_html_bytes
    max_attestation_bytes: int = DEFAULT_LIMITS.max_attestation_bytes
    smt_timeout_ms: int = DEFAULT_LIMITS.smt_timeout_ms

    limits: VerificationLimits = field(init=False, repr=False)

    def __post_init__(self) -> None:
        base = self.public_base_url
        if base is None:
            base = f"http://{_DEFAULT_HOST}:{self.port}"
            object.__setattr__(self, "public_base_url", base)
        try:
            parsed = urlparse(base)
            _ = parsed.port
        except ValueError:
            origin_ok = False
        else:
            origin_ok = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and _CLEAN_AUTHORITY.fullmatch(parsed.netloc) is not None
                and base == f"{parsed.scheme}://{parsed.netloc}"
            )
        if not origin_ok:
            msg = f"public_base_url must be a clean http(s) origin, got {base!r}"
            raise ValueError(msg)

        for name in _POSITIVE_RESOURCE_FIELDS:
            _require_resource_integer(name, getattr(self, name))
        _require_resource_integer("model_sample_rows", self.model_sample_rows, minimum=0)
        if not math.isfinite(self.model_timeout) or self.model_timeout <= 0:
            msg = f"model_timeout must be a finite value > 0, got {self.model_timeout}"
            raise ValueError(msg)

        limits = VerificationLimits(
            max_csv_bytes=self.max_csv_bytes,
            max_manifest_bytes=self.max_manifest_bytes,
            max_manifest_columns=self.max_manifest_columns,
            max_source_rows=self.max_source_rows,
            max_source_cells=self.max_source_cells,
            max_plotted_cells=self.max_plotted_cells,
            max_eval_work_units=self.max_eval_work_units,
            max_render_rows=self.max_render_rows,
            max_smt_terms=self.max_smt_terms,
            max_vega_bytes=self.max_vega_bytes,
            max_svg_bytes=self.max_svg_bytes,
            max_html_bytes=self.max_html_bytes,
            max_attestation_bytes=self.max_attestation_bytes,
            smt_timeout_ms=self.smt_timeout_ms,
        )
        object.__setattr__(self, "limits", limits)

        max_spec_bytes = _checked_resource_sum(
            "render cache spec input bound",
            self.max_body_bytes,
            self.max_model_response_bytes,
        )
        max_render_item = _checked_resource_sum(
            "render cache item bound", self.max_attestation_bytes, max_spec_bytes
        )
        if self.render_cache_bytes < max_render_item:
            msg = (
                "render_cache_bytes must admit max_attestation_bytes plus both spec-input "
                f"ceilings ({max_render_item}), got {self.render_cache_bytes}"
            )
            raise ValueError(msg)
        if self.chart_cache_bytes < self.max_html_bytes:
            msg = (
                "chart_cache_bytes must be >= max_html_bytes "
                f"({self.max_html_bytes}), got {self.chart_cache_bytes}"
            )
            raise ValueError(msg)

    @classmethod
    def from_env(cls) -> Self:
        """Build from `VERIFIER_*`; this is the service's only ambient read."""
        env = os.environ

        def integer(name: str, default: int) -> int:
            return int(env.get(name, str(default)))

        return cls(
            data_dir=Path(env.get("VERIFIER_DATA_DIR", _DEFAULT_DATA_DIR)),
            host=env.get("VERIFIER_HOST", _DEFAULT_HOST),
            port=integer("VERIFIER_PORT", _DEFAULT_PORT),
            public_base_url=env.get("VERIFIER_PUBLIC_BASE_URL"),
            max_body_bytes=integer("VERIFIER_MAX_BODY_BYTES", _DEFAULT_MAX_BODY_BYTES),
            store_cap=integer("VERIFIER_STORE_CAP", _DEFAULT_STORE_CAP),
            html_cap=integer("VERIFIER_HTML_CAP", _DEFAULT_HTML_CAP),
            model_base_url=env.get("VERIFIER_MODEL_BASE_URL", _DEFAULT_MODEL_BASE_URL),
            model_name=env.get("VERIFIER_MODEL_NAME", _DEFAULT_MODEL_NAME),
            model_timeout=float(env.get("VERIFIER_MODEL_TIMEOUT", str(_DEFAULT_MODEL_TIMEOUT))),
            model_sample_rows=integer("VERIFIER_MODEL_SAMPLE_ROWS", _DEFAULT_MODEL_SAMPLE_ROWS),
            model_max_tokens=integer("VERIFIER_MODEL_MAX_TOKENS", _DEFAULT_MODEL_MAX_TOKENS),
            max_user_request_bytes=integer(
                "VERIFIER_MAX_USER_REQUEST_BYTES", _DEFAULT_MAX_USER_REQUEST_BYTES
            ),
            max_prompt_bytes=integer("VERIFIER_MAX_PROMPT_BYTES", _DEFAULT_MAX_PROMPT_BYTES),
            max_model_response_bytes=integer(
                "VERIFIER_MAX_MODEL_RESPONSE_BYTES", _DEFAULT_MAX_MODEL_RESPONSE_BYTES
            ),
            render_cache_bytes=integer("VERIFIER_RENDER_CACHE_BYTES", _DEFAULT_RENDER_CACHE_BYTES),
            chart_cache_bytes=integer("VERIFIER_CHART_CACHE_BYTES", _DEFAULT_CHART_CACHE_BYTES),
            max_active_jobs=integer("VERIFIER_MAX_ACTIVE_JOBS", _DEFAULT_MAX_ACTIVE_JOBS),
            work_rate_per_minute=integer(
                "VERIFIER_WORK_RATE_PER_MINUTE", _DEFAULT_WORK_RATE_PER_MINUTE
            ),
            work_burst=integer("VERIFIER_WORK_BURST", _DEFAULT_WORK_BURST),
            max_csv_bytes=integer("VERIFIER_MAX_CSV_BYTES", DEFAULT_LIMITS.max_csv_bytes),
            max_manifest_bytes=integer(
                "VERIFIER_MAX_MANIFEST_BYTES", DEFAULT_LIMITS.max_manifest_bytes
            ),
            max_manifest_columns=integer(
                "VERIFIER_MAX_MANIFEST_COLUMNS", DEFAULT_LIMITS.max_manifest_columns
            ),
            max_source_rows=integer("VERIFIER_MAX_SOURCE_ROWS", DEFAULT_LIMITS.max_source_rows),
            max_source_cells=integer("VERIFIER_MAX_SOURCE_CELLS", DEFAULT_LIMITS.max_source_cells),
            max_plotted_cells=integer(
                "VERIFIER_MAX_PLOTTED_CELLS", DEFAULT_LIMITS.max_plotted_cells
            ),
            max_eval_work_units=integer(
                "VERIFIER_MAX_EVAL_WORK_UNITS", DEFAULT_LIMITS.max_eval_work_units
            ),
            max_render_rows=integer("VERIFIER_MAX_RENDER_ROWS", DEFAULT_LIMITS.max_render_rows),
            max_smt_terms=integer("VERIFIER_MAX_SMT_TERMS", DEFAULT_LIMITS.max_smt_terms),
            max_vega_bytes=integer("VERIFIER_MAX_VEGA_BYTES", DEFAULT_LIMITS.max_vega_bytes),
            max_svg_bytes=integer("VERIFIER_MAX_SVG_BYTES", DEFAULT_LIMITS.max_svg_bytes),
            max_html_bytes=integer("VERIFIER_MAX_HTML_BYTES", DEFAULT_LIMITS.max_html_bytes),
            max_attestation_bytes=integer(
                "VERIFIER_MAX_ATTESTATION_BYTES", DEFAULT_LIMITS.max_attestation_bytes
            ),
            smt_timeout_ms=integer("VERIFIER_SMT_TIMEOUT_MS", DEFAULT_LIMITS.smt_timeout_ms),
        )
