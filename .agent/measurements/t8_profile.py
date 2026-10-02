# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""T8 host/sandbox differential: pandas bits, retained digit profile, artist heights."""

import argparse
import csv
import hashlib
import io
import json
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def bit_diff(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    assert left.dtype == right.dtype == np.dtype(np.float64) and left.shape == right.shape
    return left.view(np.uint64) != right.view(np.uint64)


def witness(indices: np.ndarray, tokens: list[str], left: np.ndarray, right: np.ndarray) -> object:
    if not len(indices):
        return None
    index = int(indices[0])
    return {
        "index": index,
        "token": tokens[index],
        "left_hex": float(left[index]).hex(),
        "right_hex": float(right[index]).hex(),
    }


def comparison(
    tokens: list[str], reference: np.ndarray, observed: np.ndarray, metadata: np.ndarray
) -> dict[str, object]:
    mismatch = bit_diff(reference, observed)
    indices = np.flatnonzero(mismatch)
    order = np.argsort(np.abs(reference[indices]), kind="stable")
    candidate = metadata[:, 3] <= 15
    largest_candidate = int(np.argmax(np.where(candidate, np.abs(reference), -1.0)))
    groups = {}
    for column, name in enumerate(
        ("binary_exponent", "negative", "decimal_places", "significant_digits")
    ):
        groups[name] = [
            {
                "value": int(value),
                "rows": int(np.count_nonzero(metadata[:, column] == value)),
                "bit_mismatches": int(np.count_nonzero(mismatch & (metadata[:, column] == value))),
            }
            for value in np.unique(metadata[:, column])
        ]
    return {
        "rows": len(observed),
        "bit_mismatches": int(indices.size),
        "first_mismatch": witness(indices, tokens, reference, observed),
        "smallest_magnitude_mismatch": witness(indices[order], tokens, reference, observed),
        "max_measured_abs": float(np.max(np.abs(reference))),
        "largest_clean_sample_abs": float(np.max(np.abs(reference[~mismatch]))),
        "retained_digit_profile": {
            "rows": int(np.count_nonzero(candidate)),
            "bit_mismatches": int(np.count_nonzero(mismatch & candidate)),
            "max_measured_abs": float(np.abs(reference[largest_candidate])),
            "max_token": tokens[largest_candidate],
        },
        "groups": groups,
    }


def read_tokens(path: Path) -> list[str]:
    with path.open(encoding="ascii", newline="") as stream:
        reader = csv.reader(stream)
        assert next(reader) == ["x"]
        return [row[0] for row in reader]


def measure_corpus(data: Path, name: str, *, host: bool) -> dict[str, object]:
    tokens = read_tokens(data / f"{name}.csv")
    metadata = np.fromfile(data / f"{name}.meta.u8", dtype=np.uint8).reshape(-1, 4)
    assert metadata.shape == (len(tokens), 4) and len(tokens) >= 1_000_000
    stdlib = np.fromiter(map(float, tokens), dtype=np.float64, count=len(tokens))
    assert np.all(np.isfinite(stdlib))
    reference = None if host else np.fromfile(data / f"{name}.host.f64le", dtype="<f8")
    results = {}
    for form, suffix in (("plain", ""), ("quoted", "-quoted")):
        series = pd.read_csv(data / f"{name}{suffix}.csv")["x"]
        assert series.dtype == np.dtype(np.float64)
        observed = series.to_numpy(copy=False)
        if host and form == "plain":
            observed.astype("<f8", copy=False).tofile(data / f"{name}.host.f64le")
            reference = observed.copy()
            stdlib.astype("<f8", copy=False).tofile(data / f"{name}.stdlib.f64le")
        assert reference is not None
        control = reference.copy()
        control.view(np.uint64)[0] ^= np.uint64(1)
        planted = int(np.count_nonzero(bit_diff(reference, control)))
        assert planted == 1
        results[form] = {
            "dtype": str(series.dtype),
            "output_sha256": hashlib.sha256(
                observed.astype("<f8", copy=False).tobytes()
            ).hexdigest(),
            "vs_host_pandas": comparison(tokens, reference, observed, metadata),
            "vs_stdlib_float": comparison(tokens, stdlib, observed, metadata),
            "injected_one_bit_control": planted,
        }
    return results


def render_heights(data: Path) -> dict[str, object]:
    # The parser-only host leg has no matplotlib dependency.
    import matplotlib as mpl  # noqa: PLC0415

    mpl.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    results = {"matplotlib": mpl.__version__, "float64_paths": {}}
    for name, path in (("boundary_floats", data / "bar.csv"), ("mixed_column", data / "mixed.csv")):
        frame = pd.read_csv(path)
        assert frame["x"].dtype == np.dtype(np.float64)
        # Mixed rendering is a spot-check; parser differential covers the complete column.
        values = frame["x"] if name == "boundary_floats" else frame["x"].iloc[:2097]
        expected = values.to_numpy(copy=False)
        figure, axis = plt.subplots()
        try:
            axis.set_autoscale_on(False)
            axis.set(xlim=(-1.0, 1.0), ylim=(-1.0, 1.0))
            bars = axis.bar(pd.Series(np.arange(len(values)), dtype=np.int64), values)
            before = np.asarray([patch.get_height() for patch in bars.patches], dtype=np.float64)
            figure.canvas.draw()
            heights = [patch.get_height() for patch in bars.patches]
            observed = np.asarray(heights, dtype=np.float64)
            results["float64_paths"][name] = {
                "rows": len(values),
                "input_dtype": str(values.dtype),
                "height_types": sorted(
                    {f"{type(value).__module__}.{type(value).__qualname__}" for value in heights}
                ),
                "min_height": float(np.min(expected)),
                "max_height": float(np.max(expected)),
                "bit_mismatches_before_draw": int(np.count_nonzero(bit_diff(expected, before))),
                "bit_mismatches_after_draw": int(np.count_nonzero(bit_diff(expected, observed))),
                "draw_completed": True,
            }
        finally:
            plt.close(figure)
    probes = []
    for value in (-(2**53), -(2**31) - 1, -(2**31), 2**31 - 1, 2**31, 2**53):
        frame = pd.read_csv(io.StringIO(f"x,y\n0,{value}\n"))
        assert frame["y"].dtype == np.dtype(np.int64)
        figure, axis = plt.subplots()
        try:
            bars = axis.bar(frame["x"], frame["y"])
            figure.canvas.draw()
            probes.append({"value": value, "ok": True, "height": int(bars.patches[0].get_height())})
        except Exception as error:
            probes.append(
                {"value": value, "ok": False, "error": f"{type(error).__name__}: {error}"}
            )
        finally:
            plt.close(figure)
    results["integer_controls"] = probes
    return results


def measure(data: Path, *, host: bool, renderer: bool) -> dict[str, object]:
    manifest = json.loads((data / "manifest.json").read_text())
    for name, expected in manifest["sha256"].items():
        assert hashlib.sha256((data / name).read_bytes()).hexdigest() == expected
    versions = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
    }
    report = {
        "versions": versions,
        "seed": manifest["seed"],
        "manifest_sha256": hashlib.sha256((data / "manifest.json").read_bytes()).hexdigest(),
        "corpora": {name: measure_corpus(data, name, host=host) for name in ("decimals", "mixed")},
    }
    if renderer:
        report["renderer"] = render_heights(data)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare the T8 CSV corpus with host pandas and Python floats."
    )
    parser.add_argument("--renderer", action="store_true")
    arguments = parser.parse_args()
    report = measure(ROOT / "t8-data", host=True, renderer=arguments.renderer)
    (ROOT / "t8-host.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                name: {
                    form: {
                        "rows": result["vs_stdlib_float"]["rows"],
                        "stdlib_mismatches": result["vs_stdlib_float"]["bit_mismatches"],
                        "retained_digit_profile": result["vs_stdlib_float"][
                            "retained_digit_profile"
                        ],
                    }
                    for form, result in forms.items()
                }
                for name, forms in report["corpora"].items()
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
