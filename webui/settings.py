# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Provisioner settings — operator config for the Open WebUI harness (M4.3a).

A frozen container built from WEBUI_PROVISION_* env, mirroring the verifier / model_backend
Settings pattern: field defaults and from_env fallbacks share one set of _DEFAULT_* constants (no
drift), and __post_init__ rejects out-of-range bounds so a misconfigured deploy fails closed.

Two env namespaces meet here, kept strictly apart:
  - WEBUI_PROVISION_* is the INPUT this container reads (from_env) -- how the operator points the
    harness at the verifier, the model backend, and the OWUI binary, plus the admin bootstrap.
  - launch_env() is the OUTPUT this container EMITS: the canonical Open WebUI environment the
    launcher execs open-webui with. The launcher merges it OVERRIDE-ONLY as {**os.environ,
    **launch_env()}, so every OWUI-read axis must be pinned here (in _FIXED_ENV or a derived key)
    or an ambient value leaks into the deterministic harness. launch_env() reads no os.environ, so
    its whole output is a pure function of this Settings -- fully assertable in a test.

Persistent-config is OFF (env-over-DB every boot), so config lives in env, never the OWUI DB: the
one DB-persisted provisioning act is the admin signup (bootstrap, M4.3b). Defaults bind loopback
only -- OWUI on 8080, the verifier on 8000, the model backend's OpenAI /v1 on 8001 -- and the
secret_key / admin_password are loopback dev defaults an operator overrides. All names and defaults
were verified against open-webui 0.10.2 source (config.py / env.py). This package is an out-of-tree
harness like model_backend and bench: coverage-excluded, unshipped, importing only gate-venv deps.
"""

import json
import math
import os
from pathlib import Path
from typing import Self

import msgspec

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8080
_DEFAULT_DATA_DIR = ".webui-data"
# Loopback dev defaults, overridable via WEBUI_PROVISION_*: the whole stack binds loopback, so a
# fixed secret / password is acceptable for the PoC harness (S105 flags the literal, not a leak).
_DEFAULT_SECRET_KEY = "loopback-dev-secret-key"  # noqa: S105
_DEFAULT_ADMIN_NAME = "operator"
_DEFAULT_ADMIN_EMAIL = "operator@localhost"
_DEFAULT_ADMIN_PASSWORD = "loopback-dev-password"  # noqa: S105
_DEFAULT_VERIFIER_URL = "http://127.0.0.1:8000"
_DEFAULT_MODEL_BACKEND_URL = "http://127.0.0.1:8001/v1"
_DEFAULT_MODEL_ID = "Qwen2-0.5B-Instruct-int4-sym-ov"
_DEFAULT_WEBUI_BIN = ".venv-webui/bin/open-webui"
# request_timeout bounds each provisioning REST call; ready_timeout bounds the /ready poll for a
# cold OWUI boot (~7-10s here, so 60s leaves wide headroom).
_DEFAULT_REQUEST_TIMEOUT = 30.0
_DEFAULT_READY_TIMEOUT = 60.0
# Named to dodge PLR2004 (magic-value comparison) in the port bound.
_MAX_PORT = 65535

# The verifier tool-server registration OWUI reads from TOOL_SERVER_CONNECTIONS. The id becomes the
# OWUI tool group "server:<id>"; the name is the readback label (memory M4 Provisioning-SETTLED-
# LIVE). The verifier's OpenAPI lives at schema/openapi.json; proposeSpec is the one exposed op.
_TOOL_SERVER_ID = "verifier"
_TOOL_SERVER_NAME = "Figure Verifier"
_TOOL_SERVER_DESCRIPTION = (
    "Independently recomputes and verifies chart specs, then renders a certified figure."
)
_TOOL_SERVER_PATH = "schema/openapi.json"
_PROPOSE_OPERATION_ID = "proposeSpec"

# The Open WebUI environment launch_env() emits verbatim, independent of any Settings field. OWUI
# compares booleans as os.getenv(...).lower() == "true" (config.py / env.py), so "false" disables
# and "true" enables regardless of case. Every axis is pinned because the launcher merges this
# override-only over os.environ -- an unpinned key would let an ambient value leak in.
_FIXED_ENV: dict[str, str] = {
    # Config lives in env, never the DB: with persistent-config off, every boot reads these env
    # values and UI/REST config edits do not stick (the whole provisioning model, memory M4).
    "ENABLE_PERSISTENT_CONFIG": "false",
    # Hermetic isolation: no outbound network, no ~90MB embedding-model download, no version ping.
    "OFFLINE_MODE": "true",
    "RAG_EMBEDDING_ENGINE": "openai",
    "ENABLE_VERSION_UPDATE_CHECK": "false",
    # Backend wiring: the OpenAI-compatible model backend only, Ollama off. The base-url is
    # completed per-instance in launch_env() (both singular and plural forms, since the plural
    # overrides the singular in OWUI); a non-empty key is required or OWUI omits the auth header.
    "ENABLE_OPENAI_API": "true",
    "ENABLE_OLLAMA_API": "false",
    "OPENAI_API_KEY": "dummy",
    "OPENAI_API_KEYS": "dummy",
    "OPENAI_API_CONFIGS": "{}",
    # No task model: title / tag / query generation runs on the task model, so pin it empty (ambient
    # cannot inject one) and it falls back to the chat model (memory M4 Provisioning).
    "TASK_MODEL": "",
    "TASK_MODEL_EXTERNAL": "",
    # Determinism: every post-chat background LLM call off, or the backend request count is
    # nondeterministic. All five generation toggles default to True in OWUI 0.10.2, so each is
    # pinned (autocomplete already defaults off and never fires on the headless path).
    "ENABLE_TITLE_GENERATION": "false",
    "ENABLE_TAGS_GENERATION": "false",
    "ENABLE_FOLLOW_UP_GENERATION": "false",
    "ENABLE_RETRIEVAL_QUERY_GENERATION": "false",
    "ENABLE_SEARCH_QUERY_GENERATION": "false",
    # Attack surface off: no code execution / interpreter, evaluation arena, community sharing, or
    # message rating (all default on in 0.10.2).
    "ENABLE_CODE_EXECUTION": "false",
    "ENABLE_CODE_INTERPRETER": "false",
    "ENABLE_EVALUATION_ARENA_MODELS": "false",
    "ENABLE_COMMUNITY_SHARING": "false",
    "ENABLE_MESSAGE_RATING": "false",
    # Legacy (prompt-template) function calling: the weak model's tool selection runs inline in the
    # chat request. Native FC is gated on the UI event emitter and does not execute headless
    # (memory M4), so the one-shot headless flow needs legacy.
    "DEFAULT_MODEL_PARAMS": '{"function_calling": "legacy"}',
}


class Settings(msgspec.Struct, frozen=True, kw_only=True):
    """Immutable provisioner configuration. See the module docstring for the trust note."""

    host: str = _DEFAULT_HOST
    port: int = _DEFAULT_PORT
    data_dir: Path = Path(_DEFAULT_DATA_DIR)
    secret_key: str = _DEFAULT_SECRET_KEY
    admin_name: str = _DEFAULT_ADMIN_NAME
    admin_email: str = _DEFAULT_ADMIN_EMAIL
    admin_password: str = _DEFAULT_ADMIN_PASSWORD
    verifier_url: str = _DEFAULT_VERIFIER_URL
    model_backend_url: str = _DEFAULT_MODEL_BACKEND_URL
    model_id: str = _DEFAULT_MODEL_ID
    webui_bin: Path = Path(_DEFAULT_WEBUI_BIN)
    request_timeout: float = _DEFAULT_REQUEST_TIMEOUT
    ready_timeout: float = _DEFAULT_READY_TIMEOUT

    def __post_init__(self) -> None:
        # A port outside 1..65535 cannot bind. The two validation loops below MUST use distinct item
        # names (text / seconds): a shared name unifies mypy to the first loop's str, breaking
        # math.isfinite on the float loop.
        if not 1 <= self.port <= _MAX_PORT:
            msg = f"port must be in 1..{_MAX_PORT}, got {self.port}"
            raise ValueError(msg)
        # Each hard-breaks OWUI when empty: an empty WEBUI_SECRET_KEY is fatal under auth (env.py),
        # and an empty admin email / password breaks signup and signin (bootstrap).
        for name, text in (
            ("secret_key", self.secret_key),
            ("admin_email", self.admin_email),
            ("admin_password", self.admin_password),
        ):
            if not text:
                msg = f"{name} must be non-empty"
                raise ValueError(msg)
        # httpx does not validate its timeout: 0 times out every request immediately, a negative is
        # an undefined deadline, inf hangs unbounded, nan raises at request time and slips a bare
        # <= 0 check. float() parses "inf"/"nan" from env, so require a finite value > 0.
        for name, seconds in (
            ("request_timeout", self.request_timeout),
            ("ready_timeout", self.ready_timeout),
        ):
            if not math.isfinite(seconds) or seconds <= 0:
                msg = f"{name} must be a finite value > 0, got {seconds}"
                raise ValueError(msg)

    @property
    def base_url(self) -> str:
        """The loopback origin the provisioning REST client targets OWUI at."""
        return f"http://{self.host}:{self.port}"

    @property
    def tool_server_id(self) -> str:
        """The verifier tool-server id; OWUI exposes its tools under group "server:<id>"."""
        return _TOOL_SERVER_ID

    def tool_server_connections(self) -> str:
        """The TOOL_SERVER_CONNECTIONS env value: a one-element JSON array registering the verifier.

        Shape is the settled-live 0.10.2 connection (memory M4 Provisioning-SETTLED-LIVE): OWUI
        fetches {url}/{path} as OpenAPI, exposes only the proposeSpec op (the allowlist), and needs
        config.enable truthy or the server is skipped.
        """
        connection = {
            "url": self.verifier_url,
            "path": _TOOL_SERVER_PATH,
            "type": "openapi",
            "auth_type": "none",
            "key": "",
            "config": {
                "enable": True,
                "function_name_filter_list": [_PROPOSE_OPERATION_ID],
            },
            "info": {
                "id": self.tool_server_id,
                "name": _TOOL_SERVER_NAME,
                "description": _TOOL_SERVER_DESCRIPTION,
            },
        }
        return json.dumps([connection])

    def launch_env(self) -> dict[str, str]:
        """The canonical Open WebUI env to exec open-webui with (override-only over os.environ).

        Pure: reads no os.environ, so the whole dict is a function of this Settings. The five
        derived keys complete _FIXED_ENV per-instance -- an absolute DATA_DIR (OWUI resolves a
        relative one against its own cwd, so absolute keeps state in .webui-data regardless of
        exec cwd), the secret, both OpenAI base-url forms, and the tool-server registration.
        """
        return {
            **_FIXED_ENV,
            "DATA_DIR": str(self.data_dir.resolve()),
            "WEBUI_SECRET_KEY": self.secret_key,
            "OPENAI_API_BASE_URL": self.model_backend_url,
            "OPENAI_API_BASE_URLS": self.model_backend_url,
            "TOOL_SERVER_CONNECTIONS": self.tool_server_connections(),
        }

    @classmethod
    def from_env(cls) -> Self:
        """Build from WEBUI_PROVISION_* env vars, falling back to the field defaults."""
        env = os.environ
        return cls(
            host=env.get("WEBUI_PROVISION_HOST", _DEFAULT_HOST),
            port=int(env.get("WEBUI_PROVISION_PORT", str(_DEFAULT_PORT))),
            data_dir=Path(env.get("WEBUI_PROVISION_DATA_DIR", _DEFAULT_DATA_DIR)),
            secret_key=env.get("WEBUI_PROVISION_SECRET_KEY", _DEFAULT_SECRET_KEY),
            admin_name=env.get("WEBUI_PROVISION_ADMIN_NAME", _DEFAULT_ADMIN_NAME),
            admin_email=env.get("WEBUI_PROVISION_ADMIN_EMAIL", _DEFAULT_ADMIN_EMAIL),
            admin_password=env.get("WEBUI_PROVISION_ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD),
            verifier_url=env.get("WEBUI_PROVISION_VERIFIER_URL", _DEFAULT_VERIFIER_URL),
            model_backend_url=env.get(
                "WEBUI_PROVISION_MODEL_BACKEND_URL", _DEFAULT_MODEL_BACKEND_URL
            ),
            model_id=env.get("WEBUI_PROVISION_MODEL_ID", _DEFAULT_MODEL_ID),
            webui_bin=Path(env.get("WEBUI_PROVISION_WEBUI_BIN", _DEFAULT_WEBUI_BIN)),
            request_timeout=float(
                env.get("WEBUI_PROVISION_REQUEST_TIMEOUT", str(_DEFAULT_REQUEST_TIMEOUT))
            ),
            ready_timeout=float(
                env.get("WEBUI_PROVISION_READY_TIMEOUT", str(_DEFAULT_READY_TIMEOUT))
            ),
        )
