import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent / "s2-data"
ROOT.mkdir(exist_ok=True)
N = 1_000_000
SEED = 0x5332484F5354
FINITE_LIMIT = np.uint64(0x7FF0000000000000)
rng = np.random.default_rng(SEED)


def finite_bits(count: int, *, positive: bool = False) -> np.ndarray:
    bits = rng.integers(0, FINITE_LIMIT, size=count, dtype=np.uint64)
    if not positive:
        bits |= rng.integers(0, 2, size=count, dtype=np.uint64) << np.uint64(63)
    return bits.view(np.float64)


def trig_inputs() -> np.ndarray:
    grid = np.linspace(0.0, 6.283185307179586, 100)
    sub_bits = rng.integers(0, 1 << 52, size=99_900, dtype=np.uint64)
    sub_bits |= rng.integers(0, 2, size=sub_bits.size, dtype=np.uint64) << np.uint64(63)
    moderate = rng.uniform(-1_000.0, 1_000.0, 200_000)
    k = rng.integers(-1_000_000, 1_000_001, size=200_000)
    poles = k.astype(np.float64) * (math.pi / 2.0)
    poles = np.nextafter(poles, np.where(rng.integers(0, 2, size=poles.size), np.inf, -np.inf))
    magnitude = np.power(10.0, rng.uniform(6.0, 300.0, 250_000))
    large = magnitude * np.where(rng.integers(0, 2, size=magnitude.size), 1.0, -1.0)
    raw = finite_bits(250_000)
    values = np.concatenate((grid, sub_bits.view(np.float64), moderate, poles, large, raw))
    assert values.size == N and np.isfinite(values).all()
    return values


def exp_inputs() -> np.ndarray:
    grid = np.linspace(0.0, 6.283185307179586, 100)
    raw = finite_bits(199_900)
    near_zero = np.ldexp(np.sign(raw), -1074) * (np.abs(raw.view(np.uint64) % 4096))
    middle = rng.uniform(-100.0, 100.0, 300_000)
    low = rng.uniform(-745.0, -700.0, 200_000)
    high = rng.uniform(700.0, 709.7827128933839, 200_000)
    full = rng.uniform(-745.0, 709.7827128933839, 100_000)
    values = np.concatenate((grid, near_zero, middle, low, high, full))
    assert values.size == N and np.isfinite(values).all()
    return values


def positive_inputs() -> np.ndarray:
    grid = np.linspace(0.0, 6.283185307179586, 100)[1:]
    sub_bits = rng.integers(1, 1 << 52, size=99_901, dtype=np.uint64)
    near_one = 1.0 + rng.integers(-1_000_000, 1_000_001, size=200_000) * np.spacing(1.0)
    raw = finite_bits(700_000, positive=True)
    raw[raw == 0.0] = np.nextafter(0.0, 1.0)
    values = np.concatenate((grid, sub_bits.view(np.float64), near_one, raw))
    assert values.size == N and (values > 0.0).all() and np.isfinite(values).all()
    return values


arrays = {
    "trig": trig_inputs(),
    "exp": exp_inputs(),
    "positive": positive_inputs(),
}
functions = {
    "sin": "trig",
    "cos": "trig",
    "tan": "trig",
    "exp": "exp",
    "log": "positive",
    "sqrt": "positive",
}
regions = {
    "trig": [
        [0, 100, "exact np.linspace(0,2pi,100)"],
        [100, 100_000, "signed subnormal-or-zero bit patterns"],
        [100_000, 300_000, "uniform [-1e3,1e3]"],
        [300_000, 500_000, "one-ulp neighbor of k*pi/2, |k|<=1e6"],
        [500_000, 750_000, "log-uniform magnitude 1e6..1e300"],
        [750_000, 1_000_000, "random finite float64 bit pattern"],
    ],
    "exp": [
        [0, 100, "exact np.linspace(0,2pi,100)"],
        [100, 200_000, "signed values within 4095 min-subnormal steps of zero"],
        [200_000, 500_000, "uniform [-100,100]"],
        [500_000, 700_000, "uniform [-745,-700]"],
        [700_000, 900_000, "uniform [700,709.7827128933839]"],
        [900_000, 1_000_000, "uniform full finite-output interval"],
    ],
    "positive": [
        [0, 99, "positive points from exact np.linspace(0,2pi,100) grid"],
        [99, 100_000, "positive subnormal bit patterns"],
        [100_000, 300_000, "within 1,000,000 ulp of 1"],
        [300_000, 1_000_000, "random positive finite float64 bit pattern"],
    ],
}
manifest: dict[str, object] = {
    "python": __import__("sys").version.split()[0],
    "numpy": np.__version__,
    "seed": SEED,
    "samples_per_function": N,
    "regions": regions,
    "files": {},
}
for family, values in arrays.items():
    path = ROOT / f"input-{family}.f64le"
    values.astype("<f8", copy=False).tofile(path)
    manifest["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()  # type: ignore[index]
for function, family in functions.items():
    with np.errstate(all="ignore"):
        output = getattr(np, function)(arrays[family])
    path = ROOT / f"host-{function}.f64le"
    output.astype("<f8", copy=False).tofile(path)
    manifest["files"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()  # type: ignore[index]
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(json.dumps(manifest, sort_keys=True))
