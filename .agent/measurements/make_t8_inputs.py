# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""T8: seeded fixed-point range probes; retained C10 digit cap tracked separately."""

import csv
import hashlib
import json
import random
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parent / "t8-data"
SEED = 202_610_020_012
LOW = 2**31
HIGH = 2**53
PER_STRATUM = 4096
PROFILE_SAMPLES = 262_144
MIXED_SAMPLES = 1_000_000


def scaled_token(value: int, places: int) -> str:
    sign = "-" if value < 0 else ""
    digits = str(abs(value))
    return f"{sign}{digits[:-places]}.{digits[-places:]}"


def metadata(token: str) -> bytes:
    magnitude = token.lstrip("-")
    whole, _, fraction = magnitude.partition(".")
    return bytes(
        (
            int(whole).bit_length() - 1,
            token.startswith("-"),
            len(fraction),
            len(whole.lstrip("0") + fraction),
        )
    )


def boundaries() -> list[str]:
    tokens = set()
    for base in [2**power for power in range(31, 54)] + [10**power for power in range(10, 16)]:
        for places in range(1, 7):
            scale = 10**places
            for delta in (-1001, -10, -1, 0, 1, 10, 1001):
                value = base * scale + delta
                if LOW * scale <= value <= HIGH * scale:
                    for sign in (-1, 1):
                        tokens.add(scaled_token(sign * value, places))
    for token in ("99999999999999.9", "-99999999999999.9"):
        tokens.add(token)
    return sorted(tokens, key=lambda token: (abs(float(token)), token))


class Corpus:
    def __init__(self, stack: ExitStack, name: str) -> None:
        self.plain: TextIO = stack.enter_context((ROOT / f"{name}.csv").open("w", encoding="ascii"))
        self.quoted: TextIO = stack.enter_context(
            (ROOT / f"{name}-quoted.csv").open("w", encoding="ascii")
        )
        self.meta = stack.enter_context((ROOT / f"{name}.meta.u8").open("wb"))
        self.plain.write("x\n")
        self.quoted.write('"x"\n')
        self.count = 0
        self.bins: Counter[tuple[int, int, int, int]] = Counter()

    def add(self, token: str) -> None:
        record = metadata(token)
        assert len(record) == 4 and 31 <= record[0] <= 53
        assert LOW <= abs(float(token)) <= HIGH
        self.plain.write(token + "\n")
        self.quoted.write('"' + token + '"\n')
        self.meta.write(record)
        self.count += 1
        self.bins[tuple(record)] += 1

    def summary(self) -> dict[str, object]:
        return {
            "rows": self.count,
            "retained_digit_profile_rows": sum(n for key, n in self.bins.items() if key[3] <= 15),
            "strata": [
                {
                    "binary_exponent": key[0],
                    "negative": bool(key[1]),
                    "decimal_places": key[2],
                    "significant_digits": key[3],
                    "rows": n,
                }
                for key, n in sorted(self.bins.items())
            ],
        }


def main() -> None:
    ROOT.mkdir(exist_ok=True)
    rng = random.Random(SEED)  # noqa: S311 — deterministic arbitrary-width corpus sampling
    probes = boundaries()
    valid_strata = [
        (power, places)
        for power in range(31, 53)
        for places in range(1, 7)
        if len(str(2**power)) + places <= 15
    ]
    with ExitStack() as stack:
        decimals = Corpus(stack, "decimals")
        for power in range(31, 53):
            for places in range(1, 7):
                scale = 10**places
                for sign in (-1, 1):
                    for _ in range(PER_STRATUM):
                        value = rng.randrange(2**power * scale, 2 ** (power + 1) * scale)
                        decimals.add(scaled_token(sign * value, places))
        for index in range(PROFILE_SAMPLES):
            power, places = valid_strata[index % len(valid_strata)]
            scale = 10**places
            ceiling = min(2 ** (power + 1) * scale - 1, 10**15 - 1)
            value = rng.randint(2**power * scale, ceiling)
            decimals.add(scaled_token((-1 if index % 2 else 1) * value, places))
        for token in probes:
            decimals.add(token)
        mixed = Corpus(stack, "mixed")
        # One decimal token selects pandas' float64 path for every integer token in this column.
        mixed.add(f"{LOW}.0")
        for power in range(31, 54):
            for sign in (-1, 1):
                mixed.add(str(sign * 2**power))
        mixed.add("999999999999999")
        mixed.add("-999999999999999")
        for index in range(MIXED_SAMPLES):
            power = 31 + index % 22
            value = rng.randrange(2**power, 2 ** (power + 1))
            mixed.add(str((-1 if (index // 22) % 2 else 1) * value))
        summary = {"decimals": decimals.summary(), "mixed": mixed.summary()}
    with (ROOT / "bar.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["x"])
        writer.writerows([token] for token in probes)
    files = [path for path in ROOT.iterdir() if path.suffix in (".csv", ".u8")]
    payload = {
        "seed": SEED,
        "magnitude_range": [LOW, HIGH],
        "decimal_places_range": [1, 6],
        "significant_digits_range": [11, 22],
        "composition": {
            "uniform_per_sign_exponent_places": PER_STRATUM,
            "retained_profile_extra": PROFILE_SAMPLES,
            "decimal_boundary_rows": len(probes),
        },
        "corpora": summary,
        "bar_rows": len(probes),
        "sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)
        },
    }
    (ROOT / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {key: value for key, value in payload.items() if key != "corpora"}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
