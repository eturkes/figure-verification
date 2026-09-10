import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SEED = 0x4D31335535
SAMPLES = 1_000_000
RANDOM_DECIMALS = 500_000
RANDOM_FLOATS = 400_000
TARGETED_FLOATS = 100_000
FINITE_LIMIT = np.uint64(0x7FF0000000000000)
TARGET_EXPONENTS = np.array(
    [-324, -323, -322, -309, -308, -307, -23, -22, -17, -16, -1, 0, 1, 15, 16, 17, 22, 23, 307],
    dtype=np.int64,
)
TINY = float.fromhex("0x0.0000000000001p-1022")
MIN_NORMAL = float.fromhex("0x1.0000000000000p-1022")
MAX_FINITE = float.fromhex("0x1.fffffffffffffp+1023")
STRESS = (
    TINY,
    math.nextafter(TINY, math.inf),
    float.fromhex("0x0.fffffffffffffp-1022"),
    MIN_NORMAL,
    math.nextafter(MIN_NORMAL, math.inf),
    math.nextafter(MIN_NORMAL, 0.0),
    0.1,
    math.nextafter(0.1, math.inf),
    math.nextafter(0.1, -math.inf),
    1.0,
    math.nextafter(1.0, math.inf),
    math.nextafter(1.0, -math.inf),
    float(2**53 - 1),
    float(2**53),
    float(2**53 + 2),
    1e-300,
    1e300,
    MAX_FINITE,
)


def ordered(values: np.ndarray) -> np.ndarray:
    bits = values.view(np.uint64)
    return np.where(bits >> np.uint64(63), ~bits, bits ^ np.uint64(1 << 63))


def scientific(coefficient: int, digits: int, exponent: int, *, negative: bool) -> str:
    raw = str(coefficient)
    mantissa = raw if digits == 1 else f"{raw[0]}.{raw[1:]}"
    return f"{'-' if negative else ''}{mantissa}e{exponent:+d}"


def finite_formatted(value: float, digits: int) -> str | None:
    token = format(value, f".{digits - 1}e")
    return token if math.isfinite(float(token)) else None


def build_tokens(digits: int, rng: np.random.Generator) -> list[str]:
    low = 10 ** (digits - 1)
    high = 10**digits
    coefficients = rng.integers(low, high, size=RANDOM_DECIMALS, dtype=np.int64)
    exponents = rng.integers(-323, 308, size=RANDOM_DECIMALS, dtype=np.int64)
    targeted = rng.random(RANDOM_DECIMALS) < 0.25
    exponents[targeted] = rng.choice(TARGET_EXPONENTS, size=int(targeted.sum()))
    negatives = rng.integers(0, 2, size=RANDOM_DECIMALS, dtype=np.int8)
    tokens = [
        scientific(int(c), digits, int(e), negative=bool(sign))
        for c, e, sign in zip(coefficients, exponents, negatives, strict=True)
    ]

    needed = RANDOM_FLOATS
    while needed:
        raw = rng.integers(1, FINITE_LIMIT, size=needed, dtype=np.uint64)
        raw |= rng.integers(0, 2, size=needed, dtype=np.uint64) << np.uint64(63)
        for value in raw.view(np.float64):
            token = finite_formatted(float(value), digits)
            if token is not None:
                tokens.append(token)
                needed -= 1
                if needed == 0:
                    break

    signed_stress = STRESS + tuple(-value for value in STRESS)
    index = 0
    while len(tokens) < SAMPLES:
        token = finite_formatted(signed_stress[index % len(signed_stress)], digits)
        index += 1
        if token is not None:
            tokens.append(token)
    assert len(tokens) == SAMPLES
    rng.shuffle(tokens)
    return tokens


def measure(digits: int) -> dict[str, object]:
    rng = np.random.default_rng(SEED + digits)
    tokens = build_tokens(digits, rng)
    csv_path = ROOT / f"t3-{digits}.csv"
    csv_path.write_text("x\n" + "\n".join(tokens) + "\n", encoding="ascii")
    reference = np.fromiter((float(token) for token in tokens), dtype=np.float64, count=SAMPLES)
    series = pd.read_csv(csv_path)["x"]
    if series.dtype != np.dtype(np.float64):
        message = f"N={digits}: pandas dtype {series.dtype!s}, expected float64"
        raise AssertionError(message)
    observed = series.to_numpy(copy=False)
    ref_bits = reference.view(np.uint64)
    got_bits = observed.view(np.uint64)
    mismatch = np.flatnonzero(ref_bits != got_bits)
    distances = np.abs(
        ordered(reference)[mismatch].astype(object) - ordered(observed)[mismatch].astype(object)
    )
    smallest = (
        min(
            (int(i) for i in mismatch),
            key=lambda i: (len(tokens[i].encode("ascii")), tokens[i].encode("ascii")),
        )
        if mismatch.size
        else None
    )
    result: dict[str, object] = {
        "digits": digits,
        "samples": SAMPLES,
        "mismatches": int(mismatch.size),
        "min_ulp": int(min(distances)) if mismatch.size else 0,
        "max_ulp": int(max(distances)) if mismatch.size else 0,
        "smallest_witness_bytes": repr(tokens[smallest].encode("ascii"))
        if smallest is not None
        else None,
        "stdlib_hex": reference[smallest].item().hex() if smallest is not None else None,
        "pandas_hex": observed[smallest].item().hex() if smallest is not None else None,
    }
    csv_path.unlink()
    return result


results = [measure(digits) for digits in range(1, 18)]
payload = {
    "python": __import__("sys").version.split()[0],
    "pandas": pd.__version__,
    "numpy": np.__version__,
    "seed": SEED,
    "per_n": SAMPLES,
    "composition": {
        "random_decimal_scientific": RANDOM_DECIMALS,
        "random_binary64_formatted_scientific": RANDOM_FLOATS,
        "targeted_boundary_binary64_formatted_scientific": TARGETED_FLOATS,
    },
    "results": results,
}
(ROOT / "t3.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, sort_keys=True))
