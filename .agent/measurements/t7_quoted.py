import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
results = {}
for kind in ("decimals", "integers"):
    source = ROOT / f"t7-{kind}.csv"
    quoted = ROOT / f"t7-{kind}-quoted.csv"
    with (
        source.open(encoding="ascii") as incoming,
        quoted.open("w", encoding="ascii", newline="") as outgoing,
    ):
        next(incoming)
        outgoing.write('"x"\n')
        for line in incoming:
            outgoing.write(f'"{line.rstrip()}"\n')
    frame = pd.read_csv(quoted)
    observed = frame["x"].to_numpy(dtype=np.float64)
    reference = np.fromfile(ROOT / f"t7-{kind}.f64le", dtype="<f8")
    results[kind] = {
        "rows": len(frame),
        "source_dtype": str(frame["x"].dtype),
        "bit_mismatches_vs_host_stdlib_float": int(
            np.count_nonzero(observed.view(np.uint64) != reference.view(np.uint64))
        ),
    }
payload = {
    "python": __import__("sys").version.split()[0],
    "pandas": pd.__version__,
    "results": results,
}
(ROOT / "t7-quoted.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
print(json.dumps(payload, sort_keys=True))
