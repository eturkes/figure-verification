# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Fixed TCB values that hold canonical-form vectors byte-stable across MEASURED interpreters.

VCert stamps ``platform.python_version()``, while the project pins only the 3.13 line, so a vector
compared against a live TCB fails on any host whose patch release differs from the authoring host's.
Injecting these values decides canonical FORM alone; live provenance WIRING is decided by separate
tests that load no vector.

That portability is MEASURED, never general: the vectors are proven byte-identical across CPython
3.13.5 and 3.13.14 alone. Claim no further patch, host or platform without measuring it.

Every field is a synthetic constant no live source can produce, so one pair of objects serves both
roles: the fixed basis a vector is byte-pinned against, and the disagreement witness proving an
injected TCB really reaches the emitted certificate. ``numeric_profile`` is the sole exception --
``FormulaTcb`` admits exactly one value.
"""

from verifier import vcert

FORMULA_TCB = vcert.FormulaTcb(
    verifier_version="vector-verifier",
    z3_version="vector-z3",
    canon_version="vector-canon",
    python="vector-python",
    msgspec="vector-msgspec",
    unidata="vector-unidata",
    grammar_version="vector-grammar",
    numeric_profile="rational-half-even-v1",
    script_template_version="vector-script-template",
)

DATASET_TCB = vcert.Tcb(
    verifier_version="vector-verifier",
    z3_version="vector-z3",
    canon_version="vector-canon",
    python="vector-python",
    msgspec="vector-msgspec",
    unidata="vector-unidata",
    vl_convert_python="vector-vl-convert-python",
    vl_version="vector-vl-version",
    font_family="vector-font-family",
    vendored_font_sha256="sha256:" + "5" * 64,
)
