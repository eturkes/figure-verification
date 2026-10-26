# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Provisioner settings — operator config for the Open WebUI harness.

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
    is pinned here (in _FIXED_ENV or a derived key), so the config is complete on its own -- the
    signing key aside, which signing_key() reads or creates in the data dir.
  - child_env() is what the launcher actually execs: launch_env() + signing_key() overlaid on a
    CURATED minimal base (only the process vars the child needs -- PATH / HOME / locale),
    everything else in os.environ DROPPED. This is the hermetic boundary -- a bare
    {**os.environ, **launch_env()} would leak any axis launch_env does not pin (aiohttp reads
    HTTP_PROXY via trust_env; transport / SSL knobs are unbounded). The launcher
    (webui/__main__.py) execs os.execve(bin, argv, child_env()).

Persistent-config is OFF (env-over-DB every boot), so runtime config lives in env, never the OWUI
DB. The admin user + repo-owned global filter are DB-persisted provisioning state (bootstrap).
Endpoint settings accept only canonical, ambiguity-free URLs for this stack's fixed
origin and /v1 joins; the bind/client host is a separate bare ASCII hostname. Defaults bind
loopback only -- OWUI on 8080, the model backend's OpenAI /v1 on 8001 -- the admin_password is a
loopback dev default an operator overrides, and the signing key is random per data dir. All names
and defaults were verified against open-webui 0.10.2, 0.11.3 + 0.12.3 source (config.py / env.py).
This package is an out-of-tree harness like model_backend: coverage-excluded, unshipped, importing
only gate-venv deps.
"""

import json
import math
import os
import re
import secrets
from pathlib import Path
from typing import Literal, Self, TypeAlias, cast, get_args
from urllib.parse import urlparse

import msgspec

from model_backend.origin import loopback

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8080
_DEFAULT_DATA_DIR = ".webui-data"
# Loopback dev defaults, overridable via WEBUI_PROVISION_*: the whole stack binds loopback, so a
# fixed password is acceptable for the PoC harness (S105 flags the literal, not a leak).
_DEFAULT_ADMIN_NAME = "operator"
_DEFAULT_ADMIN_EMAIL = "operator@localhost"
_DEFAULT_ADMIN_PASSWORD = "loopback-dev-password"  # noqa: S105
_DEFAULT_MODEL_BACKEND_URL = "http://127.0.0.1:8001/v1"
_DEFAULT_MODEL_ID = "Qwen2.5-Coder-0.5B-Instruct"
_DEFAULT_WEBUI_BIN = ".venv-webui/bin/open-webui"
# request_timeout bounds each provisioning REST call; ready_timeout bounds the /ready poll for a
# cold OWUI boot (~7-10s here, so 60s leaves wide headroom).
_DEFAULT_REQUEST_TIMEOUT = 30.0
_DEFAULT_READY_TIMEOUT = 60.0
# Named to dodge PLR2004 (magic-value comparison) in the port bound.
_MAX_PORT = 65535
# RFC 7518 requires an HS256 key at least as wide as its 256-bit hash, and PyJWT warns on every
# encode/decode when given a shorter value.
_MIN_SECRET_KEY_BYTES = 32
# The instance's own signing key, beside its DB (OWUI's own `serve` keeps one in its cwd instead).
_SECRET_KEY_FILE = ".webui_secret_key"  # noqa: S105

# URL values are concatenated with fixed consumer paths by Open WebUI. Require one canonical,
# browser/client-unambiguous form: an ASCII host[:port] authority (IPv6 brackets allowed), no
# userinfo/backslash/percent/control/unicode authority bytes, and the exact endpoint path expected
# by this local stack. host is both a uvicorn bind value and the bootstrap-client hostname, so it
# uses the same ASCII subset without a port (port is its own Settings field).
_CLEAN_AUTHORITY = re.compile(r"[A-Za-z0-9._:\[\]-]+")
_CLEAN_HOST = re.compile(r"[A-Za-z0-9._-]+")

# The provisioned paste-in tool: python mode is the demo's ONE operation (.agent/spec.md § Decisions
# demo shape). The id must be a lower-case Python identifier -- OWUI rejects anything else and
# lower-cases what it accepts (routers/tools.py). name + description are ADMIN-facing workspace
# labels; the string the MODEL reads is the method docstring inside the artifact.
_TOOL_ID = "figure_verification"
_TOOL_NAME = "Figure Verification"
_TOOL_DESCRIPTION = "Draws a chart from a Python program and an attached CSV file."
# The one model-visible callable the artifact exposes: `Tools.draw_figure` (webui/paste_in/tool.py).
_TOOL_OPERATION_ID = "draw_figure"

# Which generated pair bootstrap provisions: the demo's (substitution anchoring, the bare-source
# template its adapter wraps) or production's (strict anchoring, the `draw_figure` transport
# paragraph), for a proposer that calls tools itself (the launcher's `--codex` arm).
PasteIn: TypeAlias = Literal["demo", "production"]
# Open WebUI's DEFAULT_MODEL_PARAMS `function_calling`. Legacy (prompt-template): the weak model's
# tool selection runs inline in the chat request, and native FC is gated on the UI event emitter so
# it does not execute headless (.agent/archive/m4.md); the one-shot headless flow needs legacy.
# Native = Open WebUI's own default + production's: the model returns OpenAI `tool_calls`.
FunctionCalling: TypeAlias = Literal["legacy", "native"]
_PASTE_INS: tuple[PasteIn, ...] = get_args(PasteIn)
_FUNCTION_CALLINGS: tuple[FunctionCalling, ...] = get_args(FunctionCalling)

# The Open WebUI environment launch_env() emits verbatim, independent of any Settings field. OWUI
# compares booleans as os.getenv(...).lower() == "true" (config.py / env.py), so "false" disables
# and "true" enables regardless of case. child_env() layers these pins over a curated process base;
# ambient Open WebUI config never enters the child.
_FIXED_ENV: dict[str, str] = {
    # Config lives in env, never the DB: with persistent-config off, every boot reads these env
    # values and UI/REST config edits do not stick (the whole provisioning model).
    "ENABLE_PERSISTENT_CONFIG": "false",
    # Hermetic isolation: no outbound network, no ~90MB embedding-model download, no version ping.
    "OFFLINE_MODE": "true",
    "RAG_EMBEDDING_ENGINE": "openai",
    # OWUI's offline upload otherwise calls its remote embedding endpoint before chat begins.
    "BYPASS_EMBEDDING_AND_RETRIEVAL": "true",
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
    # cannot inject one) and it falls back to the chat model (headless-tool contract).
    "TASK_MODEL": "",
    "TASK_MODEL_EXTERNAL": "",
    # Determinism: every post-chat background LLM call off, or the backend request count is
    # nondeterministic. All five generation toggles default to True in OWUI 0.12.3, so each is
    # pinned (autocomplete already defaults off and never fires on the headless path).
    "ENABLE_TITLE_GENERATION": "false",
    "ENABLE_TAGS_GENERATION": "false",
    "ENABLE_FOLLOW_UP_GENERATION": "false",
    "ENABLE_RETRIEVAL_QUERY_GENERATION": "false",
    "ENABLE_SEARCH_QUERY_GENERATION": "false",
    # Attack surface off: no code execution / interpreter, evaluation arena, community sharing, or
    # message rating (all but the arena default on in 0.12.3).
    "ENABLE_CODE_EXECUTION": "false",
    "ENABLE_CODE_INTERPRETER": "false",
    "ENABLE_EVALUATION_ARENA_MODELS": "false",
    "ENABLE_COMMUNITY_SHARING": "false",
    "ENABLE_MESSAGE_RATING": "false",
    # Auth + bootstrap login model pinned so the override-only merge cannot let ambient rewrite the
    # signup / signin path bootstrap depends on. WEBUI_AUTH on (ambient off disables auth);
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
    # The repo-owned global outlet filter must run on API chat completions. This currently defaults
    # true upstream, but it is load-bearing behavior, so the canonical env pins it instead of
    # silently inheriting a version-sensitive default.
    "ENABLE_API_OUTLET_FILTERS": "true",
}


# The process-level vars the OWUI child legitimately inherits (child_env passthrough allowlist):
# enough to find the interpreter / libraries and localize, nothing that steers OWUI config,
# networking, or auth. Everything else in os.environ is dropped so no unpinned axis leaks past
# launch_env(). Extend only when a live smoke proves a var is genuinely needed.
_BASE_ENV_PASSTHROUGH = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "TZ")


def _require_http_url(name: str, value: str, *, path: str) -> None:
    """Fail closed unless value is one canonical http(s) endpoint with the exact path.

    model_backend_url is emitted into the OWUI env, where a blank or scheme-less value fails OPEN
    not loud: OWUI rewrites an empty OpenAI base-url to https://api.openai.com/v1 (config.py).
    Query/fragment/path confusion, userinfo, and browser-reinterpreted authority bytes likewise
    corrupt the fixed `/models` and `/chat/completions` joins, so a misconfigured deploy must raise
    here instead of surfacing at first request.
    """
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:  # malformed authority (bad IPv6 literal / non-numeric or out-of-range port)
        endpoint_ok = False
    else:
        endpoint_ok = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and _CLEAN_AUTHORITY.fullmatch(parsed.netloc) is not None
            and (port is None or port >= 1)
            and parsed.path == path
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and value == f"{parsed.scheme}://{parsed.netloc}{path}"
        )
    if not endpoint_ok:
        shape = f"ending in {path!r}" if path else "with no path"
        msg = f"{name} must be a clean http(s) endpoint {shape}, got {value!r}"
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
    # None = the data dir's own random key (signing_key()).
    secret_key: str | None = None
    admin_name: str = _DEFAULT_ADMIN_NAME
    admin_email: str = _DEFAULT_ADMIN_EMAIL
    admin_password: str = _DEFAULT_ADMIN_PASSWORD
    model_backend_url: str = _DEFAULT_MODEL_BACKEND_URL
    model_id: str = _DEFAULT_MODEL_ID
    webui_bin: Path = Path(_DEFAULT_WEBUI_BIN)
    request_timeout: float = _DEFAULT_REQUEST_TIMEOUT
    ready_timeout: float = _DEFAULT_READY_TIMEOUT
    paste_in: PasteIn = "demo"
    function_calling: FunctionCalling = "legacy"

    def __post_init__(self) -> None:
        # A port outside 1..65535 cannot bind. The two validation loops below MUST use distinct item
        # names (text / seconds): a shared name unifies mypy to the first loop's str, breaking
        # math.isfinite on the float loop.
        if not 1 <= self.port <= _MAX_PORT:
            msg = f"port must be in 1..{_MAX_PORT}, got {self.port}"
            raise ValueError(msg)
        # PyJWT warns below the RFC 7518 HS256 key minimum; enforce it at the operator boundary
        # rather than admitting a boot that only reports the defect in logs.
        if self.secret_key is not None and len(self.secret_key.encode()) < _MIN_SECRET_KEY_BYTES:
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
        # Closed sets: from_env passes the raw env text through, and an unknown pair or mode would
        # otherwise provision the demo pair silently or hand Open WebUI a mode it reads as native.
        if self.paste_in not in _PASTE_INS:
            msg = f"paste_in must be one of {_PASTE_INS}, got {self.paste_in!r}"
            raise ValueError(msg)
        if self.function_calling not in _FUNCTION_CALLINGS:
            msg = (
                f"function_calling must be one of {_FUNCTION_CALLINGS}, "
                f"got {self.function_calling!r}"
            )
            raise ValueError(msg)
        # model_backend_url reaches fixed OWUI joins; host backs both its bind argv and the
        # bootstrap base_url. Validate their complete syntax so malformed values fail here, not as
        # a misdirected request or invalid client URL downstream (see the helper).
        _require_http_url("model_backend_url", self.model_backend_url, path="/v1")
        if _CLEAN_HOST.fullmatch(self.host) is None:
            msg = (
                "host must be a bare ASCII hostname without scheme, path, or port, "
                f"got {self.host!r}"
            )
            raise ValueError(msg)
        # The default password is published: off loopback, anyone signs in as the admin, and an
        # Open WebUI admin runs Python on this host through Functions.
        if not loopback(self.host) and self.admin_password == _DEFAULT_ADMIN_PASSWORD:
            msg = f"host {self.host!r} is not loopback: set a fresh WEBUI_PROVISION_ADMIN_PASSWORD"
            raise ValueError(msg)

    @property
    def base_url(self) -> str:
        """The loopback origin the provisioning REST client targets OWUI at."""
        return f"http://{self.host}:{self.port}"

    @property
    def tool_id(self) -> str:
        """The provisioned paste-in tool's OWUI id; bootstrap converges the row under it."""
        return _TOOL_ID

    @property
    def tool_name(self) -> str:
        """The workspace label an admin reads beside the provisioned tool."""
        return _TOOL_NAME

    @property
    def tool_description(self) -> str:
        """The workspace description an admin reads beside the provisioned tool."""
        return _TOOL_DESCRIPTION

    @property
    def tool_operation_id(self) -> str:
        """The one callable the artifact publishes to the model."""
        return _TOOL_OPERATION_ID

    def launch_env(self) -> dict[str, str]:
        """The Open WebUI config env to exec open-webui with (layered over the launcher base env).

        Reads no os.environ; DATA_DIR resolves against the process cwd, so the dict is a function of
        this Settings and the cwd (a test recomputes the same resolve). The four derived keys
        complete _FIXED_ENV per-instance -- an absolute DATA_DIR (OWUI resolves a relative one
        against its own cwd, so absolute keeps state in .webui-data regardless of exec cwd), both
        OpenAI base-url forms, and the function-calling mode. WEBUI_SECRET_KEY joins in child_env().
        """
        return {
            **_FIXED_ENV,
            "DATA_DIR": str(self.data_dir.resolve()),
            "OPENAI_API_BASE_URL": self.model_backend_url,
            "OPENAI_API_BASE_URLS": self.model_backend_url,
            "DEFAULT_MODEL_PARAMS": json.dumps({"function_calling": self.function_calling}),
        }

    def signing_key(self) -> str:
        """The key OWUI signs session tokens with: the operator's, else the data dir's own.

        The data dir's key is created with it (random, mode 0600) and wiped with it, so a cookie
        never outlives its instance: OWUI 0.12.3 answers `/api/config` 401 for a token that
        decodes but names a user its DB no longer holds (main.py get_app_config -> utils/mfa.py
        get_auth), and its frontend then shows "Open WebUI Backend Required" until the browser
        drops the cookie. Under a new key the old token fails to decode, which OWUI reads as
        signed out.
        """
        if self.secret_key is not None:
            return self.secret_key
        path = self.data_dir / _SECRET_KEY_FILE
        if not path.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
            # A crash before the write leaves a short key, which the check below refuses.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="ascii") as file:
                file.write(secrets.token_urlsafe(_MIN_SECRET_KEY_BYTES))
        key = path.read_text(encoding="utf-8")
        if len(key.encode()) < _MIN_SECRET_KEY_BYTES:
            msg = f"{path} must hold at least {_MIN_SECRET_KEY_BYTES} UTF-8 bytes; delete it"
            raise ValueError(msg)
        return key

    def child_env(self) -> dict[str, str]:
        """The full hermetic environment to exec open-webui with: a curated base + launch_env().

        Unlike launch_env() (pure OWUI config), this reads os.environ -- but ONLY the process vars
        the child needs (_BASE_ENV_PASSTHROUGH: PATH / HOME / locale / TMPDIR / TZ) -- then overlays
        launch_env() + the signing key (which may create the data dir's key file). Every ambient var
        outside that allowlist is DROPPED, so nothing the harness did not choose (a stray
        HTTP_PROXY, a WEBUI_* / OPENAI_* leftover) reaches OWUI. The launcher execs
        os.execve(bin, argv, settings.child_env()).
        """
        base = {k: os.environ[k] for k in _BASE_ENV_PASSTHROUGH if k in os.environ}
        return {**base, **self.launch_env(), "WEBUI_SECRET_KEY": self.signing_key()}

    @classmethod
    def from_env(cls) -> Self:
        """Build from WEBUI_PROVISION_* env vars, falling back to the field defaults."""
        env = os.environ
        return cls(
            host=env.get("WEBUI_PROVISION_HOST", _DEFAULT_HOST),
            port=int(env.get("WEBUI_PROVISION_PORT", str(_DEFAULT_PORT))),
            data_dir=Path(env.get("WEBUI_PROVISION_DATA_DIR", _DEFAULT_DATA_DIR)),
            secret_key=env.get("WEBUI_PROVISION_SECRET_KEY"),
            admin_name=env.get("WEBUI_PROVISION_ADMIN_NAME", _DEFAULT_ADMIN_NAME),
            admin_email=env.get("WEBUI_PROVISION_ADMIN_EMAIL", _DEFAULT_ADMIN_EMAIL),
            admin_password=env.get("WEBUI_PROVISION_ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD),
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
            paste_in=cast("PasteIn", env.get("WEBUI_PROVISION_PASTE_IN", "demo")),
            function_calling=cast(
                "FunctionCalling", env.get("WEBUI_PROVISION_FUNCTION_CALLING", "legacy")
            ),
        )
