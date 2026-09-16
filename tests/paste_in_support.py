# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Independent fixtures and structural oracles for the generated Open WebUI paste-ins."""

from __future__ import annotations

import ast
import asyncio
import importlib
import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Protocol, cast

import pytest

from webui.settings import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


class BundleAPI(Protocol):
    """The fixed generator-library interface from the M10.0 contract."""

    ARTIFACTS: dict[str, str]

    def render(self, root: str) -> str: ...

    def closure(self, root: str) -> list[str]: ...

    def embedded_sources(self, text: str) -> dict[str, str]: ...


@dataclass(frozen=True, slots=True)
class StoredFile:
    """One row of the fake Open WebUI file store: what an upload looks like to the tool."""

    file_id: str
    user_id: str
    filename: str
    content: bytes


def load_bundle() -> BundleAPI:
    """Load the generator dynamically so the pre-implementation suite still type-checks."""
    return cast(BundleAPI, importlib.import_module("webui.paste_in.bundle"))


def load_tool_module() -> ModuleType:
    """Load the in-tree tool dynamically so the pre-implementation suite still type-checks."""
    return importlib.import_module("webui.paste_in.tool")


def _owui_interpreter() -> Path:
    """The `.venv-webui` interpreter, searched in this tree and in the primary tree above it.

    `.venv-webui` is gitignored, so CI and a fresh clone have none and the predicates that need
    Open WebUI's own loader skip. The condition is a dependency guard rather than a disabled case:
    it runs wherever the dependency exists, and `tools/gate.sh` announces the skip by name.
    """
    # A teammate worktree sits at `<primary>/.scratch/worktrees/<name>`, which is where the second
    # candidate comes from; the shared venv is never copied into one.
    for base in (REPO_ROOT, REPO_ROOT.parents[2]):
        interpreter = base / ".venv-webui" / "bin" / "python"
        if interpreter.is_file():
            return interpreter
    pytest.skip(f"open-webui interpreter absent: {REPO_ROOT}/.venv-webui/bin/python")


def owui_driver_output(driver: str, tmp_path: Path, marker: str) -> str:
    """Run one driver under `.venv-webui` and return the payload of its `<marker>=` line.

    The committed artifact is copied beside the driver, so Open WebUI's own loader reads the bytes
    an admin pastes with no repo path in reach.
    """
    interpreter = _owui_interpreter()
    artifact = REPO_ROOT / "paste-in" / "figure_verification_tool.py"
    assert artifact.is_file()
    (tmp_path / artifact.name).write_bytes(artifact.read_bytes())
    driver_path = tmp_path / "owui_driver.py"
    driver_path.write_text(textwrap.dedent(driver), encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "DATA_DIR": str(tmp_path / "data"),
            "ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS": "false",
            "OFFLINE_MODE": "true",
            "PYTHONPATH": "",
            # open_webui refuses to import with this unset, so the driver would die before it
            # reached the artifact. The launcher's own key is what the demo runs under.
            "WEBUI_SECRET_KEY": Settings().secret_key,
        }
    )
    result = subprocess.run(  # noqa: S603
        [str(interpreter), str(driver_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    prefix = f"{marker}="
    line = next(line for line in result.stdout.splitlines() if line.startswith(prefix))
    return line[len(prefix) :]


def owui_tool_descriptions(tmp_path: Path) -> list[str]:
    """Open WebUI 0.10.2's own model-facing descriptions for the committed artifact."""
    payload = owui_driver_output(
        """
        import asyncio
        import json
        import pathlib

        from open_webui.utils.plugin import load_tool_module_by_id
        from open_webui.utils.tools import get_tool_specs

        async def main():
            artifact = pathlib.Path(__file__).with_name("figure_verification_tool.py")
            tool, _frontmatter = await load_tool_module_by_id(
                "m10u0_description_test", content=artifact.read_text(encoding="utf-8")
            )
            specs = get_tool_specs(tool)
            print("M10U0_DESCRIPTIONS=" + json.dumps([spec["description"] for spec in specs]))

        asyncio.run(main())
        """,
        tmp_path,
        "M10U0_DESCRIPTIONS",
    )
    decoded: object = json.loads(payload)
    assert isinstance(decoded, list)
    assert all(isinstance(description, str) for description in decoded)
    return cast(list[str], decoded)


def public_tool_operation(module: ModuleType) -> tuple[str, Callable[..., object]]:
    """Mirror Open WebUI's public-callable discovery over one `Tools` instance."""
    tools_type = module.Tools
    assert isinstance(tools_type, type)
    instance = tools_type()
    operations = [
        (name, value)
        for name in dir(instance)
        if not name.startswith("_")
        and callable(value := getattr(instance, name))
        and not inspect.isclass(value)
    ]
    assert len(operations) == 1, [name for name, _value in operations]
    return operations[0]


async def _complete(awaitable: Awaitable[object]) -> object:
    return await awaitable


def invoke_tool(
    module: ModuleType,
    program: str,
    *,
    metadata: Mapping[str, object] | None = None,
    user: Mapping[str, object] | None = None,
) -> str:
    """Call the sole tool operation with its one discovered model parameter + reserved context."""
    _name, operation = public_tool_operation(module)
    parameters = inspect.signature(operation).parameters
    model_parameters = [name for name in parameters if not name.startswith("__")]
    assert len(model_parameters) == 1, model_parameters
    reserved: dict[str, object] = {
        "__metadata__": metadata,
        "__user__": user,
    }
    kwargs = {
        model_parameters[0]: program,
        **{name: value for name, value in reserved.items() if name in parameters},
    }
    result = operation(**kwargs)
    if inspect.isawaitable(result):
        result = asyncio.run(_complete(cast(Awaitable[object], result)))
    assert isinstance(result, str)
    return result


@contextmanager
def fake_open_webui(stored: Sequence[StoredFile], root: Path) -> Iterator[list[tuple[str, str]]]:
    """Install a strict `open_webui` file + storage seam over a real on-disk store.

    Strictness mirrors the real API so a tolerant fake cannot un-pin what it was built for. The
    lookup is async, takes the id and the requesting user id, and answers `None` for a missing OR
    foreign row rather than raising (`models/files.py:169-181`); `Storage.get_file` is synchronous
    and returns the path unchanged, as the local provider does. The bytes therefore really sit on
    disk and the tool's own read is the one that fetches them.

    Yields the recorded `(file_id, user_id)` lookups, so a test can assert which rows were asked
    for and that nothing was asked for twice.
    """
    lookups: list[tuple[str, str]] = []
    rows = {item.file_id: item for item in stored}
    assert len(rows) == len(stored), "duplicate file id in the fake store"
    for item in stored:
        (root / item.file_id).write_bytes(item.content)

    async def get_file_by_id_and_user_id(file_id: str, user_id: str) -> object | None:
        lookups.append((file_id, user_id))
        item = rows.get(file_id)
        if item is None or item.user_id != user_id:
            return None
        return SimpleNamespace(
            id=item.file_id,
            filename=item.filename,
            path=str(root / item.file_id),
            user_id=item.user_id,
        )

    def get_file(path: str) -> str:
        assert isinstance(path, str)
        return path

    injected: dict[str, ModuleType] = {
        name: ModuleType(name)
        for name in (
            "open_webui",
            "open_webui.models",
            "open_webui.models.files",
            "open_webui.storage",
            "open_webui.storage.provider",
        )
    }
    for name, module in injected.items():
        module.__dict__["__path__"] = []
        parent, _, leaf = name.rpartition(".")
        if parent:
            injected[parent].__dict__[leaf] = module
    injected["open_webui.models.files"].__dict__["Files"] = SimpleNamespace(
        get_file_by_id_and_user_id=get_file_by_id_and_user_id
    )
    injected["open_webui.storage.provider"].__dict__["Storage"] = SimpleNamespace(get_file=get_file)
    original = {name: sys.modules.get(name) for name in injected}
    sys.modules.update(injected)
    try:
        yield lookups
    finally:
        for name, previous in original.items():
            if previous is None:
                del sys.modules[name]
            else:
                sys.modules[name] = previous


def run_generator(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the copied tree's generator without syncing or mutating the shared environment."""
    env = os.environ.copy()
    search_path = os.pathsep.join((str(root / "src"), str(root)))
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = search_path if not existing else os.pathsep.join((search_path, existing))
    return subprocess.run(  # noqa: S603
        [sys.executable, str(root / "tools" / "generate_paste_in.py"), *arguments],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def copy_tracked_tree(destination: Path) -> Path:
    """Copy current tracked bytes only, preserving a clean disposable generator input tree."""
    listed = subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        capture_output=True,
        check=True,
    ).stdout
    for raw_relative in listed.split(b"\0"):
        if not raw_relative:
            continue
        relative = Path(os.fsdecode(raw_relative))
        source = REPO_ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(source.readlink())
        else:
            shutil.copy2(source, target)
    return destination


def artifact_items(bundle: BundleAPI) -> Iterator[tuple[Path, str]]:
    """Yield each committed artifact path with its declared root module."""
    assert bundle.ARTIFACTS
    for relative, root in bundle.ARTIFACTS.items():
        path = REPO_ROOT / relative
        assert path.is_file(), relative
        yield path, root


def _tracked_python_files() -> tuple[Path, ...]:
    listed = subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(REPO_ROOT), "ls-files", "-z", "*.py"],
        capture_output=True,
        check=True,
    ).stdout
    return tuple(
        REPO_ROOT / Path(os.fsdecode(raw_relative))
        for raw_relative in listed.split(b"\0")
        if raw_relative
    )


def _candidate_module_parts(path: Path) -> tuple[str, ...] | None:
    relative = path.relative_to(REPO_ROOT)
    parts = relative.parts
    if parts[0] == "src":
        parts = parts[1:]
    if not parts or parts[0] in {"tests", "tools"}:
        return None
    if parts[-1] == "__init__.py":
        return parts[:-1]
    if parts[-1].endswith(".py"):
        return (*parts[:-1], parts[-1][:-3])
    return None


def module_index() -> dict[str, Path]:
    """Index tracked first-party package modules independently of the generator."""
    files = _tracked_python_files()
    relative_files = {path.relative_to(REPO_ROOT).as_posix() for path in files}
    index: dict[str, Path] = {}
    for path in files:
        parts = _candidate_module_parts(path)
        if not parts:
            continue
        relative = path.relative_to(REPO_ROOT)
        source_prefix = ("src",) if relative.parts[0] == "src" else ()
        package_parts = parts if path.name == "__init__.py" else parts[:-1]
        if any(
            "/".join((*source_prefix, *package_parts[:depth], "__init__.py")) not in relative_files
            for depth in range(1, len(package_parts) + 1)
        ):
            continue
        name = ".".join(parts)
        prior = index.setdefault(name, path)
        assert prior == path, f"duplicate first-party module {name}: {prior}, {path}"
    return index


def module_path(name: str) -> Path:
    """Resolve one first-party module name to its tracked source file."""
    index = module_index()
    assert name in index, f"embedded non-first-party module: {name}"
    return index[name]


def _package_for(module: str, path: Path) -> str:
    return module if path.name == "__init__.py" else module.rpartition(".")[0]


def _resolve_from(node: ast.ImportFrom, module: str, path: Path) -> str:
    if node.level == 0:
        return node.module or ""
    package = _package_for(module, path)
    relative = "." * node.level + (node.module or "")
    return importlib.util.resolve_name(relative, package)


def direct_first_party_dependencies(module: str, index: Mapping[str, Path]) -> set[str]:
    """Return direct first-party imports from one tracked module via an independent AST walk."""
    path = index[module]
    tree = ast.parse(path.read_bytes(), filename=str(path))
    dependencies: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in index:
                    dependencies.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(node, module, path)
            if base in index:
                dependencies.add(base)
            for alias in node.names:
                candidate = f"{base}.{alias.name}" if base else alias.name
                if candidate in index:
                    dependencies.add(candidate)
    return dependencies


def _parent_packages(module: str, index: Mapping[str, Path]) -> set[str]:
    parts = module.split(".")
    return {".".join(parts[:end]) for end in range(1, len(parts)) if ".".join(parts[:end]) in index}


def independent_closure(root: str) -> list[str]:
    """The exact first-party closure of `root`, parents included, in dependency-first order.

    Ancestry is MEMBERSHIP, never an edge. The artifact registers every embedded name before any
    source runs, so a submodule resolves without its package `__init__` having executed -- and
    `verifier/pysrc/__init__.py` imports from `verifier.pysrc.budget`, so reading ancestry as an
    edge makes the graph cyclic and no topological order exists at all (contract amendment B4-1).
    """
    index = module_index()
    assert root in index, f"root module is not tracked: {root}"
    members: set[str] = set()
    pending = [root]
    while pending:
        module = pending.pop()
        if module in members:
            continue
        members.add(module)
        pending.extend(direct_first_party_dependencies(module, index))
        pending.extend(_parent_packages(module, index))

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module: str) -> None:
        if module in visited:
            return
        assert module not in visiting, f"first-party import cycle through {module}"
        visiting.add(module)
        for dependency in sorted(direct_first_party_dependencies(module, index)):
            visit(dependency)
        visiting.remove(module)
        visited.add(module)
        ordered.append(module)

    for module in sorted(members):
        visit(module)
    return ordered


def assert_embedded_identity(sources: Mapping[str, str]) -> None:
    """Assert the exact one-newline transform against tracked source bytes."""
    assert sources
    for name, source in sources.items():
        expected = b"\n" + module_path(name).read_bytes()
        assert source.encode("utf-8") == expected, name


def assert_exact_closure(root: str, sources: Mapping[str, str]) -> None:
    """Assert exact closure membership independently of production's closure function."""
    expected = set(independent_closure(root))
    actual = set(sources)
    assert actual == expected, (
        f"embedded module set mismatch: missing={sorted(expected - actual)}, "
        f"extra={sorted(actual - expected)}"
    )


def mutate_embedded_blob(
    bundle: BundleAPI,
    text: str,
    addition: str = "# planted embedded-source drift\n",
) -> str:
    """Plant a source-only edit while preserving the wrapper's representation."""
    sources = bundle.embedded_sources(text)
    name, source = max(sources.items(), key=lambda item: len(item[1]))
    planted = source + addition
    mutated = text.replace(source, planted, 1)
    assert mutated != text, f"embedded source for {name} is not represented faithfully"
    return mutated


def offending_import_roots(bundle: BundleAPI, text: str) -> set[str]:
    """Return external import roots outside the hand-stated paste-in dependency envelope."""
    sources = bundle.embedded_sources(text)
    bundled_roots = {name.partition(".")[0] for name in sources}
    allowed = set(sys.stdlib_module_names) | {"__future__", "open_webui"} | bundled_roots
    offenders: set[str] = set()
    for source in (text, *sources.values()):
        tree = ast.parse(source)
        for node in ast.walk(tree):
            roots: Sequence[str]
            if isinstance(node, ast.Import):
                roots = [alias.name.partition(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                roots = [node.module.partition(".")[0]]
            else:
                continue
            offenders.update(root for root in roots if root not in allowed)
    return offenders


def _absolute_imports(source: str) -> Iterator[tuple[str, tuple[str, ...]]]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, ()
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
            yield node.module, tuple(alias.name for alias in node.names if alias.name != "*")


@contextmanager
def artifact_import_environment(bundle: BundleAPI, text: str) -> Iterator[None]:
    """Preload stdlib imports and strict-enough Open WebUI stubs, then restore module state."""
    sources = bundle.embedded_sources(text)
    requirements = tuple(
        requirement
        for source in (text, *sources.values())
        for requirement in _absolute_imports(source)
    )
    for module_name, _names in requirements:
        if module_name.partition(".")[0] in sys.stdlib_module_names:
            importlib.import_module(module_name)

    original = dict(sys.modules)
    stub_modules: dict[str, ModuleType] = {}
    for module_name, names in requirements:
        if module_name != "open_webui" and not module_name.startswith("open_webui."):
            continue
        parts = module_name.split(".")
        for end in range(1, len(parts) + 1):
            name = ".".join(parts[:end])
            if name in sys.modules:
                module = sys.modules[name]
            else:
                module = stub_modules.setdefault(name, ModuleType(name))
                module.__path__ = []
                sys.modules[name] = module
            if end > 1:
                parent_name = ".".join(parts[: end - 1])
                setattr(sys.modules[parent_name], parts[end - 1], module)
        module = sys.modules[module_name]
        for name in names:
            setattr(module, name, object())
    try:
        yield
    finally:
        sys.modules.clear()
        sys.modules.update(original)


def execute_artifact(text: str, path: Path, name: str) -> ModuleType:
    """Execute artifact text without inserting the wrapper module into `sys.modules`."""
    module = ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    exec(compile(text, str(path), "exec"), module.__dict__)  # noqa: S102
    return module


def assert_module_snapshot(before: Mapping[str, ModuleType]) -> None:
    """Assert exact `sys.modules` keys and object identities against a snapshot."""
    assert set(sys.modules) == set(before)
    rebound = [name for name, module in before.items() if sys.modules[name] is not module]
    assert rebound == [], f"rebound modules: {rebound}"


def without_module_restore(text: str, path: Path) -> str:
    """Plant B5's loader mutant by deleting the wrapper's `sys.modules` finalizer."""
    tree = ast.parse(text, filename=str(path))
    removed = 0

    class RemoveRestore(ast.NodeTransformer):
        def visit_Try(self, node: ast.Try) -> ast.AST:
            nonlocal removed
            updated = cast(ast.Try, self.generic_visit(node))
            references_modules = any(
                isinstance(item, ast.Attribute)
                and isinstance(item.value, ast.Name)
                and item.value.id == "sys"
                and item.attr == "modules"
                for statement in updated.finalbody
                for item in ast.walk(statement)
            )
            if references_modules:
                removed += len(updated.finalbody)
                updated.finalbody = [ast.Pass()]
            return updated

    mutated = RemoveRestore().visit(tree)
    ast.fix_missing_locations(mutated)
    assert removed > 0, "artifact wrapper has no removable sys.modules restore"
    return ast.unparse(mutated) + "\n"


def assert_topological(order: Sequence[str]) -> None:
    """Assert each direct first-party import precedes its consumer.

    Import dependencies alone are edges; ancestry is membership (see `independent_closure`).
    """
    index = module_index()
    positions = {name: position for position, name in enumerate(order)}
    assert len(positions) == len(order), "duplicate embedded module"
    for module in order:
        for dependency in direct_first_party_dependencies(module, index):
            assert dependency in positions, f"{module} depends on missing {dependency}"
            assert positions[dependency] < positions[module], (
                f"{dependency} emitted after dependent {module}"
            )
