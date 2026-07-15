# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Feedback loop for the Open WebUI provisioner settings (M4.3a).

webui/ is a coverage-excluded harness, not part of the verifier claim, so these are a bench-style
regression net rather than a 100%-branch gate. Locked here:

- every fail-closed bound (__post_init__): port range, >=32-byte secret, non-empty admin email /
  password, finite-positive request and ready timeouts, http(s) verifier / model-backend URLs,
  bare host;
- launch_env() as the canonical hermetic OWUI env -- it is exactly _FIXED_ENV plus the five
  per-instance derived keys and stays independent of ambient os.environ; child_env() layers it over
  only the curated process base;
- the load-bearing _FIXED_ENV values (persistent-config off, empty task model, legacy FC, every
  background-generation toggle off, plus the auth / bootstrap login model -- auth on, password
  login, public signup off, no boot auto-admin, no trusted-header) pinned directly, so a flip fails;
- tool_server_connections() as the settled-live one-element verifier registration;
- from_env() default and WEBUI_PROVISION_* override across int / str / Path / float fields.
"""

import json
import math
from collections.abc import Callable
from pathlib import Path

import pytest

from webui.settings import _FIXED_ENV, Settings

_PROVISION_ENV_VARS = (
    "WEBUI_PROVISION_HOST",
    "WEBUI_PROVISION_PORT",
    "WEBUI_PROVISION_DATA_DIR",
    "WEBUI_PROVISION_SECRET_KEY",
    "WEBUI_PROVISION_ADMIN_NAME",
    "WEBUI_PROVISION_ADMIN_EMAIL",
    "WEBUI_PROVISION_ADMIN_PASSWORD",
    "WEBUI_PROVISION_VERIFIER_URL",
    "WEBUI_PROVISION_MODEL_BACKEND_URL",
    "WEBUI_PROVISION_MODEL_ID",
    "WEBUI_PROVISION_WEBUI_BIN",
    "WEBUI_PROVISION_REQUEST_TIMEOUT",
    "WEBUI_PROVISION_READY_TIMEOUT",
)

_DERIVED_ENV_KEYS = frozenset(
    {
        "DATA_DIR",
        "WEBUI_SECRET_KEY",
        "OPENAI_API_BASE_URL",
        "OPENAI_API_BASE_URLS",
        "TOOL_SERVER_CONNECTIONS",
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
    (lambda: Settings(verifier_url=""), "verifier_url"),
    (lambda: Settings(verifier_url="ftp://127.0.0.1"), "verifier_url"),
    (lambda: Settings(model_backend_url=""), "model_backend_url"),
    (lambda: Settings(model_backend_url="http://"), "model_backend_url"),
    (lambda: Settings(host=""), "host"),
    (lambda: Settings(host="http://127.0.0.1"), "host"),
]


@pytest.mark.parametrize(("build", "match"), _BAD_CONFIGS)
def test_rejects_bad_config(build: Callable[[], Settings], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        build()


def test_defaults_construct() -> None:
    settings = Settings()
    assert settings.base_url == "http://127.0.0.1:8080"
    assert settings.tool_server_id == "verifier"


def test_secret_key_bound_counts_utf8_bytes() -> None:
    settings = Settings(secret_key="é" * 16)
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
    # The five per-instance derived keys.
    assert env["DATA_DIR"] == str(settings.data_dir.resolve())
    assert env["WEBUI_SECRET_KEY"] == settings.secret_key
    assert env["OPENAI_API_BASE_URL"] == settings.model_backend_url
    assert env["OPENAI_API_BASE_URLS"] == settings.model_backend_url
    assert env["TOOL_SERVER_CONNECTIONS"] == settings.tool_server_connections()
    # launch_env is exactly _FIXED_ENV plus those five keys, no more, no less.
    assert set(env) == set(_FIXED_ENV) | _DERIVED_ENV_KEYS


def test_fixed_env_pins_load_bearing_toggles() -> None:
    assert _FIXED_ENV["ENABLE_PERSISTENT_CONFIG"] == "false"
    assert _FIXED_ENV["TASK_MODEL"] == ""
    assert _FIXED_ENV["TASK_MODEL_EXTERNAL"] == ""
    assert _FIXED_ENV["ENABLE_OPENAI_API"] == "true"
    assert _FIXED_ENV["ENABLE_OLLAMA_API"] == "false"
    assert json.loads(_FIXED_ENV["DEFAULT_MODEL_PARAMS"]) == {"function_calling": "legacy"}
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


def test_child_env_drops_ambient_keeps_base(monkeypatch: pytest.MonkeyPatch) -> None:
    # child_env() is the hermetic exec env: launch_env() over a curated base. A passthrough var is
    # carried through; an unpinned / hostile ambient var is dropped, never reaching OWUI.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HTTP_PROXY", "http://attacker.example:3128")
    monkeypatch.setenv("WEBUI_AUTH", "false")
    settings = Settings()
    env = settings.child_env()
    # launch_env() is fully present and its pins win over ambient.
    for key, value in settings.launch_env().items():
        assert env[key] == value
    assert env["PATH"] == "/usr/bin:/bin"  # base passthrough carried
    assert "HTTP_PROXY" not in env  # unpinned ambient dropped (no aiohttp trust_env proxy leak)
    assert env["WEBUI_AUTH"] == "true"  # launch_env pin, not the ambient "false"


def test_tool_server_connections_shape() -> None:
    settings = Settings()
    connections = json.loads(settings.tool_server_connections())
    assert isinstance(connections, list)
    assert len(connections) == 1
    conn = connections[0]
    assert conn["url"] == settings.verifier_url
    assert conn["path"] == "schema/openapi.json"
    assert conn["type"] == "openapi"
    assert conn["auth_type"] == "none"
    assert conn["config"]["enable"] is True
    assert conn["config"]["function_name_filter_list"] == ["proposeSpec"]
    assert conn["info"]["id"] == settings.tool_server_id
    assert conn["info"]["name"] == "Figure Verifier"


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
    settings = Settings.from_env()
    assert settings.port == 9999
    assert settings.secret_key == override_secret
    assert settings.data_dir == Path("custom-data")
    assert settings.ready_timeout == 5.5
