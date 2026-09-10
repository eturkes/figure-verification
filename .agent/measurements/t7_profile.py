import json
from fractions import Fraction
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SEED = 0x4D31335535435356
DECIMAL_SAMPLES = 1_000_000
INTEGER_SAMPLES = 1_000_000
INT_MIN = -(2**31)
INT_MAX = 2**31 - 1
TARGET_BASES = tuple(
    dict.fromkeys(
        [
            Fraction(0),
            Fraction(1, 10),
            Fraction(1),
            Fraction(10),
            Fraction(INT_MIN),
            Fraction(INT_MAX),
        ]
        + [Fraction(sign * 2**power) for power in range(31) for sign in (-1, 1)]
        + [Fraction(sign * 10**power) for power in range(10) for sign in (-1, 1)]
    )
)


def render_scaled(value: int, places: int) -> str:
    sign = "-" if value < 0 else ""
    digits = str(abs(value)).zfill(places + 1)
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


def significant_digits(token: str) -> int:
    digits = token.lstrip("-").replace(".", "").lstrip("0")
    return len(digits) if digits else 1


def build_decimals() -> list[str]:
    rng = np.random.default_rng(SEED)
    tokens: list[str] = []
    while len(tokens) < 800_000:
        places = int(rng.integers(1, 7))
        scale = 10**places
        value = int(rng.integers(INT_MIN * scale, INT_MAX * scale + 1, dtype=np.int64))
        token = render_scaled(value, places)
        if significant_digits(token) <= 15:
            tokens.append(token)
    while len(tokens) < DECIMAL_SAMPLES:
        places = int(rng.integers(1, 7))
        scale = 10**places
        base = TARGET_BASES[int(rng.integers(0, len(TARGET_BASES)))]
        center = round(base * scale)
        value = max(INT_MIN * scale, min(INT_MAX * scale, center + int(rng.integers(-4096, 4097))))
        token = render_scaled(value, places)
        if significant_digits(token) <= 15:
            tokens.append(token)
    rng.shuffle(tokens)
    assert len(tokens) == DECIMAL_SAMPLES
    assert all(
        "e" not in token.lower() and 1 <= significant_digits(token) <= 15 for token in tokens
    )
    assert all(1 <= len(token.split(".")[1]) <= 6 for token in tokens)
    assert all(INT_MIN <= float(token) <= INT_MAX for token in tokens)
    assert all(not (token.startswith("-") and float(token) == 0.0) for token in tokens)
    return tokens


def compare_float_csv(tokens: list[str], path: Path) -> dict[str, object]:
    path.write_text("x\n" + "\n".join(tokens) + "\n", encoding="ascii")
    reference = np.fromiter((float(token) for token in tokens), dtype=np.float64, count=len(tokens))
    reference.astype("<f8", copy=False).tofile(ROOT / "t7-decimals.f64le")
    series = pd.read_csv(path)["x"]
    assert series.dtype == np.dtype(np.float64)
    observed = series.to_numpy(copy=False)
    mismatch = np.flatnonzero(reference.view(np.uint64) != observed.view(np.uint64))
    smallest = (
        min((int(i) for i in mismatch), key=lambda i: (len(tokens[i].encode()), tokens[i].encode()))
        if mismatch.size
        else None
    )
    return {
        "samples": len(tokens),
        "dtype": str(series.dtype),
        "mismatches": int(mismatch.size),
        "smallest_witness_bytes": repr(tokens[smallest].encode()) if smallest is not None else None,
        "stdlib_hex": reference[smallest].item().hex() if smallest is not None else None,
        "pandas_hex": observed[smallest].item().hex() if smallest is not None else None,
    }


def compare_integer_csv(path: Path) -> dict[str, object]:
    rng = np.random.default_rng(SEED ^ 0x494E54)
    values = rng.integers(INT_MIN, INT_MAX + 1, size=INTEGER_SAMPLES, dtype=np.int64)
    boundary = np.array([INT_MIN, INT_MIN + 1, -1, 0, 1, INT_MAX - 1, INT_MAX], dtype=np.int64)
    values[: len(boundary)] = boundary
    tokens = list(map(str, values.tolist()))
    path.write_text("x\n" + "\n".join(tokens) + "\n", encoding="ascii")
    reference = np.fromiter((float(token) for token in tokens), dtype=np.float64, count=len(tokens))
    reference.astype("<f8", copy=False).tofile(ROOT / "t7-integers.f64le")
    series = pd.read_csv(path)["x"]
    assert series.dtype == np.dtype(np.int64)
    observed = series.to_numpy(dtype=np.float64)
    mismatch = np.flatnonzero(reference.view(np.uint64) != observed.view(np.uint64))
    return {
        "samples": len(tokens),
        "dtype": str(series.dtype),
        "mismatches_after_float64_cast": int(mismatch.size),
    }


decimal_tokens = build_decimals()
payload = {
    "python": __import__("sys").version.split()[0],
    "pandas": pd.__version__,
    "numpy": np.__version__,
    "seed": SEED,
    "profile": {
        "notation": "fixed point only",
        "significant_digits_max": 15,
        "decimal_places_max": 6,
        "inclusive_value_range": [INT_MIN, INT_MAX],
        "negative_zero": "excluded",
    },
    "fixed_decimals": compare_float_csv(decimal_tokens, ROOT / "t7-decimals.csv"),
    "integers": compare_integer_csv(ROOT / "t7-integers.csv"),
    "decimal_composition": {"seeded_uniform": 800_000, "boundary_adjacent": 200_000},
}
(ROOT / "t7-profile.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, sort_keys=True))
