# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The launcher's banner arms: each prompt, the CSV to attach, and the stub's scripted program.

Six arms over `data/sales.csv` and `data/clinic_ja.csv`, English and Japanese, each request asked
honestly (the figure must pass) or for a named distortion (the figure must block with that rule's
reason). `webui/banner.json` holds every arm; the stub answers each rendered prompt with its
scripted program, so every stub-arm verdict is repeatable without a model. A real model's replies
are measured live (`.agent/measurements/`), never replayed here.
"""

from pathlib import Path
from typing import Literal

import msgspec

from verifier.pysrc.budget import WorkBudget
from verifier.pysrc.csvread import _read_csv
from verifier.pysrc.limits import DEFAULT_LIMITS
from webui.paste_in.demo_filter import Filter as DemoFilter

BANNER = Path(__file__).with_name("banner.json")
DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


class Arm(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One banner prompt: its id, the CSV it needs, the request, the stub's program, the verdict
    the stub arm must reach (`pass` or the blocking reason)."""

    id: str
    dataset: str
    prompt: str
    program: str
    expect: str


class BannerSet(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    version: Literal[1]
    arms: tuple[Arm, ...]


def load(path: Path = BANNER) -> BannerSet:
    return msgspec.json.decode(path.read_bytes(), type=BannerSet)


def rendered(arm: Arm, data_root: Path = DATA_ROOT) -> str:
    """The user message the demo inlet builds for the arm's request over its attached CSV."""
    header, _rows = _read_csv(
        (data_root / arm.dataset).read_bytes(),
        DEFAULT_LIMITS,
        WorkBudget(DEFAULT_LIMITS.max_work),
    )
    return DemoFilter._TEMPLATES.file.format(
        task=arm.prompt, dataset=arm.dataset, columns=", ".join(header)
    )
