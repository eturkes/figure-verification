# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Generate fixed float64 and CSV group-reduction probes; stdlib-only."""

import csv
import hashlib
import json
import math
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "r-data"
ROOT.mkdir(exist_ok=True)
SEED = 13620260915
rng = random.Random(SEED)  # noqa: S311 - deterministic numeric corpus
cases = []


def add(name, values, family="witness"):
    cases.append({"name": name, "family": family, "hex": [float(v).hex() for v in values]})


for count in [1, 2, 10, 100, 1000, 10000]:
    add(f"one-plus-tiny-{count}", [1.0] + [1e-17] * count)
    add(f"large-small-cancel-{count}", [1e16] + [1.0] * count + [-1e16])
for name, values in [
    ("cancel-lost", [1e16, 1.0, -1e16]),
    ("cancel-kept", [1e16, -1e16, 1.0]),
    ("cancel-two", [1e16, 1.0, 1.0, -1e16]),
    ("binary-cancel", [2**53, 1.0, -(2**53)]),
    ("fsum-vs-kahan", [1.0, 1e100, 1.0, -1e100]),
    ("neg-pos-zero", [-0.0, 0.0]),
    ("pos-neg-zero", [0.0, -0.0]),
    ("negative-zeros", [-0.0, -0.0]),
    ("positive-zeros", [0.0, 0.0]),
    ("nan-gap", [1.0, math.nan, 2.0]),
    ("all-nan", [math.nan, math.nan]),
    ("inf-finite", [math.inf, 1.0]),
    ("finite-inf", [1.0, math.inf]),
    ("infinities-cancel", [math.inf, -math.inf]),
    ("overflow-finite", [float.fromhex("0x1.fffffffffffffp+1023")] * 2),
    ("overflow-cancel", [1e308, 1e308, -1e308]),
    ("subnormal", [float.fromhex("0x0.0000000000001p-1022")] * 19),
    ("decimal", [0.1] * 17),
    ("mean-rounding", [1.0, 1.0, math.nextafter(1.0, math.inf)]),
]:
    add(name, values)

for index in range(6000):
    count = rng.randint(3, 120)
    family = ["wide-signed", "wide-positive", "cancel", "tiny-tail", "fixed-point", "permuted"][
        index % 6
    ]
    if family in {"wide-signed", "wide-positive"}:
        values = [math.ldexp(rng.uniform(0.5, 1.0), rng.randint(-950, 950)) for _ in range(count)]
        if family == "wide-signed":
            values = [value if rng.getrandbits(1) else -value for value in values]
    elif family == "cancel":
        large = math.ldexp(rng.uniform(0.5, 1.0), rng.randint(-500, 500))
        small = math.ldexp(large, -rng.randint(45, 65))
        values = [large] + [small] * count + [-large]
    elif family == "tiny-tail":
        first = math.ldexp(rng.uniform(0.5, 1.0), rng.randint(-500, 500))
        values = [first] + [math.ldexp(first, -rng.randint(45, 65)) for _ in range(count)]
    elif family == "fixed-point":
        values = [rng.randint(-1_000_000_000, 1_000_000_000) / 1_000_000 for _ in range(count)]
    else:
        values = [1.0, 2.0**-53, -1.0, -(2.0**-53)] * (count // 4 + 1)
        rng.shuffle(values)
    add(f"random-{index:04d}", values, family)

(ROOT / "cases.json").write_text(
    json.dumps({"seed": SEED, "cases": cases}, separators=(",", ":")) + "\n"
)
with (ROOT / "stress.csv").open("w", encoding="ascii", newline="") as stream:
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["k", "v"])
    for row in range(max(len(case["hex"]) for case in cases)):
        for index, case in enumerate(cases):
            if row < len(case["hex"]):
                writer.writerow([index, repr(float.fromhex(case["hex"][row]))])

profile_groups = 4000
profile_values = []
for _index in range(profile_groups):
    count = rng.randint(2, 100)
    values = []
    for _ in range(count):
        scale = rng.randint(0, 6)
        whole = rng.randint(-1_000_000_000, 1_000_000_000)
        # <= 15 significant digits, signed int32 range, no sign-bearing zero.
        digits = str(abs(whole))
        if scale:
            digits = digits.zfill(scale + 1)
            text = digits[:-scale] + "." + digits[-scale:]
        else:
            text = digits
        values.append(("-" if whole < 0 else "") + text)
    profile_values.append(values)
profile = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?\Z")
for values in profile_values:
    for text in values:
        assert profile.fullmatch(text)
        assert len(text.removeprefix("-").replace(".", "").lstrip("0")) <= 15
        assert -(2**31) <= float(text) <= 2**31 - 1
        assert not (text.startswith("-") and float(text) == 0.0)
assert sum(map(len, profile_values)) == 202424
with (ROOT / "profile.csv").open("w", encoding="ascii", newline="") as stream:
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["k", "v"])
    for row in range(max(map(len, profile_values))):
        for index, values in enumerate(profile_values):
            if row < len(values):
                writer.writerow([f"g{index:04d}", values[row]])

manifest = {
    "seed": SEED,
    "exact_groups": len(cases),
    "exact_rows": sum(len(case["hex"]) for case in cases),
    "profile_groups": profile_groups,
    "profile_rows": sum(map(len, profile_values)),
    "files": {},
}
for name in ["cases.json", "stress.csv", "profile.csv"]:
    content = (ROOT / name).read_bytes()
    manifest["files"][name] = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(json.dumps(manifest, sort_keys=True))
