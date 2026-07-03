# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M2.1 service scaffold tests: Settings env parsing, app factory, /health, runner.

Uses litestar.testing.TestClient(app=create_app(...)): the app factory owns route
registration + the body cap, so the client must wrap the built app rather than
create_test_client (which builds its own app from bare handlers). main() is covered
by monkeypatching uvicorn.run, so no socket binds during the unit suite.
"""

import ast
from pathlib import Path

import pytest
import uvicorn
from litestar import Litestar
from litestar.testing import TestClient

from verifier import __version__
from verifier.service import __main__ as service_main
from verifier.service.app import create_app
from verifier.service.settings import Settings

_VERIFIER_ENV = (
    "VERIFIER_DATA_DIR",
    "VERIFIER_HOST",
    "VERIFIER_PORT",
    "VERIFIER_MAX_BODY_BYTES",
    "VERIFIER_STORE_CAP",
)


def test_health(tmp_path: Path) -> None:
    with TestClient(app=create_app(Settings(data_dir=tmp_path))) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_settings_defaults(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.max_body_bytes == 65536
    assert settings.store_cap == 256


def test_settings_frozen(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    attr = "port"  # variable name dodges B010 and the mypy frozen guard
    with pytest.raises(AttributeError):
        setattr(settings, attr, 9)


def test_settings_rejects_nonpositive_body_cap(tmp_path: Path) -> None:
    # A non-positive cap is falsy → Litestar would treat the body as unlimited, silently
    # disabling the fail-closed guard; __post_init__ rejects it on every construction path.
    for bad in (0, -1):
        with pytest.raises(ValueError, match="max_body_bytes"):
            Settings(data_dir=tmp_path, max_body_bytes=bad)


def test_settings_rejects_nonpositive_store_cap(tmp_path: Path) -> None:
    # A non-positive store_cap makes the artifact store drop every render (cap 0) or crash on
    # its first eviction (cap < 0); __post_init__ rejects it like the body cap.
    for bad in (0, -1):
        with pytest.raises(ValueError, match="store_cap"):
            Settings(data_dir=tmp_path, store_cap=bad)


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _VERIFIER_ENV:
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env() == Settings(data_dir=Path("data"))


def test_from_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 192.0.2.1 = RFC 5737 TEST-NET-1: a distinct non-default host, no bind-all (S104).
    monkeypatch.setenv("VERIFIER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VERIFIER_HOST", "192.0.2.1")
    monkeypatch.setenv("VERIFIER_PORT", "9001")
    monkeypatch.setenv("VERIFIER_MAX_BODY_BYTES", "1024")
    monkeypatch.setenv("VERIFIER_STORE_CAP", "8")
    assert Settings.from_env() == Settings(
        data_dir=tmp_path,
        host="192.0.2.1",
        port=9001,
        max_body_bytes=1024,
        store_cap=8,
    )


def test_from_env_rejects_nonpositive_body_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The guard fires through the env path too, not just direct construction.
    monkeypatch.setenv("VERIFIER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VERIFIER_MAX_BODY_BYTES", "0")
    with pytest.raises(ValueError, match="max_body_bytes"):
        Settings.from_env()


def test_from_env_rejects_nonpositive_store_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The store_cap guard fires through the env path too, not just direct construction.
    monkeypatch.setenv("VERIFIER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VERIFIER_STORE_CAP", "0")
    with pytest.raises(ValueError, match="store_cap"):
        Settings.from_env()


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
