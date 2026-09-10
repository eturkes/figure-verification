import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent / "s6-data"
ROOT.mkdir(exist_ok=True)
CSV = ROOT / "floats.csv"
ROWS = 250_000
SEED = 0x5336435356
FINITE_LIMIT = np.uint64(0x7FF0000000000000)
rng = np.random.default_rng(SEED)

bits = rng.integers(0, FINITE_LIMIT, size=ROWS * 3, dtype=np.uint64)
bits |= rng.integers(0, 2, size=bits.size, dtype=np.uint64) << np.uint64(63)
values = bits.view(np.float64).reshape(ROWS, 3)
stress = (
    "0",
    "-0",
    "0.0",
    "-0.0",
    "0e0",
    "-0e0",
    "0.10000000000000001",
    "0.99999999999999989",
    "1.0000000000000000",
    "1.0000000000000002",
    "1.2345678901234567",
    "-1.2345678901234567",
    "9.9999999999999995e-7",
    "1.0000000000000000e+20",
    "9.9999999999999995e+20",
    "4.9406564584124654e-324",
    "9.8813129168249309e-324",
    "2.2250738585072009e-308",
    "2.2250738585072014e-308",
    "1.7976931348623155e+308",
    "1.7976931348623157e+308",
    "9007199254740991",
    "9007199254740992",
    "9007199254740993",
    "1.00000000000000011102230246251565404236316680908203125",
    "1.00000000000000011102230246251565404236316680908203124",
    "1.00000000000000011102230246251565404236316680908203126",
    "2.4703282292062327e-324",
    "2.4703282292062328e-324",
    "7.4109846876186982e-324",
    "7.4109846876186983e-324",
)
with CSV.open("w", encoding="ascii", newline="") as output:
    output.write("shortest,g17,scientific17,stress\n")
    for index, (shortest, g17, scientific) in enumerate(values):
        output.write(
            f"{float(shortest)!r},"
            f"{format(float(g17), '.17g')},"
            f"{format(float(scientific), '.16e')},"
            f"{stress[index % len(stress)]}\n"
        )

frame = pd.read_csv(CSV)
parsed = frame.to_numpy(dtype=np.float64)
reference = ROOT / "host.f64le"
parsed.astype("<f8", copy=False).tofile(reference)
manifest = {
    "python": __import__("sys").version.split()[0],
    "numpy": np.__version__,
    "pandas": pd.__version__,
    "seed": SEED,
    "rows": ROWS,
    "columns": list(frame.columns),
    "values": int(parsed.size),
    "dtypes": [str(dtype) for dtype in frame.dtypes],
    "stress_token_count": len(stress),
    "csv_sha256": hashlib.sha256(CSV.read_bytes()).hexdigest(),
    "host_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(json.dumps(manifest, sort_keys=True))
