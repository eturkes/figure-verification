import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent / "s3-data"
ROOT.mkdir(exist_ok=True)
SEED = 0x533347524944
CASE_COUNT = 10_000
MAX_EXACT_INT = 2**52
FINITE_LIMIT = np.uint64(0x7FF0000000000000)
rng = np.random.default_rng(SEED)


def sample_count(index: int) -> int:
    boundary = (2, 3, 50, 100, 1_000, 10_000, 100_000)
    if index % 997 == 0:
        return boundary[(index // 997) % len(boundary)]
    return int(rng.choice(np.array([2, 3, 4, 5, 10, 50, 100, 257, 1_000])))


def positive_finite() -> float:
    bits = rng.integers(0, FINITE_LIMIT, dtype=np.uint64)
    return float(np.array([bits], dtype=np.uint64).view(np.float64)[0])


def add_linspace(params: list[dict[str, object]], a: float, b: float, region: str) -> None:
    index = len(params)
    params.append({"a": a.hex(), "b": b.hex(), "n": sample_count(index), "region": region})


linspace: list[dict[str, object]] = []
fixed = [
    (0.0, 6.283185307179586, "canonical 0..2pi"),
    (-0.0, 0.0, "signed zeros"),
    (np.nextafter(0.0, 1.0), np.nextafter(0.0, 1.0) * 1000, "positive subnormals"),
    (np.nextafter(0.0, -1.0) * 1000, np.nextafter(0.0, -1.0), "negative subnormals"),
    (1.0, np.nextafter(1.0, np.inf), "adjacent near one"),
    (np.nextafter(1.0, -np.inf), 1.0, "adjacent below one"),
    (
        np.finfo(np.float64).tiny,
        np.nextafter(np.finfo(np.float64).tiny, np.inf),
        "adjacent normal boundary",
    ),
    (np.finfo(np.float64).max / 2, np.finfo(np.float64).max, "positive finite extreme"),
    (-np.finfo(np.float64).max, -np.finfo(np.float64).max / 2, "negative finite extreme"),
    (math.pi, -math.pi, "descending pi endpoints"),
]
for a, b, region in fixed:
    add_linspace(linspace, float(a), float(b), region)
linspace[0]["n"] = 100
while len(linspace) < 3_010:
    a, b = sorted(rng.uniform(-1_000_000.0, 1_000_000.0, size=2))
    if rng.integers(0, 2):
        a, b = b, a
    add_linspace(linspace, float(a), float(b), "moderate random endpoints")
while len(linspace) < 5_510:
    a = positive_finite()
    if rng.integers(0, 2):
        a = -a
    direction = np.inf if rng.integers(0, 2) else -np.inf
    b = float(np.nextafter(a, direction))
    if not math.isfinite(b):
        continue
    add_linspace(linspace, a, b, "adjacent broad-exponent endpoints")
while len(linspace) < 8_010:
    a, b = positive_finite(), positive_finite()
    a, b = sorted((a, b))
    if rng.integers(0, 2):
        a, b = -b, -a
    if rng.integers(0, 2):
        a, b = b, a
    add_linspace(linspace, a, b, "same-sign broad-exponent endpoints")
while len(linspace) < CASE_COUNT:
    left_bits = rng.integers(0, 1 << 52, dtype=np.uint64)
    right_bits = rng.integers(0, 1 << 52, dtype=np.uint64)
    a = float(np.array([left_bits], dtype=np.uint64).view(np.float64)[0])
    b = float(np.array([right_bits], dtype=np.uint64).view(np.float64)[0])
    if rng.integers(0, 2):
        a = -a
    if rng.integers(0, 2):
        b = -b
    add_linspace(linspace, a, b, "subnormal and signed-zero endpoints")

arange: list[dict[str, object]] = []
for index in range(CASE_COUNT):
    length = sample_count(index + CASE_COUNT)
    if index < 4_000:
        start = int(rng.integers(-1_000_000, 1_000_001))
        region = "moderate exact integers"
    elif index < 7_000:
        start = MAX_EXACT_INT - length - int(rng.integers(0, 10_000))
        region = "near +2**52 exact-integer bound"
    else:
        start = -MAX_EXACT_INT + int(rng.integers(0, 10_000))
        region = "near -2**52 exact-integer bound"
    stop = start + length
    style = "float" if index % 2 else "int"
    arange.append({"a": start, "b": stop, "style": style, "region": region})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_expected(kind: str, params: list[dict[str, object]]) -> tuple[int, dict[str, int]]:
    value_path = ROOT / f"host-{kind}.f64le"
    offsets = [0]
    dtype_counts: dict[str, int] = {}
    with value_path.open("wb") as output:
        for param in params:
            if kind == "linspace":
                values = np.linspace(
                    float.fromhex(str(param["a"])), float.fromhex(str(param["b"])), int(param["n"])
                )
            else:
                a, b = int(param["a"]), int(param["b"])
                values = (
                    np.arange(float(a), float(b)) if param["style"] == "float" else np.arange(a, b)
                )
            dtype_counts[str(values.dtype)] = dtype_counts.get(str(values.dtype), 0) + 1
            values.astype("<f8", copy=False).tofile(output)
            offsets.append(offsets[-1] + int(values.size))
    np.asarray(offsets, dtype="<u8").tofile(ROOT / f"host-{kind}-offsets.u64le")
    return offsets[-1], dtype_counts


(ROOT / "linspace.json").write_text(json.dumps(linspace, separators=(",", ":")))
(ROOT / "arange.json").write_text(json.dumps(arange, separators=(",", ":")))
linspace_values, linspace_dtypes = write_expected("linspace", linspace)
arange_values, arange_dtypes = write_expected("arange", arange)
files = {}
for path in sorted(ROOT.iterdir()):
    if path.is_file() and path.name != "manifest.json":
        files[path.name] = sha256(path)
manifest = {
    "python": __import__("sys").version.split()[0],
    "numpy": np.__version__,
    "seed": SEED,
    "cases": {"linspace": len(linspace), "arange": len(arange)},
    "values": {"linspace": linspace_values, "arange": arange_values},
    "host_dtypes": {"linspace": linspace_dtypes, "arange": arange_dtypes},
    "files": files,
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(json.dumps(manifest, sort_keys=True))
