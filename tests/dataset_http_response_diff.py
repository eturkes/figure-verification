# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Dataset HTTP response bytes against baseline 7491481.

T42 proves the dataset bundle/archive/audit/replay bytes; it never builds an app, so it cannot
decide the TRANSPORT surface. This runs the identical program in both trees over every dataset
POST and every GET. Seventeen of the eighteen surfaces are compared as exact status, header, and
response body BYTES.

/schema/openapi.json is the eighteenth and cannot be, because the unit publishes a new path and a
new schema into that one document: byte equality there is false by construction, and asserting it
would leave a differential that can only be deleted or falsified. It is compared as a PROJECTION
instead — every baseline path, schema, and envelope value must survive intact, the added keys are
hand-stated so an unannounced third one fails, and the single prose-only allowance still pins the
wire shape it covers. The new document's own bytes are pinned by the committed OpenAPI golden.

Determinism comes from three pins the HTTP path otherwise leaves free: a seeded signing key, a
frozen occurrence clock, and a fixed attempt nonce. All three patch targets exist in both trees.
The proposer backend is stubbed to one fixed reply, so /propose-spec exercises its whole
downstream verify/commit/encode path without a model.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NoReturn

_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = "7491481"

# The document's permitted drift, hand-stated so an unannounced fourth change fails. /verify-formula
# and FormulaScriptVerdict are the unit's whole OpenAPI surface. Verdict is prose-only: the envelope
# now serves both plot modes, so its docstring — which openapi.py publishes as `description` — was
# rewritten source-neutral while its WIRE SHAPE stayed byte-identical, and the shape is what the
# preservation claim covers.
_ADDED_PATHS = frozenset({"/verify-formula"})
_ADDED_SCHEMAS = frozenset({"FormulaScriptVerdict"})
_PROSE_ONLY_SCHEMAS = frozenset({"Verdict"})

_PROGRAM = """
import itertools
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from litestar.testing import TestClient

import verifier
from verifier.service import app as app_module
from verifier.service import archive as a
from verifier.service import model_client as mc
from verifier.service import pipeline
from verifier.service.identity import load_identity
from verifier.service.settings import Settings

root = Path.cwd()
# Vacuity guard. The editable install's .pth entry resolves `verifier` to the PRIMARY src no
# matter the cwd, so an unset PYTHONPATH silently makes both runs import the SAME code and the
# comparison passes against itself. Fail loudly instead.
_loaded = Path(verifier.__file__).resolve()
if not _loaded.is_relative_to(root / "src"):
    raise SystemExit(f"imported {_loaded}, expected a module under {root / 'src'}")
_FIXED = datetime(2026, 1, 1, tzinfo=UTC)


class _Clock:
    @staticmethod
    def now(tz=None):
        # REQUIRE the timezone rather than ignoring it. A clock that accepts any argument makes
        # `datetime.now(UTC)` -> `datetime.now()` invisible here, even though the naive timestamp
        # breaks the live service downstream.
        if tz is not UTC:
            raise SystemExit(f"occurrence clock needs UTC, got {tz!r}")
        return _FIXED


# Three nondeterminism pins. Without them every attempt id, and therefore every response
# carrying one, differs per run and the differential decides nothing.
pipeline.datetime = _Clock
# A CONSTANT nonce under a frozen clock makes every occurrence envelope identical, so the second
# render of one spec collides on attempt_id and answers 500 — which would silently drop the
# include_html and propose surfaces from the comparison. Count instead: distinct and deterministic.
_NONCES = itertools.count()
a._attempt_nonce = lambda: f"{next(_NONCES):032x}"
_REPLY = (root / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()


async def _stub_propose(*_args, **_kwargs):
    return mc.ModelProposal(
        reply_bytes=_REPLY,
        trace=mc.ProposalTrace(
            request_body=b'{"stub":"request"}',
            response_body=b'{"stub":"response"}',
            reply_bytes=_REPLY,
            fault=None,
        ),
    )


app_module.propose_spec = _stub_propose

_JSON = {"content-type": "application/json"}
# Litestar stamps neither header today. ASSERT their absence instead of filtering them out:
# filtering would silently absorb a future wall-clock header, and the exact-header claim would
# then be weaker than it reads. If one ever appears, this fails loudly and gets a real ruling.
_FORBIDDEN_HEADERS = ("date", "server")


def _record(response):
    headers = sorted((k.lower(), v) for k, v in response.headers.items())
    present = [name for name, _ in headers if name in _FORBIDDEN_HEADERS]
    if present:
        raise SystemExit(f"nondeterministic header now served: {present}")
    return {"status": response.status_code, "headers": headers, "body": response.content.hex()}


with tempfile.TemporaryDirectory() as td:
    settings = Settings(data_dir=root / "data", state_dir=Path(td) / "state")
    # Let load_identity create the key file with its required mode, then seed it deterministically.
    load_identity(settings)
    Path(settings.signing_key_file).write_bytes(bytes(range(32)))
    keyid = load_identity(settings).signer.keyid
    app = app_module.create_app(settings)
    good = (root / "examples/good_specs/g01_total_revenue_by_month.json").read_bytes()
    propose = json.dumps({"user_request": "total revenue by month", "dataset_name": "sales.csv"})
    out = {}
    with TestClient(app=app) as client:
        out["verify_only_good"] = _record(client.post("/verify-only", content=good, headers=_JSON))
        out["verify_only_undecodable"] = _record(
            client.post("/verify-only", content=b"{", headers=_JSON)
        )
        out["verify_only_wrong_media"] = _record(
            client.post("/verify-only", content=good, headers={"content-type": "text/plain"})
        )
        rendered = client.post(
            "/verify-and-render?include_html=false", content=good, headers=_JSON
        )
        out["render_no_html"] = _record(rendered)
        out["render_html"] = _record(
            client.post("/verify-and-render?include_html=true", content=good, headers=_JSON)
        )
        out["render_undecodable"] = _record(
            client.post("/verify-and-render", content=b"{", headers=_JSON)
        )
        out["render_bad_query"] = _record(
            client.post("/verify-and-render?include_html=maybe", content=good, headers=_JSON)
        )
        out["propose"] = _record(
            client.post("/propose-spec", content=propose.encode("utf-8"), headers=_JSON)
        )
        body = rendered.json()
        plot_id = body["plot_id"]
        spec_id = body["spec_id"]
        out["health"] = _record(client.get("/health"))
        out["openapi"] = _record(client.get("/schema/openapi.json"))
        out["certificate"] = _record(client.get(f"/certificate/{plot_id}"))
        out["spec"] = _record(client.get(f"/spec/{spec_id}"))
        out["key"] = _record(client.get(f"/key/{keyid}"))
        out["chart"] = _record(client.get(f"/chart/{plot_id}"))
        out["replay"] = _record(client.get(f"/replay/{plot_id}"))
        out["certificate_absent"] = _record(client.get("/certificate/" + "0" * 64))
        out["chart_malformed"] = _record(client.get("/chart/deadbeef"))
        out["method_not_allowed"] = _record(client.get("/verify-only"))
    print(json.dumps(out, sort_keys=True, separators=(",", ":")))
"""


def _run(cwd: Path) -> bytes:
    # PYTHONPATH is load-bearing: the project is installed editable, so its .pth entry resolves
    # `verifier` to the PRIMARY src from any cwd. Without this the baseline run would import the
    # candidate's own production code and the differential would compare a tree against itself.
    # PYTHONPATH precedes site-packages in sys.path, so this wins; the program asserts it did.
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),
        "PYTHONHASHSEED": "0",
        "PYTHONPATH": str(cwd / "src"),
    }
    return subprocess.run(  # noqa: S603 — fixed interpreter and literal child program
        [sys.executable, "-c", _PROGRAM],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
    ).stdout


def _fail(detail: str) -> NoReturn:
    msg = f"dataset HTTP surface differs from {_BASELINE}: {detail}"
    raise SystemExit(msg)


def _ordered(value: Any) -> str:
    """Compact JSON preserving emitted key order, so reordering counts as a difference."""
    return json.dumps(value, separators=(",", ":"))


def _headers(record: dict[str, Any]) -> list[Any]:
    return [pair for pair in record["headers"] if pair[0] != "content-length"]


def _without_prose(value: Any) -> Any:
    """The same subtree minus every `description`, i.e. its wire shape alone."""
    if isinstance(value, dict):
        return {k: _without_prose(v) for k, v in value.items() if k != "description"}
    if isinstance(value, list):
        return [_without_prose(item) for item in value]
    return value


def _compare_subtrees(
    kind: str,
    candidate: Any,
    expected: Any,
    added: frozenset[str],
    prose_only: frozenset[str] = frozenset(),
) -> None:
    if set(expected) - set(candidate):
        _fail(f"{kind} removed: {sorted(set(expected) - set(candidate))}")
    if set(candidate) - set(expected) != added:
        _fail(f"unexpected {kind} added: {sorted(set(candidate) - set(expected) - added)}")
    for name in expected:
        if _ordered(candidate[name]) == _ordered(expected[name]):
            continue
        shape_held = _ordered(_without_prose(candidate[name])) == _ordered(
            _without_prose(expected[name])
        )
        if name in prose_only and shape_held:
            continue
        _fail(f"{kind} {name} changed" if shape_held else f"{kind} {name} changed shape")


def _compare_openapi(candidate: dict[str, Any], expected: dict[str, Any]) -> None:
    """Every baseline path, schema, and top-level value survives; only the declared keys appear.

    Whole-document equality is unachievable by construction here: the unit ADDS /verify-formula
    and FormulaScriptVerdict, so the served document must change. Equality would therefore have to
    be either deleted or falsified. This projects instead — the preservation claim keeps its full
    strength over everything that existed at the baseline, and the additions are named, so an
    unannounced third path or schema still fails. The new document's own bytes are pinned
    elsewhere, by the committed OpenAPI golden.
    """
    if candidate["status"] != expected["status"]:
        _fail(f"openapi status {candidate['status']} != {expected['status']}")
    # content-length necessarily tracks the added path and schema; every other header is pinned.
    if _headers(candidate) != _headers(expected):
        _fail("openapi headers changed")
    got = json.loads(bytes.fromhex(candidate["body"]))
    want = json.loads(bytes.fromhex(expected["body"]))
    _compare_subtrees("path", got["paths"], want["paths"], _ADDED_PATHS)
    _compare_subtrees(
        "schema",
        got["components"]["schemas"],
        want["components"]["schemas"],
        _ADDED_SCHEMAS,
        _PROSE_ONLY_SCHEMAS,
    )
    outer_got = {k: v for k, v in got.items() if k not in {"paths", "components"}}
    outer_want = {k: v for k, v in want.items() if k not in {"paths", "components"}}
    if _ordered(outer_got) != _ordered(outer_want):
        _fail("openapi document envelope changed")
    if _ordered({k: v for k, v in got["components"].items() if k != "schemas"}) != _ordered(
        {k: v for k, v in want["components"].items() if k != "schemas"}
    ):
        _fail("openapi components envelope changed")


def main() -> None:
    candidate = _run(_ROOT)
    with tempfile.TemporaryDirectory() as td:
        baseline = Path(td) / "baseline"
        subprocess.run(  # noqa: S603 — fixed literal argv
            ["git", "worktree", "add", "--detach", str(baseline), _BASELINE],  # noqa: S607
            cwd=_ROOT,
            check=True,
            capture_output=True,
        )
        try:
            expected = _run(baseline)
        finally:
            subprocess.run(  # noqa: S603 — fixed literal argv
                ["git", "worktree", "remove", "--force", str(baseline)],  # noqa: S607
                cwd=_ROOT,
                check=True,
                capture_output=True,
            )
    got = json.loads(candidate)
    want = json.loads(expected)
    if set(got) != set(want):
        _fail(f"surface set changed: {sorted(set(got) ^ set(want))}")
    differing = {name for name in want if got[name] != want[name]}
    if differing - {"openapi"}:
        _fail(f"response bytes changed on {sorted(differing - {'openapi'})}")
    _compare_openapi(got["openapi"], want["openapi"])


if __name__ == "__main__":
    main()
