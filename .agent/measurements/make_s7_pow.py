"""S7 -- `pow` inputs + the three host legs N8 needs.

N7 puts `pow` in the libm-dependent class but the band was never measured for it, and `pow` is the
only admitted binary op whose CPython scalar spelling disagrees with numpy on WHOLE CASES rather
than on a last bit: `(-8.0) ** 0.5` returns a COMPLEX in CPython, `math.pow(-8.0, 0.5)` raises, and
`np.power` returns nan. So this records three host legs, not one.
"""

import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent / "s7-data"
ROOT.mkdir(exist_ok=True)
N = 1_000_000
SEED = 0x5337504F57
rng = np.random.default_rng(SEED)

# Exception classes, recorded per element so the mapping rule is derived from data, not assumed.
OK = 0
VALUE_ERROR = 1
OVERFLOW_ERROR = 2
ZERO_DIVISION = 3
COMPLEX_RESULT = 4


def random_finite(count: int, *, positive: bool = False) -> np.ndarray:
    bits = rng.integers(0, np.uint64(0x7FF0000000000000), size=count, dtype=np.uint64)
    if not positive:
        bits |= rng.integers(0, 2, size=count, dtype=np.uint64) << np.uint64(63)
    return bits.view(np.float64)


def build() -> tuple[np.ndarray, np.ndarray]:
    grid = np.linspace(0.0, 6.283185307179586, 100)
    parts_base = [grid]
    parts_exp = [np.full(100, 2.0)]

    # Positive base, exponent scaled so the true result stays inside the finite range: the band is
    # about rounding, and an all-inf stratum measures nothing.
    magnitude = np.power(10.0, rng.uniform(-300.0, 300.0, 199_900))
    span = np.log2(magnitude)
    safe = np.where(np.abs(span) < 1e-12, 1.0, span)
    limit = 1023.0 / np.abs(safe)
    parts_base.append(magnitude)
    parts_exp.append(rng.uniform(-1.0, 1.0, 199_900) * np.minimum(limit, 1e3))

    # Negative base with an INTEGRAL exponent: well defined everywhere, and the case a chart hits.
    neg = -np.power(10.0, rng.uniform(-30.0, 30.0, 150_000))
    parts_base.append(neg)
    parts_exp.append(rng.integers(-64, 65, size=150_000).astype(np.float64))

    # Negative base with a NON-integral exponent: the divergence stratum.
    parts_base.append(-np.power(10.0, rng.uniform(-30.0, 30.0, 150_000)))
    parts_exp.append(rng.uniform(-64.0, 64.0, 150_000) + 0.5)

    # Signed zero base against every exponent sign, including integral and non-integral.
    zero_sign = np.where(rng.integers(0, 2, size=100_000), 0.0, -0.0)
    zero_exp = rng.uniform(-64.0, 64.0, 100_000)
    zero_exp[::3] = np.trunc(zero_exp[::3])
    parts_base.append(zero_sign)
    parts_exp.append(zero_exp)

    # Base within 1e6 ulp of 1 against a huge exponent: catastrophic cancellation in log(base).
    parts_base.append(1.0 + rng.integers(-1_000_000, 1_000_001, size=100_000) * np.spacing(1.0))
    parts_exp.append(
        np.power(10.0, rng.uniform(0.0, 17.0, 100_000))
        * np.where(rng.integers(0, 2, size=100_000), 1.0, -1.0)
    )

    # Straddle the overflow and underflow edges, where an off-by-one-ulp result flips to inf or 0.
    edge_base = rng.uniform(1.0000001, 10.0, 100_000)
    edge_exp = (1024.0 / np.log2(edge_base)) * rng.uniform(0.995, 1.005, 100_000)
    parts_base.append(edge_base)
    parts_exp.append(edge_exp * np.where(rng.integers(0, 2, size=100_000), 1.0, -1.0))

    # The literal chart case: `x ** 2`, `x ** 3`.
    parts_base.append(random_finite(100_000))
    parts_exp.append(rng.integers(0, 11, size=100_000).astype(np.float64))

    # Unstructured pairs.
    parts_base.append(random_finite(100_000))
    parts_exp.append(random_finite(100_000))

    base = np.concatenate(parts_base)
    exponent = np.concatenate(parts_exp)
    assert base.size == N and exponent.size == N
    assert np.isfinite(base).all() and np.isfinite(exponent).all()
    return base, exponent


REGIONS = [
    [0, 100, "exact np.linspace(0,2pi,100) ** 2"],
    [100, 200_000, "positive base 1e-300..1e300, exponent held inside the finite range"],
    [200_000, 350_000, "negative base, integral exponent |k|<=64"],
    [350_000, 500_000, "negative base, non-integral exponent"],
    [500_000, 600_000, "signed zero base, mixed-sign integral + non-integral exponent"],
    [600_000, 700_000, "base within 1e6 ulp of 1, |exponent| up to 1e17"],
    [700_000, 800_000, "overflow/underflow edge, base in (1,10]"],
    [800_000, 900_000, "random finite base, integral exponent 0..10"],
    [900_000, 1_000_000, "random finite float64 bit patterns, both operands"],
]


def host_scalar_legs(
    base: np.ndarray, exponent: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """`math.pow` and `**` element by element, each with its exception class."""
    mp = np.empty(N, dtype=np.float64)
    mp_exc = np.zeros(N, dtype=np.uint8)
    ss = np.empty(N, dtype=np.float64)
    ss_exc = np.zeros(N, dtype=np.uint8)
    b_list = base.tolist()
    e_list = exponent.tolist()
    for i in range(N):
        b = b_list[i]
        e = e_list[i]
        try:
            mp[i] = math.pow(b, e)
        except ValueError:
            mp[i] = math.nan
            mp_exc[i] = VALUE_ERROR
        except OverflowError:
            mp[i] = math.nan
            mp_exc[i] = OVERFLOW_ERROR
        try:
            value = b**e
        except ZeroDivisionError:
            ss[i] = math.nan
            ss_exc[i] = ZERO_DIVISION
        except OverflowError:
            ss[i] = math.nan
            ss_exc[i] = OVERFLOW_ERROR
        else:
            if isinstance(value, complex):
                ss[i] = math.nan
                ss_exc[i] = COMPLEX_RESULT
            else:
                ss[i] = value
    return mp, mp_exc, ss, ss_exc


def classify(values: np.ndarray) -> np.ndarray:
    """0 finite, 1 +inf, 2 -inf, 3 nan -- the categories a mapping rule must reproduce."""
    out = np.zeros(values.size, dtype=np.uint8)
    out[np.isposinf(values)] = 1
    out[np.isneginf(values)] = 2
    out[np.isnan(values)] = 3
    return out


def compare(name: str, values: np.ndarray, exc: np.ndarray, reference: np.ndarray) -> dict:
    """Cross-tabulate the scalar leg's exception class against numpy's value category."""
    ref_class = classify(reference)
    table: dict[str, int] = {}
    for exc_value in np.unique(exc):
        for ref_value in np.unique(ref_class[exc == exc_value]):
            key = f"exc={int(exc_value)},np={int(ref_value)}"
            table[key] = int(np.count_nonzero((exc == exc_value) & (ref_class == ref_value)))
    clean = exc == OK
    both_finite = clean & (ref_class == 0)
    agree_bits = np.zeros(N, dtype=bool)
    agree_bits[both_finite] = (
        values[both_finite].view(np.uint64)[: np.count_nonzero(both_finite)]
        == reference[both_finite].view(np.uint64)[: np.count_nonzero(both_finite)]
    )
    same_category = classify(values) == ref_class
    return {
        "leg": name,
        "exception_by_numpy_category": table,
        "no_exception": int(np.count_nonzero(clean)),
        "category_agrees": int(np.count_nonzero(same_category & clean)),
        "category_disagrees": int(np.count_nonzero(~same_category & clean)),
        "both_finite": int(np.count_nonzero(both_finite)),
        "both_finite_bit_equal": int(np.count_nonzero(agree_bits)),
    }


base, exponent = build()
with np.errstate(all="ignore"):
    host_np = np.power(base, exponent)
mathpow, mathpow_exc, starstar, starstar_exc = host_scalar_legs(base, exponent)

files: dict[str, str] = {}
for name, array in (
    ("base.f64le", base),
    ("exp.f64le", exponent),
    ("host-np.f64le", host_np),
    ("host-mathpow.f64le", mathpow),
    ("host-starstar.f64le", starstar),
):
    path = ROOT / name
    array.astype("<f8", copy=False).tofile(path)
    files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
for name, array in (("host-mathpow-exc.u8", mathpow_exc), ("host-starstar-exc.u8", starstar_exc)):
    path = ROOT / name
    array.tofile(path)
    files[name] = hashlib.sha256(path.read_bytes()).hexdigest()

manifest = {
    "python": __import__("sys").version.split()[0],
    "numpy": np.__version__,
    "seed": SEED,
    "samples": N,
    "regions": REGIONS,
    "files": files,
    "exception_classes": {
        "0": "no exception",
        "1": "ValueError",
        "2": "OverflowError",
        "3": "ZeroDivisionError",
        "4": "complex result",
    },
    "numpy_categories": {"0": "finite", "1": "+inf", "2": "-inf", "3": "nan"},
    "legs": [
        compare("math.pow", mathpow, mathpow_exc, host_np),
        compare("**", starstar, starstar_exc, host_np),
    ],
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(json.dumps(manifest, sort_keys=True))
