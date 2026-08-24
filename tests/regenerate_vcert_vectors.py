# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Regenerate the real-pipeline entries of ``tests/vcert_v03_vectors.json``.

Run from the repository root: ``uv run --locked python tests/regenerate_vcert_vectors.py``.

Only the two real-pipeline formula entries are derived here, each under the injected fixed TCB from
``vector_tcb`` so the bytes stay identical across the interpreter patches MEASURED there -- CPython
3.13.5 and 3.13.14, never the whole ``>=3.13,<3.14`` band the floor admits. Injection buys that
portability, never independent authority. The hand-authored ``synthetic_*`` entries are copied
through verbatim: they pin field
order and every tag discriminator INDEPENDENTLY of the builder, which is what keeps a co-derived
real-pipeline vector honest. Rerunning against an unchanged pipeline rewrites the same bytes.

Two further pins are producer-derived but live inline in their test modules, so this script also
PRINTS them: every producer-derived constant in the suite therefore replays from this one command,
and a hand edit is distinguishable from a regeneration. ``tests/test_vcert.py``'s v0.2 render pin
is computed here; ``tests/test_attestation_v03.py``'s real-f02 pin is the ``f02_linear.json`` row
above, since both encode the same certificate.
"""

import hashlib
from pathlib import Path
from typing import cast

import msgspec

from vector_tcb import DATASET_TCB, FORMULA_TCB
from verifier import checks, formula_prepare, matplotlib_script, vcert
from verifier.schema import decode_formula_spec, decode_spec

_ROOT = Path(__file__).resolve().parent.parent
_FORMULA_GOOD = _ROOT / "examples" / "formula_good_specs"
_DATASET_GOOD = _ROOT / "examples" / "good_specs"
_DATA = _ROOT / "data"
_SCHEMAS = _DATA / "schemas"
_VECTOR_PATH = Path(__file__).with_name("vcert_v03_vectors.json")
_REAL_PIPELINE_NAMES = ("f02_linear.json", "f06_quadratic.json")


def _fixed_tcb_payload(name: str) -> bytes:
    spec = decode_formula_spec((_FORMULA_GOOD / name).read_bytes())
    evidence = checks.verify_formula_run(spec).require_evidence()
    prepared = cast(
        "formula_prepare.PreparedFormula",
        formula_prepare.prepare_formula(spec, evidence).prepared,
    )
    artifact = cast(
        "matplotlib_script.MatplotlibScriptArtifact",
        matplotlib_script.emit_matplotlib_script(prepared).artifact,
    )
    return vcert.vcert_v03_bytes(vcert.build_formula_certificate(artifact, tcb=FORMULA_TCB))


def _v02_render_payload() -> bytes:
    """The v0.2 pin, driven through the shipped render path on the same injected-TCB terms."""
    from verifier import render  # noqa: PLC0415

    def _seam() -> vcert.Tcb:
        return DATASET_TCB

    spec = decode_spec((_DATASET_GOOD / "g01_total_revenue_by_month.json").read_bytes())
    manifest = (_SCHEMAS / f"{Path(spec.dataset.name).stem}.json").read_bytes()
    original = render._tcb
    render._tcb = _seam
    try:
        result = cast("render.RenderResult", render.render(spec, manifest, data_dir=_DATA))
    finally:
        render._tcb = original
    return render.vcert_bytes(result.certificate)


def main() -> None:
    """Rewrite the vector file, replacing only the real-pipeline entries, then report every pin."""
    vectors = cast(
        "dict[str, dict[str, int | str]]",
        msgspec.json.decode(_VECTOR_PATH.read_bytes()),
    )
    payloads = {name: _fixed_tcb_payload(name) for name in _REAL_PIPELINE_NAMES}
    for name, payload in payloads.items():
        vectors[name] = {
            "canonical_hex": payload.hex(),
            "length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    _VECTOR_PATH.write_bytes(msgspec.json.encode(vectors))

    reported = [
        (f"tests/vcert_v03_vectors.json {name}", payload) for name, payload in payloads.items()
    ]
    reported.append(("tests/test_attestation_v03.py real f02", payloads[_REAL_PIPELINE_NAMES[0]]))
    reported.append(("tests/test_vcert.py v0.2 render", _v02_render_payload()))
    for label, payload in reported:
        digest = hashlib.sha256(payload).hexdigest()
        print(f"{label}: {len(payload)} B sha256:{digest}")  # noqa: T201


if __name__ == "__main__":
    main()
