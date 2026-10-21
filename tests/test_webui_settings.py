# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Feedback loop for the Open WebUI provisioner settings.

webui/ is a coverage-excluded harness, not part of the verifier claim, so these are a bench-style
regression net rather than a 100%-branch gate. Locked here:

- every fail-closed bound (__post_init__): port range, >=32-byte operator secret, non-empty admin
  email / password, finite-positive request and ready timeouts, an http(s) model-backend URL,
  bare host;
- launch_env() as the canonical hermetic OWUI env -- it is exactly _FIXED_ENV plus the four
  per-instance derived keys and stays independent of ambient os.environ; child_env() layers it over
  only the curated process base + the signing key (the operator's, else the data dir's own);
- the function-calling mode: legacy by default, byte-equal to the pre-`--codex` pin, native on
  request; the provisioned pair + mode refuse any value outside their closed sets;
- the load-bearing _FIXED_ENV values (persistent-config off, empty task model, every
  background-generation toggle off, API outlet filters on, plus the auth / bootstrap login model
  -- auth on, password login, public signup off, no boot auto-admin, no trusted-header) pinned
  directly, so a flip fails;
- the provisioned paste-in tool's identity (id / name / description / operation id), stated as
  literals because the id is what OWUI rows the tool under and what bootstrap attaches;
- from_env() default and WEBUI_PROVISION_* override across int / str / Path / float fields.
"""

import json
import math
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from model_backend.settings import _DEFAULT_MODEL_NAME as _BACKEND_MODEL_NAME
from webui.settings import _FIXED_ENV, FunctionCalling, PasteIn, Settings

# The two-tier model identity: model_backend SERVES this name on /v1/models and webui SELECTS it as
# OWUI's completion model, so the two are held equal and stated here as a literal.
_SERVED_MODEL_NAME = "Qwen2.5-Coder-0.5B-Instruct"

_PROVISION_ENV_VARS = (
    "WEBUI_PROVISION_HOST",
    "WEBUI_PROVISION_PORT",
    "WEBUI_PROVISION_DATA_DIR",
    "WEBUI_PROVISION_SECRET_KEY",
    "WEBUI_PROVISION_ADMIN_NAME",
    "WEBUI_PROVISION_ADMIN_EMAIL",
    "WEBUI_PROVISION_ADMIN_PASSWORD",
    "WEBUI_PROVISION_MODEL_BACKEND_URL",
    "WEBUI_PROVISION_MODEL_ID",
    "WEBUI_PROVISION_WEBUI_BIN",
    "WEBUI_PROVISION_REQUEST_TIMEOUT",
    "WEBUI_PROVISION_READY_TIMEOUT",
    "WEBUI_PROVISION_PASTE_IN",
    "WEBUI_PROVISION_FUNCTION_CALLING",
)

_DERIVED_ENV_KEYS = frozenset(
    {
        "DATA_DIR",
        "OPENAI_API_BASE_URL",
        "OPENAI_API_BASE_URLS",
        "DEFAULT_MODEL_PARAMS",
    }
)

# Each builder trips exactly one __post_init__ bound; the match anchors on the offending field so a
# reordered or dropped check fails here. Builders (not prebuilt Settings) defer construction so the
# raise happens inside pytest.raises.
_BAD_CONFIGS: list[tuple[Callable[[], Settings], str]] = [
    (lambda: Settings(port=0), "port"),
    (lambda: Settings(port=65536), "port"),
    (lambda: Settings(secret_key=""), "secret_key"),
    (lambda: Settings(secret_key="x" * 31), "secret_key"),
    (lambda: Settings(admin_email=""), "admin_email"),
    (lambda: Settings(admin_password=""), "admin_password"),
    (lambda: Settings(request_timeout=0.0), "request_timeout"),
    (lambda: Settings(request_timeout=-1.0), "request_timeout"),
    (lambda: Settings(request_timeout=math.inf), "request_timeout"),
    (lambda: Settings(request_timeout=math.nan), "request_timeout"),
    (lambda: Settings(ready_timeout=0.0), "ready_timeout"),
    (lambda: Settings(ready_timeout=math.inf), "ready_timeout"),
    (lambda: Settings(ready_timeout=math.nan), "ready_timeout"),
    (lambda: Settings(model_backend_url=""), "model_backend_url"),
    (lambda: Settings(model_backend_url="http://"), "model_backend_url"),
    (lambda: Settings(model_backend_url="http://127.0.0.1:8001"), "model_backend_url"),
    (lambda: Settings(model_backend_url="http://127.0.0.1:8001/v1/"), "model_backend_url"),
    (lambda: Settings(model_backend_url="http://127.0.0.1:bad/v1"), "model_backend_url"),
    (lambda: Settings(model_backend_url="http://127.0.0.1:8001/v1#fragment"), "model_backend_url"),
    (
        lambda: Settings(model_backend_url="https://trusted.example@evil.example/v1"),
        "model_backend_url",
    ),
    (lambda: Settings(host=""), "host"),
    (lambda: Settings(host="http://127.0.0.1"), "host"),
    (lambda: Settings(host="127.0.0.1:9000"), "host"),
    (lambda: Settings(host="bad host"), "host"),
    (lambda: Settings(host="host\\name"), "host"),
    (lambda: Settings(paste_in=cast("PasteIn", "Production")), "paste_in"),
    (lambda: Settings(paste_in=cast("PasteIn", "")), "paste_in"),
    (lambda: Settings(function_calling=cast("FunctionCalling", "native ")), "function_calling"),
    (lambda: Settings(function_calling=cast("FunctionCalling", "default")), "function_calling"),
]


@pytest.mark.parametrize(("build", "match"), _BAD_CONFIGS)
def test_rejects_bad_config(build: Callable[[], Settings], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        build()


def test_defaults_construct() -> None:
    settings = Settings()
    assert settings.base_url == "http://127.0.0.1:8080"
    # Hand-stated, never read off the production constant: OWUI selects the completion model by
    # this exact id (webui/client.py:380) and bootstrap refuses an id the backend does not
    # advertise, so a drift from model_backend's served name breaks launch, not a later request.
    assert settings.model_id == _SERVED_MODEL_NAME


def test_model_identity_agrees_across_the_three_tiers() -> None:
    # Compared against the hand-stated literal, not against each other: a same-value assertion
    # between two production constants passes just as happily when both drift together.
    assert _BACKEND_MODEL_NAME == _SERVED_MODEL_NAME
    assert Settings().model_id == _SERVED_MODEL_NAME


# A host off loopback needs a fresh admin password (M21.1 F6); an operator key is the operator's.
_FRESH_SECRET = "fresh-deployment-secret-of-32-bytes"  # noqa: S105 - a test value
_FRESH_PASSWORD = "fresh-deployment-password"  # noqa: S105 - a test value


def test_accepts_clean_endpoint_authorities() -> None:
    settings = Settings(
        model_backend_url="https://[2001:db8::1]:8443/v1",
        host="webui.local",
        secret_key=_FRESH_SECRET,
        admin_password=_FRESH_PASSWORD,
    )
    assert settings.model_backend_url == "https://[2001:db8::1]:8443/v1"
    assert settings.base_url == "http://webui.local:8080"


def test_secret_key_bound_counts_utf8_bytes() -> None:
    settings = Settings(secret_key="é" * 16)
    assert settings.secret_key is not None
    assert len(settings.secret_key.encode()) == 32


def test_frozen() -> None:
    settings = Settings()
    attr = "port"  # variable name dodges B010 and the mypy frozen guard
    with pytest.raises(AttributeError):
        setattr(settings, attr, 9000)


def test_launch_env_is_fixed_plus_derived() -> None:
    settings = Settings()
    env = settings.launch_env()
    # Every fixed toggle is emitted verbatim (a derived key must not shadow one).
    for key, value in _FIXED_ENV.items():
        assert env[key] == value
    # The four per-instance derived keys; the signing key joins at child_env() alone, since the
    # instance's own key is a file launch_env() never reads.
    assert env["DATA_DIR"] == str(settings.data_dir.resolve())
    assert "WEBUI_SECRET_KEY" not in env
    assert env["OPENAI_API_BASE_URL"] == settings.model_backend_url
    assert env["OPENAI_API_BASE_URLS"] == settings.model_backend_url
    # Byte-equal to the legacy pin _FIXED_ENV carried before the mode became a setting.
    assert env["DEFAULT_MODEL_PARAMS"] == '{"function_calling": "legacy"}'
    native = Settings(function_calling="native").launch_env()["DEFAULT_MODEL_PARAMS"]
    assert json.loads(native) == {"function_calling": "native"}
    # launch_env is exactly _FIXED_ENV plus those four keys, no more, no less.
    # TOOL_SERVER_CONNECTIONS is absent by ruling: a registered tool server is what published the
    # JSON-spec operation, and python mode is the demo's ONE operation, so the registration is
    # removed rather than filtered.
    assert set(env) == set(_FIXED_ENV) | _DERIVED_ENV_KEYS
    assert "TOOL_SERVER_CONNECTIONS" not in env


def test_fixed_env_pins_load_bearing_toggles() -> None:
    assert _FIXED_ENV["ENABLE_PERSISTENT_CONFIG"] == "false"
    assert _FIXED_ENV["TASK_MODEL"] == ""
    assert _FIXED_ENV["TASK_MODEL_EXTERNAL"] == ""
    assert _FIXED_ENV["ENABLE_OPENAI_API"] == "true"
    assert _FIXED_ENV["ENABLE_OLLAMA_API"] == "false"
    assert json.loads(_FIXED_ENV["OPENAI_API_CONFIGS"]) == {}
    # Every background-generation toggle is pinned off for a deterministic backend request count.
    for key in (
        "ENABLE_TITLE_GENERATION",
        "ENABLE_TAGS_GENERATION",
        "ENABLE_FOLLOW_UP_GENERATION",
        "ENABLE_RETRIEVAL_QUERY_GENERATION",
        "ENABLE_SEARCH_QUERY_GENERATION",
    ):
        assert _FIXED_ENV[key] == "false"
    # Auth + bootstrap login model pinned so ambient cannot rewrite the signup / signin path.
    assert _FIXED_ENV["WEBUI_AUTH"] == "true"
    assert _FIXED_ENV["ENABLE_LOGIN_FORM"] == "true"
    assert _FIXED_ENV["ENABLE_PASSWORD_AUTH"] == "true"  # noqa: S105 (config toggle value)
    assert _FIXED_ENV["ENABLE_SIGNUP"] == "false"
    assert _FIXED_ENV["WEBUI_ADMIN_EMAIL"] == ""
    assert _FIXED_ENV["WEBUI_AUTH_TRUSTED_EMAIL_HEADER"] == ""
    assert _FIXED_ENV["ENABLE_API_OUTLET_FILTERS"] == "true"
    assert _FIXED_ENV["BYPASS_EMBEDDING_AND_RETRIEVAL"] == "true"


def test_launch_env_ignores_ambient(monkeypatch: pytest.MonkeyPatch) -> None:
    # launch_env() layers over the launcher base env, so it must emit each axis it pins regardless
    # of ambient. Set hostile ambient across config AND auth; launch_env still returns the pins.
    monkeypatch.setenv("ENABLE_PERSISTENT_CONFIG", "true")
    monkeypatch.setenv("TASK_MODEL", "ambient-task-model")
    monkeypatch.setenv("OPENAI_API_BASE_URL", "http://ambient.example/v1")
    monkeypatch.setenv("WEBUI_AUTH", "false")
    monkeypatch.setenv("ENABLE_PASSWORD_AUTH", "false")
    monkeypatch.setenv("WEBUI_ADMIN_EMAIL", "attacker@evil.test")
    monkeypatch.setenv("WEBUI_AUTH_TRUSTED_EMAIL_HEADER", "X-Trusted-Email")
    monkeypatch.setenv("ENABLE_API_OUTLET_FILTERS", "false")
    settings = Settings()
    env = settings.launch_env()
    assert env["ENABLE_PERSISTENT_CONFIG"] == "false"
    assert env["TASK_MODEL"] == ""
    assert env["OPENAI_API_BASE_URL"] == settings.model_backend_url
    # The auth pins hold against a hostile ambient (no auth-off, no auto-admin, no header-trust).
    assert env["WEBUI_AUTH"] == "true"
    assert env["ENABLE_PASSWORD_AUTH"] == "true"  # noqa: S105 (config toggle value)
    assert env["WEBUI_ADMIN_EMAIL"] == ""
    assert env["WEBUI_AUTH_TRUSTED_EMAIL_HEADER"] == ""
    assert env["ENABLE_API_OUTLET_FILTERS"] == "true"


def test_child_env_drops_ambient_keeps_base(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # child_env() is the hermetic exec env: launch_env() over a curated base. A passthrough var is
    # carried through; an unpinned / hostile ambient var is dropped, never reaching OWUI.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HTTP_PROXY", "http://attacker.example:3128")
    monkeypatch.setenv("WEBUI_AUTH", "false")
    monkeypatch.setenv("WEBUI_SECRET_KEY", "ambient-secret-key-of-at-least-32-bytes")
    settings = Settings(data_dir=tmp_path / "data")
    env = settings.child_env()
    # launch_env() is fully present and its pins win over ambient.
    for key, value in settings.launch_env().items():
        assert env[key] == value
    assert env["PATH"] == "/usr/bin:/bin"  # base passthrough carried
    assert "HTTP_PROXY" not in env  # unpinned ambient dropped (no aiohttp trust_env proxy leak)
    assert env["WEBUI_AUTH"] == "true"  # launch_env pin, not the ambient "false"
    assert env["WEBUI_SECRET_KEY"] == (tmp_path / "data" / ".webui_secret_key").read_text()


def test_the_instance_key_lives_and_dies_with_its_data_dir(tmp_path: Path) -> None:
    """A browser cookie must not outlive its instance: Open WebUI 0.12.3 answers `/api/config` 401
    for a token that still decodes but names a user the DB no longer holds, and its frontend then
    shows "Open WebUI Backend Required" until the cookie is cleared. A key created with the data
    dir, private to its owner, stable across serves and replaced with the data dir, makes every
    cookie of a wiped instance undecodable, so the browser lands on the sign-in page."""
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir)
    key = settings.child_env()["WEBUI_SECRET_KEY"]
    key_file = data_dir / ".webui_secret_key"
    assert key == key_file.read_text()
    assert len(key.encode()) >= 32
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert settings.child_env()["WEBUI_SECRET_KEY"] == key
    assert sorted(path.name for path in data_dir.iterdir()) == [".webui_secret_key"]
    shutil.rmtree(data_dir)
    assert settings.child_env()["WEBUI_SECRET_KEY"] != key
    other = Settings(data_dir=tmp_path / "other").child_env()["WEBUI_SECRET_KEY"]
    assert other not in {key, settings.child_env()["WEBUI_SECRET_KEY"]}


def test_an_existing_instance_key_is_kept(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    kept = "kept-instance-key-written-by-an-earlier-serve"
    (data_dir / ".webui_secret_key").write_text(kept)
    assert Settings(data_dir=data_dir).child_env()["WEBUI_SECRET_KEY"] == kept


def test_a_short_instance_key_is_refused(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / ".webui_secret_key").write_text("x" * 31)
    with pytest.raises(ValueError, match=r"\.webui_secret_key"):
        Settings(data_dir=data_dir).child_env()


def test_the_operator_key_wins_and_writes_no_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, secret_key=_FRESH_SECRET)
    assert settings.child_env()["WEBUI_SECRET_KEY"] == _FRESH_SECRET
    assert not data_dir.exists()


def test_tool_identity_is_the_paste_in_python_operation() -> None:
    # Hand-stated literals, never read off the production constants: the id is the DB key OWUI rows
    # the tool under and the value bootstrap attaches to the workspace model, so a drift here
    # provisions a second tool and leaves the first attached.
    settings = Settings()
    assert settings.tool_id == "figure_verification"
    assert settings.tool_name == "Figure Verification"
    assert (
        settings.tool_description == "Draws a chart from a Python program and an attached CSV file."
    )
    assert settings.tool_operation_id == "draw_figure"


def test_tool_id_satisfies_the_open_webui_id_rule() -> None:
    # routers/tools.py rejects an id that is not .isidentifier() and lower-cases what it accepts, so
    # an id OWUI would rewrite would be stored under a name bootstrap never reads back.
    tool_id = Settings().tool_id
    assert tool_id.isidentifier()
    assert tool_id == tool_id.lower()


def test_from_env_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _PROVISION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    assert Settings.from_env() == Settings()


def test_from_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _PROVISION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("WEBUI_PROVISION_PORT", "9999")
    override_secret = "override-secret-at-least-thirty-two-bytes"  # noqa: S105
    monkeypatch.setenv("WEBUI_PROVISION_SECRET_KEY", override_secret)
    monkeypatch.setenv("WEBUI_PROVISION_DATA_DIR", "custom-data")
    monkeypatch.setenv("WEBUI_PROVISION_READY_TIMEOUT", "5.5")
    monkeypatch.setenv("WEBUI_PROVISION_PASTE_IN", "production")
    monkeypatch.setenv("WEBUI_PROVISION_FUNCTION_CALLING", "native")
    settings = Settings.from_env()
    assert settings.port == 9999
    assert settings.secret_key == override_secret
    assert settings.data_dir == Path("custom-data")
    assert settings.ready_timeout == 5.5
    assert settings.paste_in == "production"
    assert settings.function_calling == "native"


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "192.168.1.5", "operator-box", "127.0.0.1.example"],  # noqa: S104 - refused binds
)
def test_m21_a_host_beyond_loopback_needs_a_fresh_password(host: str) -> None:
    """M21.1 F6: the published admin password lets anyone on the network sign in as the admin,
    and an Open WebUI admin runs Python on the host through Functions. The signing key is no
    published default: the operator's own, else a random key per data dir."""
    builds: tuple[Callable[[], Settings], ...] = (
        lambda: Settings(host=host),
        lambda: Settings(host=host, secret_key=_FRESH_SECRET),
    )
    for build in builds:
        with pytest.raises(ValueError, match="host"):
            build()
    assert Settings(host=host, admin_password=_FRESH_PASSWORD).host == host
    fresh = Settings(host=host, secret_key=_FRESH_SECRET, admin_password=_FRESH_PASSWORD)
    assert fresh.host == host


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "localhost", "LOCALHOST"])
def test_m21_loopback_keeps_the_demo_defaults(host: str) -> None:
    assert Settings(host=host).host == host
