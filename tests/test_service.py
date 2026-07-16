# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M2.1 service scaffold tests: Settings env parsing, app factory, /health, runner.

Uses litestar.testing.TestClient(app=create_app(...)): the app factory owns route
registration + the body cap, so the client must wrap the built app rather than
create_test_client (which builds its own app from bare handlers). main() is covered
by monkeypatching uvicorn.run, so no socket binds during the unit suite.
"""

import ast
import math
from pathlib import Path
from typing import Any, cast

import pytest
import uvicorn
from litestar import Litestar
from litestar.testing import TestClient

from verifier import __version__
from verifier.attestation import envelope_byte_limit
from verifier.limits import DEFAULT_LIMITS, VerificationLimits
from verifier.service import __main__ as service_main
from verifier.service import settings as settings_module
from verifier.service.app import create_app
from verifier.service.settings import Settings
from verifier.service.store import ArtifactStore

_MAX_RESOURCE_INTEGER = 2**63 - 1
_PIN_A = "sha256:" + "a" * 64
_PIN_B = "sha256:" + "b" * 64
_CORE_DEFAULTS = {name: getattr(DEFAULT_LIMITS, name) for name in DEFAULT_LIMITS.__struct_fields__}
_RESOURCE_DEFAULTS = {
    "max_body_bytes": 64 * 1024,
    "store_cap": 256,
    "html_cap": 16,
    "model_max_tokens": 512,
    "max_user_request_bytes": 4 * 1024,
    "max_prompt_bytes": 32 * 1024,
    "max_model_response_bytes": 128 * 1024,
    "render_cache_bytes": 32 * 1024 * 1024,
    "chart_cache_bytes": 128 * 1024 * 1024,
    "max_active_jobs": 2,
    "work_rate_per_minute": 120,
    "work_burst": 120,
    **_CORE_DEFAULTS,
}
_RESOURCE_ENV = {
    "max_body_bytes": "VERIFIER_MAX_BODY_BYTES",
    "store_cap": "VERIFIER_STORE_CAP",
    "html_cap": "VERIFIER_HTML_CAP",
    "model_max_tokens": "VERIFIER_MODEL_MAX_TOKENS",
    "max_user_request_bytes": "VERIFIER_MAX_USER_REQUEST_BYTES",
    "max_prompt_bytes": "VERIFIER_MAX_PROMPT_BYTES",
    "max_model_response_bytes": "VERIFIER_MAX_MODEL_RESPONSE_BYTES",
    "render_cache_bytes": "VERIFIER_RENDER_CACHE_BYTES",
    "chart_cache_bytes": "VERIFIER_CHART_CACHE_BYTES",
    "max_active_jobs": "VERIFIER_MAX_ACTIVE_JOBS",
    "work_rate_per_minute": "VERIFIER_WORK_RATE_PER_MINUTE",
    "work_burst": "VERIFIER_WORK_BURST",
    **{name: f"VERIFIER_{name.upper()}" for name in DEFAULT_LIMITS.__struct_fields__},
}
_VERIFIER_ENV = (
    "VERIFIER_DATA_DIR",
    "VERIFIER_STATE_DIR",
    "VERIFIER_SIGNING_KEY_FILE",
    "VERIFIER_TRUSTED_KEYIDS",
    "VERIFIER_HOST",
    "VERIFIER_PORT",
    "VERIFIER_PUBLIC_BASE_URL",
    "VERIFIER_MODEL_BASE_URL",
    "VERIFIER_MODEL_NAME",
    "VERIFIER_MODEL_TIMEOUT",
    "VERIFIER_MODEL_SAMPLE_ROWS",
    *_RESOURCE_ENV.values(),
)


def _settings_with(data_dir: Path, **changes: object) -> Settings:
    """Dynamically override named fields for exhaustive runtime validation matrices."""
    constructor = cast("Any", Settings)
    return cast("Settings", constructor(data_dir=data_dir, **changes))


def test_health(tmp_path: Path) -> None:
    assert __version__ == "0.2.0"
    with TestClient(app=create_app(Settings(data_dir=tmp_path))) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_app_threads_validated_cache_byte_budgets(tmp_path: Path) -> None:
    render_budget = envelope_byte_limit(1) + 2
    settings = Settings(
        data_dir=tmp_path,
        state_dir=tmp_path / "state",
        max_body_bytes=1,
        max_model_response_bytes=1,
        max_attestation_bytes=1,
        render_cache_bytes=render_budget,
        max_html_bytes=2,
        chart_cache_bytes=2,
    )
    app = create_app(settings)
    store = cast("ArtifactStore", app.state["store"])
    store.put(plot_id="a" * 64, cert_bytes=b"A", spec_id="5" * 64, spec_bytes=b"SS")
    store.put_chart("a" * 64, b"HH")
    with pytest.raises(ValueError, match="render payload bytes"):
        store.put(
            plot_id="b" * 64,
            cert_bytes=b"C" * render_budget,
            spec_id="7" * 64,
            spec_bytes=b"S",
        )
    with pytest.raises(ValueError, match="chart payload bytes"):
        store.put_chart("b" * 64, b"HHH")


def test_settings_defaults(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    launch_root = Path.cwd().resolve()
    assert settings.state_dir == launch_root / ".verifier-state"
    assert settings.signing_key_file == launch_root / ".verifier-state" / "signing.key"
    assert settings.trusted_keyids == ()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.public_base_url == "http://127.0.0.1:8000"
    assert settings.model_base_url == "http://127.0.0.1:8001/v1"
    assert settings.model_name == "Qwen2-0.5B-Instruct-int4-sym-ov"
    assert settings.model_timeout == 120.0
    assert settings.model_sample_rows == 5
    assert {name: getattr(settings, name) for name in _RESOURCE_DEFAULTS} == _RESOURCE_DEFAULTS
    assert settings.limits == DEFAULT_LIMITS


def test_settings_public_base_url_derives_from_port(tmp_path: Path) -> None:
    # Left unset, the browser-facing origin derives from the loopback literal + the configured
    # port (separate from host, the bind address), so a non-default port flows through.
    settings = Settings(data_dir=tmp_path, port=9000)
    assert settings.public_base_url == "http://127.0.0.1:9000"


def test_signing_paths_absolutize_without_following_final_component(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target_state = tmp_path / "target-state"
    target_state.mkdir()
    state_link = tmp_path / "state-link"
    state_link.symlink_to(target_state, target_is_directory=True)
    target_key = tmp_path / "target-key"
    target_key.write_bytes(b"x")
    key_link = tmp_path / "key-link"
    key_link.symlink_to(target_key)
    monkeypatch.chdir(tmp_path)

    settings = Settings(
        data_dir=Path("data"),
        state_dir=Path("state-link"),
        signing_key_file=Path("key-link"),
    )
    assert settings.state_dir == state_link
    assert settings.state_dir != target_state
    assert settings.signing_key_file == key_link
    assert settings.signing_key_file != target_key


def test_signing_path_settings_require_named_path_entries(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="state_dir"):
        Settings(data_dir=tmp_path, state_dir=Path("/"))
    with pytest.raises(ValueError, match="signing_key_file"):
        _settings_with(tmp_path, signing_key_file=cast("Path", "not-a-path"))


def test_trusted_keyids_are_canonical_deduplicated_and_bounded(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, trusted_keyids=(_PIN_A, _PIN_A, _PIN_B))
    assert settings.trusted_keyids == (_PIN_A, _PIN_B)

    for bad in ("", "sha256:" + "A" * 64, "sha512:" + "a" * 64, cast("str", 7)):
        with pytest.raises(ValueError, match="trusted_keyids entries"):
            _settings_with(tmp_path, trusted_keyids=(bad,))
    with pytest.raises(TypeError, match="must be a tuple"):
        _settings_with(tmp_path, trusted_keyids=cast("tuple[str, ...]", [_PIN_A]))
    too_many = tuple(f"sha256:{index:064x}" for index in range(33))
    with pytest.raises(ValueError, match="at most 32"):
        Settings(data_dir=tmp_path, trusted_keyids=too_many)


def test_settings_public_base_url_accepts_clean_origins(tmp_path: Path) -> None:
    # Clean explicit origins (an operator behind a reverse proxy) are preserved verbatim: https
    # with a port, a bare host with an implicit port (the common proxy case), IPv6 with and without
    # a port, and a bare loopback name. The authority allowlist must not over-reject these.
    clean = (
        "https://verify.example.org:8443",
        "https://verify.example.org",
        "http://[::1]:8000",
        "http://[2001:db8::1]:8443",
        "http://[::1]",
        "http://localhost",
    )
    for good in clean:
        settings = Settings(data_dir=tmp_path, public_base_url=good)
        assert settings.public_base_url == good


def test_settings_rejects_malformed_public_base_url(tmp_path: Path) -> None:
    # Only a clean origin scheme://host[:port] is accepted, so f"{base}/chart/{id}" appends exactly
    # one clean segment toward the browser. Every other shape -- a path/query/fragment/trailing
    # slash, whitespace, a missing or userinfo-shadowed host, a backslash a browser reads as '/', a
    # percent-escape or control byte or forbidden char in the authority, a raw-unicode/IDN host, an
    # uppercase (non-canonical) scheme, or a port urlparse cannot parse -- corrupts that browser-
    # facing URL, so it fails closed with the one uniform message on both construction paths.
    malformed = (
        # path / query / fragment / trailing slash / whitespace / wrong scheme / garbage
        "",
        "ftp://host",
        "not a url",
        "http://",
        "http://host:8000/",
        "http://host?x",
        "http://host#frag",
        "http://host/base",
        "http://host ",
        "http://ho\tst",
        # missing host (netloc truthy but no hostname) + userinfo host-confusion
        "http://:8000",
        "http://@host",
        "https://trusted.example@evil.example",
        "http://user:pass@host:8000",
        # backslash path-injection -- a browser normalizes '\' to '/'
        "http://host\\evil",
        "http://good.example\\@evil.example",
        # forbidden authority bytes: percent-escape, pipe, C0 NUL, ESC, DEL
        "http://host%2f.evil",
        "http://host|evil:8000",
        "http://host\x00evil",
        "http://host\x1bevil",
        "http://host\x7fevil",
        # raw-unicode / IDN host (requires punycode) -- built via chr() to keep the source ASCII
        f"http://ex{chr(0xE4)}mple.org",
        f"http://{chr(0x4F8B)}.test:8443",
        # uppercase (non-canonical) scheme, kept lowercase-only by design
        "HTTP://example.org:8443",
        # a port urlparse rejects (non-numeric, out of range) or a malformed double-colon authority
        "http://host:bad",
        "http://host:99999",
        "http://host:80:80",
        # unbalanced IPv6 bracket -- urlparse raises ValueError, caught into the uniform message
        "http://[::1",
    )
    for bad in malformed:
        with pytest.raises(ValueError, match="public_base_url"):
            Settings(data_dir=tmp_path, public_base_url=bad)


def test_settings_frozen(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    attr = "port"  # variable name dodges B010 and the mypy frozen guard
    with pytest.raises(AttributeError):
        setattr(settings, attr, 9)


@pytest.mark.parametrize("field", tuple(_RESOURCE_DEFAULTS))
@pytest.mark.parametrize("bad", [0, -1, cast("int", math.isfinite(1.0)), cast("int", 1.5), 2**63])
def test_settings_rejects_invalid_resource_integer(tmp_path: Path, field: str, bad: int) -> None:
    # Every resource setting is a finite positive signed-64-bit integer. The bool/float casts
    # model runtime misuse without weakening the static API; the huge integer proves the absolute
    # ceiling with no correspondingly huge allocation.
    with pytest.raises(ValueError, match=field):
        _settings_with(tmp_path, **{field: bad})


def test_settings_rejects_nonfinite_or_nonpositive_model_timeout(tmp_path: Path) -> None:
    # httpx does not validate its timeout, and not every non-None value is bounded: 0 times out
    # every request immediately, a negative is an undefined deadline, inf runs unbounded, and nan
    # crashes the asyncio deadline at request time -- none is a real bounded wait, and a bare
    # `<= 0` misses inf/nan. Require a finite value > 0; all of these fail closed.
    for bad in (0.0, -1.0, math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError, match="model_timeout"):
            Settings(data_dir=tmp_path, model_timeout=bad)


def test_settings_rejects_negative_model_sample_rows(tmp_path: Path) -> None:
    # sample_rows >= 0 accepts 0 (header only), but retains the same exact-int/absolute ceiling.
    for bad in (-1, cast("int", math.isfinite(1.0)), cast("int", 1.5), 2**63):
        with pytest.raises(ValueError, match="model_sample_rows"):
            Settings(data_dir=tmp_path, model_sample_rows=bad)


def test_settings_accepts_resource_integer_boundaries(tmp_path: Path) -> None:
    # Exercise the inclusive absolute ceiling on a field that does not participate in a sum.
    settings = Settings(data_dir=tmp_path, max_active_jobs=_MAX_RESOURCE_INTEGER)
    assert settings.max_active_jobs == _MAX_RESOURCE_INTEGER


def test_settings_eagerly_builds_core_limits(tmp_path: Path) -> None:
    overrides = {name: index + 1 for index, name in enumerate(_CORE_DEFAULTS)}
    settings = _settings_with(tmp_path, **overrides)
    assert isinstance(settings.limits, VerificationLimits)
    assert {name: getattr(settings.limits, name) for name in overrides} == overrides


def test_settings_rejects_independently_supplied_limits(tmp_path: Path) -> None:
    # `limits` is init=False: the flat operator fields are authoritative and derive it once.
    with pytest.raises(TypeError, match="limits"):
        _settings_with(tmp_path, limits=DEFAULT_LIMITS)


def test_settings_rejects_incompatible_render_cache_budget(tmp_path: Path) -> None:
    # Conservatively reserve a full DSSE envelope plus both route-specific spec-input ceilings.
    required = envelope_byte_limit(17) + 11 + 13
    with pytest.raises(ValueError, match="render_cache_bytes"):
        Settings(
            data_dir=tmp_path,
            max_body_bytes=11,
            max_model_response_bytes=13,
            max_attestation_bytes=17,
            render_cache_bytes=required - 1,
        )
    assert (
        Settings(
            data_dir=tmp_path,
            max_body_bytes=11,
            max_model_response_bytes=13,
            max_attestation_bytes=17,
            render_cache_bytes=required,
        ).render_cache_bytes
        == required
    )


def test_settings_rejects_incompatible_chart_cache_budget(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="chart_cache_bytes"):
        Settings(data_dir=tmp_path, max_html_bytes=17, chart_cache_bytes=16)
    assert (
        Settings(data_dir=tmp_path, max_html_bytes=17, chart_cache_bytes=17).chart_cache_bytes == 17
    )


def test_settings_rejects_resource_bound_sum_overflow_without_allocating(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="render cache item"):
        Settings(
            data_dir=tmp_path,
            max_body_bytes=_MAX_RESOURCE_INTEGER - 1,
            max_model_response_bytes=1,
            max_attestation_bytes=1,
            render_cache_bytes=_MAX_RESOURCE_INTEGER,
        )


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _VERIFIER_ENV:
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env() == Settings(data_dir=Path("data"))


def test_from_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 192.0.2.1 = RFC 5737 TEST-NET-1: a distinct non-default host, no bind-all (S104).
    monkeypatch.setenv("VERIFIER_DATA_DIR", str(tmp_path))
    state_dir = tmp_path / "state"
    signing_key = tmp_path / "rotated.key"
    monkeypatch.setenv("VERIFIER_STATE_DIR", str(state_dir))
    monkeypatch.setenv("VERIFIER_SIGNING_KEY_FILE", str(signing_key))
    monkeypatch.setenv("VERIFIER_TRUSTED_KEYIDS", f"{_PIN_A}, {_PIN_A},{_PIN_B}")
    monkeypatch.setenv("VERIFIER_HOST", "192.0.2.1")
    monkeypatch.setenv("VERIFIER_PORT", "9001")
    monkeypatch.setenv("VERIFIER_PUBLIC_BASE_URL", "https://verify.example.org:8443")
    monkeypatch.setenv("VERIFIER_MODEL_BASE_URL", "http://192.0.2.1:9100/v1")
    monkeypatch.setenv("VERIFIER_MODEL_NAME", "test-model")
    monkeypatch.setenv("VERIFIER_MODEL_TIMEOUT", "30.5")  # non-integer float exercises the parse
    monkeypatch.setenv("VERIFIER_MODEL_SAMPLE_ROWS", "3")
    resource_overrides = {name: index + 101 for index, name in enumerate(_RESOURCE_DEFAULTS)}
    # Keep the two cache budgets compatible with their overridden per-item ceilings.
    resource_overrides["render_cache_bytes"] = 16_384
    resource_overrides["chart_cache_bytes"] = 8_192
    for field, env_name in _RESOURCE_ENV.items():
        monkeypatch.setenv(env_name, str(resource_overrides[field]))
    assert Settings.from_env() == _settings_with(
        tmp_path,
        state_dir=state_dir,
        signing_key_file=signing_key,
        trusted_keyids=(_PIN_A, _PIN_B),
        host="192.0.2.1",
        port=9001,
        public_base_url="https://verify.example.org:8443",
        model_base_url="http://192.0.2.1:9100/v1",
        model_name="test-model",
        model_timeout=30.5,
        model_sample_rows=3,
        **resource_overrides,
    )


def test_from_env_rejects_malformed_trusted_keyid_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERIFIER_TRUSTED_KEYIDS", f"{_PIN_A},,")
    with pytest.raises(ValueError, match="trusted_keyids entries"):
        Settings.from_env()


@pytest.mark.parametrize("field,env_name", tuple(_RESOURCE_ENV.items()))
def test_from_env_rejects_every_invalid_resource_bound(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str, env_name: str
) -> None:
    monkeypatch.setenv("VERIFIER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(env_name, "0")
    with pytest.raises(ValueError, match=field):
        Settings.from_env()


@pytest.mark.parametrize("env_name", tuple(_RESOURCE_ENV.values()))
def test_from_env_rejects_every_noninteger_resource_bound(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    monkeypatch.setenv(env_name, "not-an-integer")
    with pytest.raises(ValueError, match="invalid literal"):
        Settings.from_env()


@pytest.mark.parametrize("bad", ["-1", "not-an-integer", str(2**63)])
def test_from_env_rejects_invalid_model_sample_rows(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setenv("VERIFIER_MODEL_SAMPLE_ROWS", bad)
    with pytest.raises(ValueError, match=r"model_sample_rows|invalid literal"):
        Settings.from_env()


@pytest.mark.parametrize(
    ("env_name", "field"),
    [
        ("VERIFIER_RENDER_CACHE_BYTES", "render_cache_bytes"),
        ("VERIFIER_CHART_CACHE_BYTES", "chart_cache_bytes"),
    ],
)
def test_from_env_rejects_cross_limit_cache_budget(
    monkeypatch: pytest.MonkeyPatch, env_name: str, field: str
) -> None:
    monkeypatch.setenv(env_name, "1")
    with pytest.raises(ValueError, match=field):
        Settings.from_env()


def test_from_env_rejects_nonfinite_model_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # float() parses "inf"/"nan", so the finite-value guard must fire through the env path too --
    # this is the realistic vector for a non-finite deadline reaching the client.
    monkeypatch.setenv("VERIFIER_DATA_DIR", str(tmp_path))
    for bad in ("inf", "-inf", "nan"):
        monkeypatch.setenv("VERIFIER_MODEL_TIMEOUT", bad)
        with pytest.raises(ValueError, match="model_timeout"):
            Settings.from_env()


def test_service_environment_is_read_only_inside_from_env() -> None:
    tree = ast.parse(Path(settings_module.__file__).read_text(encoding="utf-8"))

    def reads_environment(node: ast.AST) -> bool:
        return any(
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "os"
            and child.attr in {"environ", "getenv"}
            for child in ast.walk(node)
        )

    readers = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and reads_environment(node)
    ]
    assert readers == ["from_env"]


def test_main_serves_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        captured["app"] = app
        captured["kwargs"] = kwargs

    # __main__ and this test share the one uvicorn module object, so patching run
    # here is what main() calls — no socket binds.
    monkeypatch.setattr(uvicorn, "run", fake_run)
    for name in _VERIFIER_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERIFIER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VERIFIER_PORT", "9002")

    service_main.main()

    assert isinstance(captured["app"], Litestar)
    assert captured["kwargs"] == {"host": "127.0.0.1", "port": 9002, "workers": 1}


def _imports_verifier_service(source: str) -> bool:
    """True if the module source directly imports verifier.service in any form."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "verifier.service" or alias.name.startswith("verifier.service.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "verifier.service" or module.startswith("verifier.service."):
                return True
            if module == "verifier" and any(alias.name == "service" for alias in node.names):
                return True
    return False


def test_core_does_not_import_service() -> None:
    # POC_SCOPE one-way dependency: the transport adds no trust, so the core must never
    # import verifier.service. Enforce the __init__ claim — a later import fails the gate.
    package_root = Path(__file__).parents[1] / "src" / "verifier"
    offenders = sorted(
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*.py")
        if path.relative_to(package_root).parts[0] != "service"
        and _imports_verifier_service(path.read_text(encoding="utf-8"))
    )
    assert offenders == [], f"core modules import verifier.service: {offenders}"
