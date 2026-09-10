import json
import math
import time

import numpy as np

N = 1_000_000
SEED = 0x4D31335535
SIGN = np.uint64(1 << 63)
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
    directions = np.where(rng.integers(0, 2, size=poles.size), np.inf, -np.inf)
    poles = np.nextafter(poles, directions)
    magnitude = np.power(10.0, rng.uniform(6.0, 300.0, 250_000))
    large = magnitude * np.where(rng.integers(0, 2, size=magnitude.size), 1.0, -1.0)
    raw = finite_bits(250_000)
    values = np.concatenate((grid, sub_bits.view(np.float64), moderate, poles, large, raw))
    assert values.size == N and np.isfinite(values).all()
    return values


def exp_inputs() -> np.ndarray:
    grid = np.linspace(0.0, 6.283185307179586, 100)
    near_zero = finite_bits(199_900)
    near_zero = np.ldexp(np.sign(near_zero), -1074) * (np.abs(near_zero.view(np.uint64) % 4096))
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


def ordered(bits: np.ndarray) -> np.ndarray:
    return np.where(bits & SIGN, ~bits, bits | SIGN)


def measure(name: str, values: np.ndarray) -> dict[str, object]:
    scalar = getattr(math, name)
    vector = getattr(np, name)
    started = time.perf_counter()
    host_math = np.fromiter((scalar(float(x)) for x in values), dtype=np.float64, count=values.size)
    with np.errstate(all="ignore"):
        host_numpy = vector(values)
    math_bits = host_math.view(np.uint64)
    numpy_bits = host_numpy.view(np.uint64)
    mismatch = math_bits != numpy_bits
    left = ordered(math_bits)
    right = ordered(numpy_bits)
    distances = np.maximum(left, right) - np.minimum(left, right)
    worst_index = int(np.argmax(distances))
    return {
        "samples": int(values.size),
        "disagreements": int(np.count_nonzero(mismatch)),
        "max_ulp": int(distances[worst_index]),
        "worst_input_hex": float(values[worst_index]).hex(),
        "math_output_hex": float(host_math[worst_index]).hex(),
        "numpy_output_hex": float(host_numpy[worst_index]).hex(),
        "seconds": round(time.perf_counter() - started, 6),
    }


trig = trig_inputs()
positive = positive_inputs()
results = {
    "python": __import__("sys").version.split()[0],
    "numpy": np.__version__,
    "seed": SEED,
    "regions": {
        "trig": (
            "100 exact linspace(0,2pi,100); 99,900 signed subnormals/zero; "
            "200,000 uniform [-1e3,1e3]; 200,000 one-ulp from k*pi/2, |k|<=1e6; "
            "250,000 log-uniform magnitudes 1e6..1e300; 250,000 random finite bit patterns"
        ),
        "exp": (
            "100 exact linspace(0,2pi,100); "
            "199,900 signed values within 4095 min-subnormal steps of zero; "
            "300,000 uniform [-100,100]; 200,000 [-745,-700]; "
            "200,000 [700,709.7827128933839]; 100,000 full finite-output interval"
        ),
        "log_sqrt": (
            "99 positive exact linspace-grid values; 99,901 positive subnormals; "
            "200,000 values within 1,000,000 ulp of 1; 700,000 random positive finite bit patterns"
        ),
    },
}
for fn in ("sin", "cos", "tan"):
    results[fn] = measure(fn, trig)
results["exp"] = measure("exp", exp_inputs())
for fn in ("log", "sqrt"):
    results[fn] = measure(fn, positive)
print(json.dumps(results, indent=2, sort_keys=True))
