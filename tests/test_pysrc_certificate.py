# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Core certificate — K1-K6 of `.agent/archive/contracts/m13u5.md`.

The certificate is the surface a reader ACTS on, so what it does not establish is as load-bearing
as what it does. `checks` is all-pass by construction, matching v0.3's
`CertifiedCheck.status: Literal["pass"]`; everything unestablished lives in `declared_open`.

Skeleton: each body is `pytest.skip` and its docstring carries the predicate's acceptance check.
"""

import hashlib
from fractions import Fraction

from verifier.pysrc import spec

_ARTIFACT_GAP = "The emitted image is not compared against this table."
_INTENT_GAP = (
    "The plotted values are the submitted program's own expression, not a target the user stated."
)
_NO_ARTIFACT = (
    "No user artifact was consumed. The plotted values come from the submitted program alone."
)
_DATASET_BYTES = b"site,value\nwest,1\neast,2\n"
_DATASET_SOURCE = (
    "import pandas as pd\n"
    "import matplotlib.pyplot as plt\n"
    'frame = pd.read_csv("measurements.csv")\n'
    'plt.bar(frame["site"], frame["value"])\n'
    "plt.show()\n"
)
_FORMULA_SOURCE = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n"
    "grid_points = np.linspace(0, 1, num=3)\n"
    "curve_values = np.sin(grid_points)\n"
    "plt.plot(grid_points, curve_values)\n"
    "plt.show()\n"
)


def _formula_target() -> spec.FormulaTarget:
    return spec.FormulaTarget(
        y=spec.Fn("sin", spec.Var()),
        grid=spec.Grid(spec.Num(Fraction(0)), spec.Num(Fraction(1)), 3),
    )


def test_k1_certificate_field_set() -> None:
    """Exactly `version, source_sha256, spec_sha256, table_sha256, provenance, artifact_sha256,
    numeric_profile, checks, declared_open, interpretation`.

    Accept: `__dataclass_fields__` pinned as an exact hand-stated set; adding a field without
    updating the pin goes red.
    """
    from verifier.pysrc.certificate import CoreCertificate  # noqa: PLC0415

    assert set(CoreCertificate.__dataclass_fields__) == {
        "version",
        "source_sha256",
        "spec_sha256",
        "table_sha256",
        "provenance",
        "artifact_sha256",
        "numeric_profile",
        "checks",
        "declared_open",
        "interpretation",
    }


def test_k2_source_digest_is_the_submitted_bytes() -> None:
    """`source_sha256` is `sha256:` plus the digest of the EXACT submitted UTF-8 bytes.

    Accept: byte-identical round trip; a whitespace-only edit changes the digest; the digest has
    the contract-fixed prefix and no hash-domain prefix.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415

    first = verify_python_source(_FORMULA_SOURCE)
    repeated = verify_python_source(_FORMULA_SOURCE)
    whitespace_edit = verify_python_source("\n" + _FORMULA_SOURCE)
    assert isinstance(first, Verified)
    assert isinstance(repeated, Verified)
    assert isinstance(whitespace_edit, Verified)

    raw_digest = hashlib.sha256(_FORMULA_SOURCE.encode()).hexdigest()
    expected = "sha256:" + raw_digest
    assert first.certificate.source_sha256 == expected
    assert repeated.certificate.source_sha256 == expected
    assert whitespace_edit.certificate.source_sha256 != expected
    assert expected.removeprefix("sha256:") == raw_digest


def test_k3_checks_are_all_pass_by_construction() -> None:
    """No failure ever enters `checks`; anything unestablished goes to `declared_open`.

    Accept: `CertifiedCheck(id, status)` and the contract-fixed ordered ids; a variant introducing
    a non-pass status fails `mypy --strict`.
    """
    from verifier.pysrc import CertifiedCheck, Verified, verify_python_source  # noqa: PLC0415

    result = verify_python_source(
        _DATASET_SOURCE,
        declared_target=spec.DatasetTarget(path="measurements.csv", content=_DATASET_BYTES),
    )
    assert isinstance(result, Verified)
    assert set(CertifiedCheck.__dataclass_fields__) == {"id", "status"}
    assert tuple(check.id for check in result.certificate.checks) == (
        "prescan",
        "admission",
        "projection",
        "target_binding",
        "recomputation",
        "integrity",
    )
    assert {check.status for check in result.certificate.checks} == {"pass"}


def test_k4_declared_open_always_names_the_artifact_gap() -> None:
    """The PNG is never compared against this table -- M10 observation owns that -- and the
    formula arm without a `FormulaTarget` also carries the intent gap.

    Accept: both strings byte-pinned; the artifact gap present in BOTH arms, the intent gap
    present exactly when no `FormulaTarget` was consumed.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415

    dataset = verify_python_source(
        _DATASET_SOURCE,
        declared_target=spec.DatasetTarget(path="measurements.csv", content=_DATASET_BYTES),
    )
    formula_internal = verify_python_source(_FORMULA_SOURCE)
    formula_targeted = verify_python_source(
        _FORMULA_SOURCE,
        declared_target=_formula_target(),
    )
    assert isinstance(dataset, Verified)
    assert isinstance(formula_internal, Verified)
    assert isinstance(formula_targeted, Verified)

    assert set(dataset.certificate.declared_open) == {_ARTIFACT_GAP}
    assert set(formula_internal.certificate.declared_open) == {
        _ARTIFACT_GAP,
        _INTENT_GAP,
        _NO_ARTIFACT,
    }
    assert set(formula_targeted.certificate.declared_open) == {_ARTIFACT_GAP, _NO_ARTIFACT}
    for result in (dataset, formula_internal, formula_targeted):
        assert result.certificate.artifact_sha256 is None


def test_k5_provenance_matrix() -> None:
    """`provenance = "artifact"` only when every plotted number derives from user-supplied bytes:
    the dataset arm with a matched target, or the formula arm with a `FormulaTarget`. Otherwise
    `"internal"`.

    Accept: the full arm x target matrix, each cell pinned.
    """
    from verifier.pysrc import Refused, Verified, verify_python_source  # noqa: PLC0415

    dataset_target = spec.DatasetTarget(path="measurements.csv", content=_DATASET_BYTES)
    formula_target = _formula_target()
    dataset_results = (
        verify_python_source(_DATASET_SOURCE),
        verify_python_source(_DATASET_SOURCE, declared_target=dataset_target),
        verify_python_source(_DATASET_SOURCE, declared_target=formula_target),
    )
    assert isinstance(dataset_results[0], Refused)
    assert dataset_results[0].code == "source_not_supplied"
    assert isinstance(dataset_results[1], Verified)
    assert dataset_results[1].certificate.provenance == "artifact"
    assert isinstance(dataset_results[2], Refused)
    assert dataset_results[2].code == "source_not_supplied"

    formula_results = (
        verify_python_source(_FORMULA_SOURCE),
        verify_python_source(_FORMULA_SOURCE, declared_target=dataset_target),
        verify_python_source(_FORMULA_SOURCE, declared_target=formula_target),
    )
    assert all(isinstance(result, Verified) for result in formula_results)
    assert [
        result.certificate.provenance for result in formula_results if isinstance(result, Verified)
    ] == ["internal", "internal", "artifact"]


def test_k6_interpretation_is_plain_words_and_model_free() -> None:
    """Arm, mark, what x and y are, sample or row count, labels, numeric profile, and -- formula
    arm -- the expression and grid printed back for the reader to check against their own request.

    Accept: the contract's byte-pinned string for one witness per arm; label sentences append as
    `X label:`, `Y label:`, `Title:` in that order; submitted identifiers do not survive.
    """
    from verifier.pysrc import Verified, verify_python_source  # noqa: PLC0415

    dataset_source = (
        "import pandas as pd\n"
        "import matplotlib.pyplot as plt\n"
        'frame = pd.read_csv("sales.csv")\n'
        'plt.bar(frame["region"], frame["revenue"])\n'
        "plt.show()\n"
    )
    dataset_bytes = b"region,revenue\nnorth,1\nsouth,2\neast,3\nwest,4\n"
    formula_source = (
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "grid_points = np.linspace(0, 10, num=101)\n"
        "curve_values = np.sin(grid_points)\n"
        "plt.plot(grid_points, curve_values)\n"
        "plt.show()\n"
    )
    dataset = verify_python_source(
        dataset_source,
        declared_target=spec.DatasetTarget(path="sales.csv", content=dataset_bytes),
    )
    formula = verify_python_source(formula_source)
    assert isinstance(dataset, Verified)
    assert isinstance(formula, Verified)

    dataset_interpretation = (
        'Chart type: bar. The data comes from the file "sales.csv". X shows the column "region". '
        'Y shows the column "revenue". The chart draws 4 rows. Numbers follow the profile '
        "binary64-libm-v1."
    )
    formula_interpretation = (
        "Chart type: line. The data comes from the submitted program. Y computes sin(x). X runs "
        "from 0 to 10 in 101 samples. Numbers follow the profile binary64-libm-v1."
    )
    assert dataset.certificate.interpretation == dataset_interpretation
    assert formula.certificate.interpretation == formula_interpretation

    dataset_labeled = verify_python_source(
        dataset_source.replace(
            'plt.bar(frame["region"], frame["revenue"])',
            'plt.bar(frame["region"], frame["revenue"])\n'
            'plt.title("Clinical values")\n'
            'plt.xlabel("Region")\n'
            'plt.ylabel("Revenue")',
        ),
        declared_target=spec.DatasetTarget(path="sales.csv", content=dataset_bytes),
    )
    formula_labeled = verify_python_source(
        formula_source.replace(
            "plt.plot(grid_points, curve_values)",
            "plt.plot(grid_points, curve_values)\n"
            'plt.title("Sine values")\n'
            'plt.xlabel("Input")\n'
            'plt.ylabel("Output")',
        )
    )
    assert isinstance(dataset_labeled, Verified)
    assert isinstance(formula_labeled, Verified)

    for result, base, labels in (
        (dataset_labeled, dataset_interpretation, ("Region", "Revenue", "Clinical values")),
        (formula_labeled, formula_interpretation, ("Input", "Output", "Sine values")),
    ):
        interpretation = result.certificate.interpretation
        assert interpretation.startswith(base)
        positions = tuple(
            interpretation.index(prefix) for prefix in ("X label:", "Y label:", "Title:")
        )
        assert positions == tuple(sorted(positions))
        for label in labels:
            assert label in interpretation

    for identifier in ("frame", "grid_points", "curve_values"):
        for result in (dataset, formula, dataset_labeled, formula_labeled):
            assert identifier not in result.certificate.interpretation
