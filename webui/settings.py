# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Provisioner settings — operator config for the Open WebUI harness (M4.3a).

A frozen container built from WEBUI_PROVISION_* env, mirroring the verifier / model_backend
Settings pattern: field defaults and from_env fallbacks share one set of _DEFAULT_* constants (no
drift), and __post_init__ rejects out-of-range bounds so a misconfigured deploy fails closed.

Two env namespaces meet here, kept strictly apart:
  - WEBUI_PROVISION_* is the INPUT this container reads (from_env) -- how the operator points the
    harness at the verifier, the model backend, and the OWUI binary, plus the admin bootstrap.
  - launch_env() is the Open WebUI config the harness intends -- determinism toggles, backend
    wiring, and the auth / bootstrap login model. It reads no os.environ (DATA_DIR resolves against
    the process cwd, not the environment), so it is a pure function of this Settings and the cwd --
    fully assertable (a test recomputes the same resolve). Every axis the harness has intent about
    is pinned here (in _FIXED_ENV or a derived key), so the config is complete on its own.
  - child_env() is what the launcher actually execs: launch_env() overlaid on a CURATED minimal base
    (only the process vars the child needs -- PATH / HOME / locale), everything else in os.environ
    DROPPED. This is the hermetic boundary -- a bare {**os.environ, **launch_env()} would leak any
    axis launch_env does not pin (aiohttp reads HTTP_PROXY via trust_env; transport / SSL knobs are
    unbounded). The launcher (webui/__main__.py, M4.3d) execs os.execve(bin, argv, child_env()).

Persistent-config is OFF (env-over-DB every boot), so runtime config lives in env, never the OWUI
DB. The admin user + repo-owned global filter are DB-persisted provisioning state (bootstrap,
M4.3b/M4.4c). Defaults bind loopback only -- OWUI on 8080, the verifier on 8000, the model backend's
OpenAI /v1 on 8001 -- and the secret_key / admin_password are loopback dev defaults an operator
overrides. All names and defaults were verified against open-webui 0.10.2 source (config.py /
env.py). This package is an out-of-tree harness like model_backend and bench: coverage-excluded,
unshipped, importing only gate-venv deps.
"""

import json
import math
import os
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

import msgspec

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8080
_DEFAULT_DATA_DIR = ".webui-data"
# Loopback dev defaults, overridable via WEBUI_PROVISION_*: the whole stack binds loopback, so a
# fixed secret / password is acceptable for the PoC harness (S105 flags the literal, not a leak).
# Keep the secret >= 32 UTF-8 bytes: RFC 7518 requires an HS256 key at least as wide as its
# 256-bit hash, and PyJWT warns on every encode/decode when given a shorter value.
_DEFAULT_SECRET_KEY = "loopback-dev-secret-key-for-local-poc"  # noqa: S105
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
_MIN_SECRET_KEY_BYTES = 32

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
# and "true" enables regardless of case. child_env() layers these pins over a curated process base;
# ambient Open WebUI config never enters the child.
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
    # Auth + bootstrap login model pinned so the override-only merge cannot let ambient rewrite the
    # signup / signin path M4.3b depends on. WEBUI_AUTH on (ambient off disables auth);
    # login form + password auth on (each gates signup and signin, routers/auths.py); public signup
    # off (the first admin auto-registers regardless -- auths.py first-user get_num_users==1 -- so
    # this only shuts LATER signups). WEBUI_ADMIN_EMAIL empty defuses the boot-time auto-admin
    # (main.py runs create_admin_user only when WEBUI_ADMIN_EMAIL *and* WEBUI_ADMIN_PASSWORD are
    # set, so the empty email alone short-circuits it -- else ambient seizes the first-admin slot
    # before bootstrap). The trusted-email header empty keeps header-trust auth off (the name header
    # is read only alongside it), so signin stays password-based.
    "WEBUI_AUTH": "true",
    "ENABLE_LOGIN_FORM": "true",
    "ENABLE_PASSWORD_AUTH": "true",
    "ENABLE_SIGNUP": "false",
    "WEBUI_ADMIN_EMAIL": "",
    "WEBUI_AUTH_TRUSTED_EMAIL_HEADER": "",
    # Legacy (prompt-template) function calling: the weak model's tool selection runs inline in the
    # chat request. Native FC is gated on the UI event emitter and does not execute headless
    # (memory M4), so the one-shot headless flow needs legacy.
    "DEFAULT_MODEL_PARAMS": '{"function_calling": "legacy"}',
}


# The process-level vars the OWUI child legitimately inherits (child_env passthrough allowlist):
# enough to find the interpreter / libraries and localize, nothing that steers OWUI config,
# networking, or auth. Everything else in os.environ is dropped so no unpinned axis leaks past
# launch_env(). Extend only if the M4.3e live smoke proves a var is genuinely needed.
_BASE_ENV_PASSTHROUGH = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "TZ")


def _require_http_url(name: str, value: str) -> None:
    """Fail closed unless value is a non-empty http(s) URL carrying a host.

    verifier_url and model_backend_url are emitted into the OWUI env / tool-server JSON, where a
    blank or scheme-less value fails OPEN not loud: OWUI rewrites an empty OpenAI base-url to
    https://api.openai.com/v1 (config.py) and silently drops a tool server whose url will not
    url-join, so a misconfigured deploy must raise here instead of surfacing at first request.
    """
    try:
        parsed = urlparse(value)
    except ValueError as exc:  # malformed authority (bad IPv6 literal / port)
        msg = f"{name} must be an http(s) URL, got {value!r}"
        raise ValueError(msg) from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        msg = f"{name} must be an http(s) URL with a host, got {value!r}"
        raise ValueError(msg)


class Settings(msgspec.Struct, frozen=True, kw_only=True):
    """Immutable provisioner configuration. See the module docstring for the trust note.

    from_env() is the runtime type boundary: it coerces port / timeouts / paths out of str, so
    __post_init__ guards values, not types. Direct construction trusts caller types (msgspec does
    not check them at runtime), matching the model_backend / verifier Settings convention.
    """

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
        # PyJWT warns below the RFC 7518 HS256 key minimum; enforce it at the operator boundary
        # rather than admitting a boot that only reports the defect in logs.
        if len(self.secret_key.encode()) < _MIN_SECRET_KEY_BYTES:
            msg = f"secret_key must be at least {_MIN_SECRET_KEY_BYTES} UTF-8 bytes"
            raise ValueError(msg)
        # Each hard-breaks bootstrap when empty: admin email / password feed signup and signin.
        for name, text in (
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
        # verifier_url / model_backend_url reach OWUI; host backs base_url -- validate each so an
        # empty or malformed value fails closed here, not open downstream (see the helper).
        _require_http_url("verifier_url", self.verifier_url)
        _require_http_url("model_backend_url", self.model_backend_url)
        if not self.host or "/" in self.host:
            msg = f"host must be a bare host without scheme or path, got {self.host!r}"
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
        """The Open WebUI config env to exec open-webui with (layered over the launcher base env).

        Reads no os.environ; DATA_DIR resolves against the process cwd, so the dict is a function of
        this Settings and the cwd (a test recomputes the same resolve). The five derived keys
        complete _FIXED_ENV per-instance -- an absolute DATA_DIR (OWUI resolves a relative one
        against its own cwd, so absolute keeps state in .webui-data regardless of exec cwd), the
        secret, both OpenAI base-url forms, and the tool-server registration.
        """
        return {
            **_FIXED_ENV,
            "DATA_DIR": str(self.data_dir.resolve()),
            "WEBUI_SECRET_KEY": self.secret_key,
            "OPENAI_API_BASE_URL": self.model_backend_url,
            "OPENAI_API_BASE_URLS": self.model_backend_url,
            "TOOL_SERVER_CONNECTIONS": self.tool_server_connections(),
        }

    def child_env(self) -> dict[str, str]:
        """The full hermetic environment to exec open-webui with: a curated base + launch_env().

        Unlike launch_env() (pure OWUI config), this reads os.environ -- but ONLY the process vars
        the child needs (_BASE_ENV_PASSTHROUGH: PATH / HOME / locale / TMPDIR / TZ) -- then overlays
        launch_env(). Every ambient var outside that allowlist is DROPPED, so nothing the harness
        did not choose (a stray HTTP_PROXY, a WEBUI_* / OPENAI_* leftover) reaches OWUI. The
        launcher execs os.execve(bin, argv, settings.child_env()).
        """
        base = {k: os.environ[k] for k in _BASE_ENV_PASSTHROUGH if k in os.environ}
        return {**base, **self.launch_env()}

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
