# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.0 bundle: the generator that turns tracked sources into the production paste-in.

Contract: `.agent/archive/contracts/m10u0.md` predicate group B. Each docstring carries its
predicate's acceptance check; the check is the test's specification and the contract's wording
wins wherever a body would assert more.

The single-source ruling is what these predicates defend. The verification core is written once
under `src/verifier/pysrc/`; the pasted artifact embeds it BY GENERATION, and a hand fork is
banned. A generator whose output drifts from its inputs recreates the fork silently, so freshness,
byte identity, closure, order and the import surface are each pinned separately.
"""

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

from paste_in_support import (
    REPO_ROOT,
    artifact_import_environment,
    artifact_items,
    assert_embedded_identity,
    assert_exact_closure,
    assert_module_snapshot,
    assert_topological,
    copy_tracked_tree,
    execute_artifact,
    load_bundle,
    module_path,
    mutate_embedded_blob,
    offending_import_roots,
    run_generator,
    without_module_restore,
)

# `pydantic` + its runtime dependencies, as the Open WebUI image ships them (Q43).
_IMAGE_PACKAGES = (
    "pydantic",
    "pydantic_core",
    "typing_extensions",
    "annotated_types",
    "typing_inspection",
)


def test_b1_committed_artifact_equals_a_fresh_generation(tmp_path: Path) -> None:
    """B1: `tools/generate_paste_in.py --check` is rc=0 on a clean tree, rc=1 on a planted byte.

    Generation is deterministic and idempotent. Two runs produce identical bytes, and the rc=1 path
    names the file that drifted.
    """
    clean = run_generator(REPO_ROOT, "--check")
    assert clean.returncode == 0, clean.stdout + clean.stderr

    bundle = load_bundle()
    for path, root in artifact_items(bundle):
        assert path.read_text(encoding="utf-8") == bundle.render(root)

    clone = copy_tracked_tree(tmp_path / "repo")
    first = run_generator(clone)
    assert first.returncode == 0, first.stdout + first.stderr
    first_bytes = {relative: (clone / relative).read_bytes() for relative in bundle.ARTIFACTS}
    second = run_generator(clone)
    assert second.returncode == 0, second.stdout + second.stderr
    assert {
        relative: (clone / relative).read_bytes() for relative in bundle.ARTIFACTS
    } == first_bytes

    victim_relative = next(iter(bundle.ARTIFACTS))
    victim = clone / victim_relative
    victim.write_bytes(victim.read_bytes() + b" ")
    drifted = run_generator(clone, "--check")
    assert drifted.returncode == 1
    assert victim_relative in drifted.stdout + drifted.stderr


def test_b2_each_embedded_source_is_its_tracked_file_plus_one_newline() -> None:
    """B2: `sources[name] == "\\n" + tracked_bytes`, for every embedded name.

    The one leading newline is the whole transform. A planted edit inside an embedded blob goes red.
    """
    bundle = load_bundle()
    for path, _root in artifact_items(bundle):
        text = path.read_text(encoding="utf-8")
        assert_embedded_identity(bundle.embedded_sources(text))
        planted = mutate_embedded_blob(bundle, text)
        with pytest.raises(AssertionError):
            assert_embedded_identity(bundle.embedded_sources(planted))


def test_b3_embedded_set_is_exactly_the_first_party_closure() -> None:
    """B3: emitted keys == AST closure of the root module + the parent packages it needs.

    An extra module and a missing module both fail.
    """
    bundle = load_bundle()
    for path, root in artifact_items(bundle):
        sources = bundle.embedded_sources(path.read_text(encoding="utf-8"))
        expected_order = bundle.closure(root)
        assert set(expected_order) == set(sources)
        assert_exact_closure(root, sources)

        missing = dict(sources)
        missing.pop(next(iter(missing)))
        with pytest.raises(AssertionError, match="embedded module set mismatch"):
            assert_exact_closure(root, missing)

        extra = {**sources, "tests.__planted_extra__": "\n"}
        with pytest.raises(AssertionError, match="embedded module set mismatch"):
            assert_exact_closure(root, extra)


def test_b4_emission_order_is_topological() -> None:
    """B4: every embedded module's first-party dependencies are emitted before it.

    Checked over the committed artifact, not over a fresh in-memory computation.
    """
    bundle = load_bundle()
    for path, root in artifact_items(bundle):
        order = list(bundle.embedded_sources(path.read_text(encoding="utf-8")))
        assert order == bundle.closure(root)
        assert_topological(order)
        with pytest.raises(AssertionError, match="emitted after dependent"):
            assert_topological(list(reversed(order)))


def test_b5_loading_restores_embedded_module_slots() -> None:
    """B5-1: no embedded name remains and no existing value is rebound after `exec_module`.

    Preload the imports before snapshotting; new standard-library keys may remain after a cold load.
    One warm load does that for the lazy imports a load makes: building the tool's `Valves` model
    loads pydantic's plugin loader (Q43). Red under a loader whose embedded-name restore step is
    removed.
    """
    bundle = load_bundle()
    for index, (path, _root) in enumerate(artifact_items(bundle)):
        text = path.read_text(encoding="utf-8")
        sources = bundle.embedded_sources(text)
        with artifact_import_environment(bundle, text):
            execute_artifact(text, path, f"_paste_in_warm_{index}")
            sentinels = {name: ModuleType(name) for name in sources}
            sys.modules.update(sentinels)
            before = dict(sys.modules)

            execute_artifact(text, path, f"_paste_in_normal_{index}")
            assert_module_snapshot(before)

            mutant = without_module_restore(text, path)
            try:
                execute_artifact(mutant, path, f"_paste_in_no_restore_{index}")
                with pytest.raises(AssertionError):
                    assert_module_snapshot(before)
                assert any(
                    sys.modules.get(name) is not module for name, module in sentinels.items()
                )
            finally:
                sys.modules.clear()
                sys.modules.update(before)


def test_b6_import_surface_is_stdlib_open_webui_and_tool_pydantic() -> None:
    """B6: AST scan over the wrapper AND every embedded source admits only stdlib + `open_webui`,
    plus `pydantic` in the two tool artifacts alone (Q43: the admin `Valves`).

    The failure names every offending root. A planted `import numpy` inside a blob fails.
    """
    bundle = load_bundle()
    beyond = {
        "paste-in/figure_verification_tool.py": {"pydantic"},
        "paste-in/figure_verification_filter.py": set(),
        "webui/demo-paste-in/figure_verification_tool.py": {"pydantic"},
        "webui/demo-paste-in/figure_verification_filter.py": set(),
    }
    seen = set()
    for path, _root in artifact_items(bundle):
        relative = path.relative_to(REPO_ROOT).as_posix()
        seen.add(relative)
        text = path.read_text(encoding="utf-8")
        assert offending_import_roots(bundle, text) == beyond[relative]
        planted = mutate_embedded_blob(bundle, text, "import numpy\n")
        assert offending_import_roots(bundle, planted) == beyond[relative] | {"numpy"}
    assert seen == set(beyond)


def test_b7_artifact_is_self_contained_without_the_repo(tmp_path: Path) -> None:
    """B7: with `verifier` absent and `src/` off `sys.path`, the filter artifact still judges.

    A subprocess with a scrubbed path decodes and judges two real reader descriptions (an honest
    bar chart and bars cut off by `plt.ylim`) through the artifact's own embedded judge, and
    returns the same verdicts as the in-tree judge.
    """
    from verifier.figure import reader  # noqa: PLC0415
    from verifier.figure.description import parse_description  # noqa: PLC0415
    from verifier.figure.judge import Passed, Sources, judge  # noqa: PLC0415

    plot = "import matplotlib.pyplot as plt\nplt.bar(['west', 'east'], [3.25, 1])\n"
    content = b"site,value\nwest,3.25\neast,1\ncentral,2.5\n"
    descriptions = [reader.run(plot), reader.run(plot + "plt.ylim(1, 4)\n")]

    def summarize(text: str) -> dict[str, str | None]:
        described = parse_description(text)
        assert described is not None
        verdict = judge(described, Sources((("measurements.csv", content),), "value by site"))
        return {
            "kind": "passed" if isinstance(verdict, Passed) else "blocked",
            "code": None if isinstance(verdict, Passed) else verdict.reason,
        }

    artifact = REPO_ROOT / "paste-in" / "figure_verification_filter.py"
    assert artifact.is_file()
    isolated_artifact = tmp_path / "artifact.py"
    isolated_artifact.write_bytes(artifact.read_bytes())
    # The Open WebUI image carries `pydantic` (Q43: the tool's `Valves`); the driver reaches it and
    # its own dependencies alone, through `image/`, never the rest of the dev environment.
    image = tmp_path / "image"
    image.mkdir()
    for name in _IMAGE_PACKAGES:
        found = importlib.util.find_spec(name)
        assert found is not None and found.origin is not None, name
        source = Path(found.origin)
        source = source.parent if found.submodule_search_locations else source
        (image / source.name).symlink_to(source)
    (tmp_path / "payload.json").write_text(
        json.dumps(
            {
                "descriptions": descriptions,
                "content_hex": content.hex(),
            }
        ),
        encoding="utf-8",
    )
    driver = textwrap.dedent(
        """
        import importlib.abc
        import importlib.util
        import json
        import pathlib
        import sys
        import sysconfig
        import types

        here = pathlib.Path(__file__).resolve().parent
        stdlib = pathlib.Path(sysconfig.get_path("stdlib")).resolve()
        platstdlib = pathlib.Path(sysconfig.get_path("platstdlib")).resolve()

        def kept(entry):
            resolved = pathlib.Path(entry or ".").resolve()
            return (
                resolved == here
                or resolved == stdlib
                or stdlib in resolved.parents
                or resolved == platstdlib
                or platstdlib in resolved.parents
            )

        sys.path[:] = [entry for entry in sys.path if kept(entry)] + [str(here / "image")]
        assert "verifier" not in sys.modules
        for absent in ("verifier", "msgspec"):
            try:
                __import__(absent)
            except ModuleNotFoundError:
                continue
            raise AssertionError(f"{absent} is still reachable, so this proves nothing")

        class OpenWebUIStub(importlib.abc.MetaPathFinder, importlib.abc.Loader):
            def find_spec(self, fullname, path=None, target=None):
                del path, target
                if fullname == "open_webui" or fullname.startswith("open_webui."):
                    return importlib.util.spec_from_loader(fullname, self, is_package=True)
                return None

            def create_module(self, spec):
                del spec
                return None

            def exec_module(self, module):
                module.__path__ = []

                def missing(name):
                    return type(name, (), {})()

                module.__getattr__ = missing

        sys.meta_path.insert(0, OpenWebUIStub())
        spec = importlib.util.spec_from_file_location("isolated_filter", here / "artifact.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert "verifier" not in sys.modules

        namespace = module.Filter.outlet.__globals__
        parse, judge, sources = (
            namespace["parse_description"], namespace["judge"], namespace["Sources"]
        )
        payload = json.loads((here / "payload.json").read_text(encoding="utf-8"))
        content = bytes.fromhex(payload["content_hex"])
        observed = []
        for text in payload["descriptions"]:
            verdict = judge(parse(text), sources((("measurements.csv", content),), "value by site"))
            code = getattr(verdict, "reason", None)
            observed.append({"kind": "blocked" if code is not None else "passed", "code": code})
        print(json.dumps(observed, sort_keys=True))
        """
    )
    driver_path = tmp_path / "driver.py"
    driver_path.write_text(driver, encoding="utf-8")
    # Two flags, two halves of the isolation. `-I` drops the environment and the user site; `-S`
    # skips `site`, without which the venv's editable `verifier.pth` and every installed
    # third-party package stay importable and the driver's own controls above go silent.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-S", str(driver_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = [summarize(text) for text in descriptions]
    assert expected[0] == {"kind": "passed", "code": None}
    assert expected[1]["kind"] == "blocked"
    assert json.loads(result.stdout) == expected


def test_b8_generation_fails_closed_on_an_unembeddable_source(tmp_path: Path) -> None:
    """B8: a source holding `'''`, ending in a backslash, or overflowing the line cap aborts.

    The abort names the file. Silent truncation or escaping is the defect this forbids.
    """
    bundle = load_bundle()
    root = next(iter(bundle.ARTIFACTS.values()))
    relative = module_path(root).relative_to(REPO_ROOT)
    original = (REPO_ROOT / relative).read_bytes()
    _first, rest = original.split(b"\n", 1)
    mutations = {
        "delimiter": original + b'\n_UNEMBEDDABLE = """\'\'\'"""\n',
        "trailing-backslash": original.rstrip(b"\n") + b"\\",
        "line-overflow": b"# " + b"x" * 10_000 + b"\n" + rest,
    }

    for name, mutation in mutations.items():
        clone = copy_tracked_tree(tmp_path / name)
        (clone / relative).write_bytes(mutation)
        result = run_generator(clone)
        assert result.returncode != 0, name
        assert relative.as_posix() in result.stdout + result.stderr, name


@pytest.mark.parametrize("prefix", ["utils", "apps", "main", "config"])
def test_b8_generation_rejects_a_source_open_webui_would_rewrite(
    tmp_path: Path, prefix: str
) -> None:
    """B8-1: refuse each `from <prefix>` byte sequence before Open WebUI rewrites it."""
    bundle = load_bundle()
    root = next(iter(bundle.ARTIFACTS.values()))
    relative = module_path(root).relative_to(REPO_ROOT)
    clone = copy_tracked_tree(tmp_path / prefix)
    victim = clone / relative
    victim.write_bytes(victim.read_bytes() + f"\n# from {prefix}\n".encode())

    result = run_generator(clone)
    assert result.returncode != 0, prefix
    assert relative.as_posix() in result.stdout + result.stderr, prefix


def test_b8_generation_rejects_a_source_without_triple_double_quote(tmp_path: Path) -> None:
    """B8-1: refuse a parseable source whose embedding delimiter ruff would rewrite."""
    bundle = load_bundle()
    root = next(iter(bundle.ARTIFACTS.values()))
    relative = module_path(root).relative_to(REPO_ROOT)
    clone = copy_tracked_tree(tmp_path / "no-triple-double-quote")
    (clone / relative).write_bytes(
        b"# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception\nclass Tools:\n    pass\n"
    )

    result = run_generator(clone)
    assert result.returncode != 0
    assert relative.as_posix() in result.stdout + result.stderr
