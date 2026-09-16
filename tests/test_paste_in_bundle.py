# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""M10.0 bundle: the generator that turns tracked sources into the production paste-in.

Contract: `.agent/contracts/m10u0.md` predicate group B. Each docstring carries its predicate's
acceptance check; the check is the test's specification and the contract's wording wins wherever a
body would assert more.

The single-source ruling is what these predicates defend. The verification core is written once
under `src/verifier/pysrc/`; the pasted artifact embeds it BY GENERATION, and a hand fork is
banned. A generator whose output drifts from its inputs recreates the fork silently, so freshness,
byte identity, closure, order and the import surface are each pinned separately.
"""

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


def test_b5_loading_the_artifact_leaves_sys_modules_untouched() -> None:
    """B5: no key added, no value rebound, across an `exec_module` of the artifact.

    Red under a loader whose restore step is removed.
    """
    bundle = load_bundle()
    for index, (path, _root) in enumerate(artifact_items(bundle)):
        text = path.read_text(encoding="utf-8")
        sources = bundle.embedded_sources(text)
        with artifact_import_environment(bundle, text):
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


def test_b6_import_surface_is_stdlib_plus_open_webui() -> None:
    """B6: AST scan over the wrapper AND every embedded source admits only stdlib + `open_webui`.

    The failure names every offending root. A planted `import numpy` inside a blob fails.
    """
    bundle = load_bundle()
    for path, _root in artifact_items(bundle):
        text = path.read_text(encoding="utf-8")
        assert offending_import_roots(bundle, text) == set()
        planted = mutate_embedded_blob(bundle, text, "import numpy\n")
        assert offending_import_roots(bundle, planted) == {"numpy"}


def test_b7_artifact_is_self_contained_without_the_repo(tmp_path: Path) -> None:
    """B7: with `verifier` absent and `src/` off `sys.path`, the artifact still verifies.

    A subprocess with a scrubbed path returns the same verdicts as the in-tree core for one
    known-good and one known-bad program.
    """
    from verifier.pysrc import DatasetTarget, Refused, verify_python_source  # noqa: PLC0415

    good = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'df = pd.read_csv("measurements.csv")\n'
        'plt.bar(df["site"], df["value"])\n'
        "plt.show()\n"
    )
    bad = "import os\n"
    content = b"site,value\nwest,3.25\neast,1\ncentral,2.5\n"
    target = DatasetTarget(path="measurements.csv", content=content)

    def summarize(source: str) -> dict[str, str | None]:
        verdict = verify_python_source(source, declared_target=target)
        return {
            "kind": "refused" if isinstance(verdict, Refused) else "verified",
            "code": verdict.code if isinstance(verdict, Refused) else None,
        }

    artifact = REPO_ROOT / "paste-in" / "figure_verification_tool.py"
    assert artifact.is_file()
    isolated_artifact = tmp_path / "artifact.py"
    isolated_artifact.write_bytes(artifact.read_bytes())
    (tmp_path / "payload.json").write_text(
        json.dumps(
            {
                "sources": [good, bad],
                "path": "measurements.csv",
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

        sys.path[:] = [entry for entry in sys.path if kept(entry)]
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
        spec = importlib.util.spec_from_file_location("isolated_tool", here / "artifact.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert "verifier" not in sys.modules

        public = [
            value
            for name, value in vars(module.Tools).items()
            if not name.startswith("_") and callable(value)
        ]
        assert len(public) == 1
        namespace = public[0].__globals__
        verify = next(
            value
            for value in namespace.values()
            if callable(value) and getattr(value, "__name__", "") == "verify_python_source"
        )
        target_type = next(
            value
            for value in namespace.values()
            if isinstance(value, type) and value.__name__ == "DatasetTarget"
        )
        payload = json.loads((here / "payload.json").read_text(encoding="utf-8"))
        target_value = target_type(
            path=payload["path"],
            content=bytes.fromhex(payload["content_hex"]),
        )
        observed = []
        for source in payload["sources"]:
            verdict = verify(source, declared_target=target_value)
            code = getattr(verdict, "code", None)
            observed.append(
                {"kind": "refused" if code is not None else "verified", "code": code}
            )
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
    assert json.loads(result.stdout) == [summarize(good), summarize(bad)]


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
