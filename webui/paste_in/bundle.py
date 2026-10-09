# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The generator: tracked first-party sources in, one pasteable artifact out.

The single-source ruling is what this module implements. The verification core is written once
under `src/verifier/`; the artifact embeds it BY GENERATION, and a hand fork is banned. A
generator whose output drifts from its inputs recreates that fork silently, so `--check` compares
committed bytes against a fresh render on every gate run.

Concatenating the sources is unsound: module-private names repeat across modules (`_refuse`,
`__all__`), each meaning its own module's. Module namespaces are therefore preserved -- each source
is embedded whole and executed into its own `types.ModuleType` -- and emission order is topological,
because an alphabetical order runs `verifier/pysrc/__init__.py` before the modules it imports from
and the artifact fails to load.

Embedding is one transform and one only: a raw triple-single-quoted literal holding a leading
newline followed by the tracked bytes. The newline is load-bearing -- without it a source's first
line continues the assignment's physical line and can exceed the 100-column cap. The delimiter is
`'''` because every tracked source contains `\"\"\"`, which is what stops `ruff format` from
rewriting the quotes and breaking `--check` on the next gate run.
"""

import ast
import sys
from pathlib import Path

TOOL_ARTIFACT = "paste-in/figure_verification_tool.py"
FILTER_ARTIFACT = "paste-in/figure_verification_filter.py"
# The demo's own pair (Q37): production + demo ship separate files; the launcher provisions these.
DEMO_TOOL_ARTIFACT = "webui/demo-paste-in/figure_verification_tool.py"
DEMO_FILTER_ARTIFACT = "webui/demo-paste-in/figure_verification_filter.py"

# Each root names the one class Open WebUI discovers after its source closure loads.
ARTIFACTS: dict[str, str] = {
    TOOL_ARTIFACT: "webui.paste_in.tool",
    FILTER_ARTIFACT: "webui.paste_in.filter",
    DEMO_TOOL_ARTIFACT: "webui.paste_in.demo_tool",
    DEMO_FILTER_ARTIFACT: "webui.paste_in.demo_filter",
}
_EXPORTS = {
    "webui.paste_in.tool": "Tools",
    "webui.paste_in.filter": "Filter",
    "webui.paste_in.demo_tool": "Tools",
    "webui.paste_in.demo_filter": "Filter",
}

# First-party root package -> the repo-relative directory holding it.
_PACKAGE_ROOTS: dict[str, str] = {"verifier": "src", "webui": ""}

# `pyproject.toml` [tool.ruff] line-length. The artifact is linted like any other tracked source,
# so a source line that would overflow here must abort generation rather than fail the gate.
_LINE_LIMIT = 100
# The third-party imports an artifact may carry: Open WebUI imports itself into the process
# that runs the pasted file (CSV ruling), so it is inside the dependency envelope by definition;
# its own dependency `pydantic` builds the tool's admin `Valves` (Q43).
_ADMITTED_IMPORT_ROOTS = frozenset({"open_webui", "pydantic"})

_ASSIGNMENT = "_SOURCES[\"{name}\"] = r'''\n{source}'''\n"


class BundleError(RuntimeError):
    """Generation cannot produce a faithful artifact. Never raised for a drifted committed file."""


def repo_root() -> Path:
    """The repository root, resolved from this file rather than from the process cwd."""
    return Path(__file__).resolve().parents[2]


def artifact_text(relative: str) -> str:
    """The COMMITTED artifact's bytes, which is what provisioning sends and an admin pastes.

    Read from disk rather than rendered, so a drifted artifact is provisioned as-is and caught by
    `--check` in the gate. Provisioning a fresh render instead would hide the drift it exists to
    expose.
    """
    return (repo_root() / relative).read_text(encoding="utf-8")


def is_first_party(name: str) -> bool:
    """True when `name`'s root package is one this repo owns and can therefore embed."""
    return name.split(".", 1)[0] in _PACKAGE_ROOTS


def module_path(name: str) -> Path:
    """The tracked file backing a first-party dotted module name.

    Resolved by repo layout rather than by `importlib`, so generation reads the tree it is about to
    embed instead of whatever the environment happens to have installed.
    """
    root, *rest = name.split(".")
    if root not in _PACKAGE_ROOTS:
        msg = f"{name!r} is not a first-party module"
        raise BundleError(msg)
    base = repo_root() / _PACKAGE_ROOTS[root] / root
    for part in rest:
        base = base / part
    package = base / "__init__.py"
    if package.is_file():
        return package
    module = base.with_suffix(".py")
    if module.is_file():
        return module
    msg = f"no tracked source for module {name!r}"
    raise BundleError(msg)


def _module_exists(name: str) -> bool:
    """True when `name` resolves to a tracked source; `from pkg import x` needs this to tell a
    submodule from a plain name."""
    try:
        module_path(name)
    except BundleError:
        return False
    return True


def import_roots(tree: ast.AST) -> set[str]:
    """Every root package name imported anywhere in a parsed source, nesting included."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and not node.level:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _embeddable_source(name: str) -> str:
    """The tracked bytes for `name`, refused before anything else reads them.

    The check precedes the parse because a source ending in a backslash is not parsable at all:
    `ast.parse` would raise a bare `SyntaxError` carrying no path, and generation must abort naming
    the source it refused.
    """
    source = module_path(name).read_text(encoding="utf-8")
    _check_embeddable(name, source)
    return source


def _first_party_deps(name: str) -> tuple[str, ...]:
    """The first-party modules `name` imports, resolved to the modules that must load before it."""
    tree = ast.parse(_embeddable_source(name))
    deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            deps.update(alias.name for alias in node.names if is_first_party(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                msg = f"{name!r} uses a relative import, which carries no embeddable module name"
                raise BundleError(msg)
            if node.module is None or not is_first_party(node.module):
                continue
            for alias in node.names:
                submodule = f"{node.module}.{alias.name}"
                deps.add(submodule if _module_exists(submodule) else node.module)
    return tuple(sorted(deps))


def _ancestors(name: str) -> tuple[str, ...]:
    """The parent packages of a dotted name, outermost first."""
    parts = name.split(".")
    return tuple(".".join(parts[:index]) for index in range(1, len(parts)))


def closure(root: str) -> list[str]:
    """The transitive first-party closure of `root` plus its parent packages, in load order.

    Parent packages are members but never edges: the loader registers every name before any source
    runs, so `verifier.pysrc.errors` resolves without `verifier/pysrc/__init__.py` having executed,
    while that `__init__` still sorts after the modules it imports from. Making ancestry an edge
    would make the graph cyclic for no gain.
    """
    deps: dict[str, tuple[str, ...]] = {}
    pending = [root]
    while pending:
        name = pending.pop()
        if name in deps:
            continue
        found = _first_party_deps(name)
        deps[name] = found
        pending.extend(found)
        pending.extend(_ancestors(name))
    return _load_order(deps)


def _load_order(deps: dict[str, tuple[str, ...]]) -> list[str]:
    """Kahn's algorithm, alphabetical within a level, so one input yields one byte-exact order."""
    order: list[str] = []
    placed: set[str] = set()
    remaining = dict(deps)
    while remaining:
        ready = sorted(n for n, edges in remaining.items() if placed.issuperset(edges))
        if not ready:
            msg = f"import cycle among {', '.join(sorted(remaining))}"
            raise BundleError(msg)
        for name in ready:
            order.append(name)
            placed.add(name)
            del remaining[name]
    return order


def _check_embeddable(name: str, source: str) -> None:
    """Abort on any source the one embedding transform would not reproduce byte-for-byte.

    Every clause is a way the emitted literal stops meaning the tracked file: `'''` closes it
    early, a trailing backslash escapes the closing delimiter, a missing `\"\"\"` lets `ruff
    format` rewrite the quotes, an overlong line fails the lint the artifact is subject to, and
    Open WebUI rewrites four `from …` prefixes in tool content on every create and update
    (`utils/plugin.py` `replace_imports`), which would leave the stored bytes unequal to the
    generated ones.
    """
    faults: list[str] = []
    if "'''" in source:
        faults.append("holds a ''' sequence")
    if source.endswith("\\"):
        faults.append("ends in a backslash")
    if '"""' not in source:
        faults.append('holds no """, so ruff format would rewrite the delimiter')
    overlong = [n for n, line in enumerate(source.splitlines(), 1) if len(line) > _LINE_LIMIT]
    if overlong:
        faults.append(f"exceeds {_LINE_LIMIT} columns at line(s) {overlong}")
    rewritten = [p for p in ("from utils", "from apps", "from main", "from config") if p in source]
    if rewritten:
        faults.append(f"holds {rewritten}, which Open WebUI rewrites on paste")
    if faults:
        msg = f"{module_path(name)} cannot be embedded: {'; '.join(faults)}"
        raise BundleError(msg)


def embedded_sources(text: str) -> dict[str, str]:
    """Parse a rendered artifact back into its embedded name -> source map, in emission order.

    Reads the artifact's own AST rather than matching text, so the result is the value the loader
    will execute and not a second guess at the quoting.
    """
    found: dict[str, str] = {}
    for node in ast.parse(text).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Subscript):
            continue
        holder, key, value = target.value, target.slice, node.value
        named = isinstance(holder, ast.Name) and holder.id == "_SOURCES"
        if not named or not isinstance(key, ast.Constant) or not isinstance(value, ast.Constant):
            continue
        found[str(key.value)] = str(value.value)
    return found


def offending_import_roots(text: str) -> list[str]:
    """Root packages a rendered artifact imports outside stdlib, `open_webui` and `pydantic`.

    Scans the wrapper AND every embedded source, because an import inside a blob is invisible to a
    scan of the artifact's own AST. First-party roots are admitted: those modules are embedded, so
    the import resolves inside the artifact and reaches nothing outside it.
    """
    admitted = sys.stdlib_module_names | _ADMITTED_IMPORT_ROOTS | _PACKAGE_ROOTS.keys()
    roots = import_roots(ast.parse(text))
    for source in embedded_sources(text).values():
        roots |= import_roots(ast.parse(source))
    return sorted(roots - admitted)


def render(root: str) -> str:
    """The complete artifact text for one paste target. Deterministic in the tracked sources."""
    names = closure(root)
    blobs = [_ASSIGNMENT.format(name=name, source=_embeddable_source(name)) for name in names]
    try:
        exported = _EXPORTS[root]
    except KeyError as exc:
        msg = f"{root!r} is not a paste-in root"
        raise BundleError(msg) from exc
    text = _PREAMBLE + "\n".join(blobs) + _EPILOGUE.format(root=root, exported=exported)
    offending = offending_import_roots(text)
    if offending:
        msg = f"{root!r} reaches outside the dependency envelope: {', '.join(offending)}"
        raise BundleError(msg)
    return text


_PREAMBLE = '''\
# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Figure verification for Open WebUI. GENERATED FILE -- do not edit.

Paste the whole file into Open WebUI. It imports the standard library and packages the image
already carries -- `open_webui`, and `pydantic` in the tool -- and nothing else. There is no
`requirements:` frontmatter and no network call.

Regenerate with `uv run --locked python tools/generate_paste_in.py`. The same command with
`--check` fails when this file and its sources disagree, so an edit made here is lost at the next
gate run: change `webui/paste_in/` or `src/verifier/` instead.
"""

import sys
import types

_SOURCES: dict[str, str] = {}

'''

_EPILOGUE = '''
_ROOT = "{root}"


def _load() -> types.ModuleType:
    """Execute each embedded module in its own namespace and restore the embedded module slots.

    Registration comes first for every name, which is what lets a submodule import resolve before
    its package `__init__` has run; the blobs then execute in dependency order, so each `from X
    import Y` finds `Y` already bound. Each source is stored with one leading newline, stripped
    here so the executed bytes equal the tracked file's.

    The embedded-name registration is undone in `finally`; newly imported standard-library
    modules remain loaded. This file runs inside Open WebUI's process, so an embedded-name residue
    would shadow, or be shadowed by, whatever else that process imports.
    """
    saved = {{name: sys.modules.get(name) for name in _SOURCES}}
    modules = {{}}
    for name in _SOURCES:
        module = types.ModuleType(name)
        module.__path__ = []  # treat every name as a package so submodule lookups resolve
        modules[name] = module
        sys.modules[name] = module
    try:
        for name, source in _SOURCES.items():
            # The figure reader ships its own text to the browser (M19), so each module keeps it.
            modules[name].__dict__["__paste_in_source__"] = source[1:]
            code = compile(source[1:], f"<paste-in:{{name}}>", "exec")
            exec(code, modules[name].__dict__)  # noqa: S102 - embedding IS this file's job
        return modules[_ROOT]
    finally:
        for name, previous in saved.items():
            if previous is None:
                del sys.modules[name]
            else:
                sys.modules[name] = previous


{exported} = _load().{exported}
'''
