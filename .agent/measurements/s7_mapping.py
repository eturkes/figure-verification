"""S7 leg 2 -- does an explicit C99 special-case mapping make `math.pow` reproduce numpy exactly?

The generator measured `math.pow`'s exception classes against numpy's value categories and found
ValueError covering THREE numpy answers (+inf 45,528 / -inf 4,236 / nan 176,382), so a blanket
`ValueError -> nan` is wrong on ~5% of the corpus. C99 pow says the ambiguity is resolvable from the
operands alone. This asserts that over the whole corpus, bit for bit.
"""

import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent / "s7-data"
N = 1_000_000
base = np.fromfile(ROOT / "base.f64le", dtype="<f8")
exponent = np.fromfile(ROOT / "exp.f64le", dtype="<f8")
reference = np.fromfile(ROOT / "host-np.f64le", dtype="<f8")
manifest = json.loads((ROOT / "manifest.json").read_text())


def is_odd_integer(value: float) -> bool:
    return value == math.trunc(value) and math.fmod(value, 2.0) != 0.0


def evaluate(b: float, e: float) -> float:
    """The candidate `numeric.py` pow: `math.pow`, with C99's special cases supplying the sign."""
    try:
        return math.pow(b, e)
    except OverflowError:
        # Magnitude overflowed. C99: the sign is negative only for a negative base raised to an
        # odd integer.
        return -math.inf if b < 0.0 and is_odd_integer(e) else math.inf
    except ValueError:
        if b == 0.0:
            # A pole, not a domain error: C99 gives +-inf for a zero base and a negative exponent.
            negative = math.copysign(1.0, b) < 0.0 and is_odd_integer(e)
            return -math.inf if negative else math.inf
        # Negative base, non-integral exponent -- the only true domain error left.
        return math.nan


b_list = base.tolist()
e_list = exponent.tolist()
computed = np.array([evaluate(b_list[i], e_list[i]) for i in range(N)], dtype=np.float64)

both_nan = np.isnan(computed) & np.isnan(reference)
bit_equal = computed.view(np.uint64) == reference.view(np.uint64)
agree = bit_equal | both_nan
disagreements = int(np.count_nonzero(~agree))

per_region = []
for start, stop, label in manifest["regions"]:
    window = ~agree[start:stop]
    per_region.append(
        {
            "region": label,
            "samples": stop - start,
            "disagreements": int(np.count_nonzero(window)),
        }
    )

witnesses = [
    {
        "index": index,
        "base_hex": float(base[index]).hex(),
        "exp_hex": float(exponent[index]).hex(),
        "computed_hex": float(computed[index]).hex(),
        "numpy_hex": float(reference[index]).hex(),
    }
    for index in np.flatnonzero(~agree)[:20].tolist()
]

# A mapping this specific must be shown to be doing work: the blanket rule the contract implied is
# rerun here so its failure count is on the record next to the specific rule's.
blanket = np.where(
    np.array([m != 0 for m in np.fromfile(ROOT / "host-mathpow-exc.u8", dtype=np.uint8)]),
    math.nan,
    np.fromfile(ROOT / "host-mathpow.f64le", dtype="<f8"),
)
blanket_agree = (blanket.view(np.uint64) == reference.view(np.uint64)) | (
    np.isnan(blanket) & np.isnan(reference)
)

result = {
    "samples": N,
    "specific_mapping_disagreements": disagreements,
    "blanket_value_error_to_nan_disagreements": int(np.count_nonzero(~blanket_agree)),
    "per_region": per_region,
    "witnesses": witnesses,
}
(Path(__file__).resolve().parent / "s7-mapping.json").write_text(
    json.dumps(result, indent=2, sort_keys=True) + "\n"
)
print(json.dumps(result, sort_keys=True))
