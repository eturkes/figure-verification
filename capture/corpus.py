# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Python-mode prompt corpus: schema, loader, byte-pinned capture prompt, structural validator.

corpus/python/ is pure DATA and holds no .py file: a `corpus` package would shadow tests/corpus.py
under pytest's `pythonpath = ["tests", "."]` and raise a duplicate-module error under mypy. So this
module is the only code that knows the corpus shape.

    corpus/python/design/manifest.json    24 simple + 24 complicated; read freely
    corpus/python/heldout/manifest.json   20 + 20; generated against only once the M13 config is
                                          frozen, and never read by a subset-design session
    corpus/python/sentinels.json          the 2 public demo prompts, outside both denominators
    corpus/python/capture_prompt_v1.txt   byte-pinned; its sha256 rides every capture record
    corpus/python/captures/<run>/         M12.6+ records, TRACKED (unlike bench/reports/)

Predicates C1-C10 of .agent/archive/contracts/m12u5.md are implemented HERE and nowhere else;
tests/test_python_corpus.py calls them and restates none of them.
"""

import hashlib
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Final, Literal, get_args

import msgspec

Category = Literal["simple", "complicated"]
Kind = Literal["design", "heldout", "sentinels"]
DatasetName = Literal["sales.csv", "weather.csv"]

CATEGORIES: Final[tuple[Category, ...]] = get_args(Category)
KINDS: Final[tuple[Kind, ...]] = get_args(Kind)
DATASET_NAMES: Final[tuple[DatasetName, ...]] = get_args(DatasetName)

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
CORPUS_ROOT: Final = REPO_ROOT / "corpus" / "python"
DATA_ROOT: Final = REPO_ROOT / "data"

CAPTURE_PROMPT_NAME: Final = "capture_prompt_v1.txt"
# Hand-stated: the pin is worthless if it re-derives from the file it guards. Every M12.6 capture
# record carries this value, so an edit to the template invalidates every capture taken before it.
CAPTURE_PROMPT_SHA256: Final = "a18162f788cce976a55458545c5761e2fd5b8b924e116ac137ffc4deb004964e"
CAPTURE_PROMPT_FORMAT_SENTENCE: Final = (
    "Return one complete Python program as bare source text, no Markdown fences."
)

_MANIFESTS: Final[dict[Kind, str]] = {
    "design": "design/manifest.json",
    "heldout": "heldout/manifest.json",
    "sentinels": "sentinels.json",
}

_EXPECTED_COUNTS: Final[dict[tuple[Kind, Category], int]] = {
    ("design", "simple"): 24,
    ("design", "complicated"): 24,
    ("heldout", "simple"): 20,
    ("heldout", "complicated"): 20,
    ("sentinels", "simple"): 1,
    ("sentinels", "complicated"): 1,
}

# Closed vocabulary, MAIN-declared: these labels become M13's subset design vocabulary, so the
# corpus is authored by idiom CLASS rather than against sampled model output.
IDIOMS: Final[dict[Category, tuple[str, ...]]] = {
    "simple": (
        "bar_category_sum",
        "bar_category_mean",
        "bar_category_extremum",
        "bar_time_sum",
        "line_time_series",
        "line_time_multi_series",
        "scatter_xy",
        "scatter_xy_grouped",
    ),
    "complicated": (
        "subplot_grid",
        "twin_axis",
        "statistical_fit",
        "derived_metric",
        "distribution_plot",
        "styled_annotation",
        "composite_marks",
        "external_or_interactive",
    ),
}

# Simple asks stay terse, complicated asks stay elaborate: the public sentinels measure 46 B and
# 260 B, and a one-clause "complicated" prompt is answerable by an ordinary plot, which collapses
# the fail arm the way res-port measured.
_LENGTH_BANDS: Final[dict[Category, tuple[int, int]]] = {
    "simple": (25, 109),
    "complicated": (110, 400),
}

# Ruling 6: prompts carry TASK + FORMAT + dataset binding only. Admission vocabulary relocates the
# pass/fail decision out of the verifier and into the model. Word-start stems, any suffix.
_BANNED_STEMS: Final[tuple[str, ...]] = (
    "admiss",
    "admit",
    "allow",
    "blacklist",
    "block",
    "blocklist",
    "disallow",
    "forbid",
    "permit",
    "policy",
    "refus",
    "reject",
    "restrict",
    "sandbox",
    "support",
    "unsupport",
    "validat",
    "verif",
    "whitelist",
)
_BANNED_RE: Final = re.compile(r"\b(?:" + "|".join(_BANNED_STEMS) + r")\w*", re.IGNORECASE)

_SET_ID_RE: Final = re.compile(r"^(design|heldout)-(simple|complicated)-(\d{2})$")
_PLACEHOLDER_RE: Final = re.compile(r"\{(\w+)\}")
_DISJOINT_PAIRS: Final[tuple[tuple[Kind, Kind], ...]] = (
    ("design", "heldout"),
    ("design", "sentinels"),
    ("heldout", "sentinels"),
)

# Hand-stated headers; check_dataset_binding asserts them against the real CSVs, so the literal is
# the claim and the file is the oracle.
DATASET_COLUMNS: Final[dict[DatasetName, tuple[str, ...]]] = {
    "sales.csv": ("month", "region", "revenue", "orders"),
    "weather.csv": ("date", "city", "temp_c", "precip_mm", "aqi"),
}


class Prompt(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One corpus prompt: its id, category, expected plotting idiom and bound dataset."""

    id: str
    category: Category
    idiom: str
    dataset_name: DatasetName
    prompt: str


class PromptSet(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """One corpus file: a version, the set it belongs to, and its ordered prompts."""

    version: Literal["python-corpus-1"]
    kind: Kind
    prompts: tuple[Prompt, ...]


class Corpus(msgspec.Struct, frozen=True, kw_only=True):
    """The three loaded prompt sets and the root they came from."""

    root: Path
    design: PromptSet
    heldout: PromptSet
    sentinels: PromptSet

    def sets(self) -> Iterator[tuple[Kind, PromptSet]]:
        """Yield each (kind, set) pair in declaration order."""
        yield "design", self.design
        yield "heldout", self.heldout
        yield "sentinels", self.sentinels

    def rows(self) -> Iterator[tuple[Kind, Prompt]]:
        """Yield every prompt in the corpus, tagged with the set it came from."""
        for kind, prompt_set in self.sets():
            for prompt in prompt_set.prompts:
                yield kind, prompt


_DECODER: Final = msgspec.json.Decoder(PromptSet)


def load_corpus(root: Path = CORPUS_ROOT) -> Corpus:
    """Strictly decode the three corpus files; raise on any malformed or unknown field."""
    loaded = {kind: _DECODER.decode((root / rel).read_bytes()) for kind, rel in _MANIFESTS.items()}
    return Corpus(
        root=root,
        design=loaded["design"],
        heldout=loaded["heldout"],
        sentinels=loaded["sentinels"],
    )


def render_capture_prompt(prompt: Prompt, root: Path = CORPUS_ROOT) -> str:
    """Render the byte-pinned capture prompt for one corpus row.

    The template is read from disk on every call, so CAPTURE_PROMPT_SHA256 describes the exact
    bytes that reach the wire. Task text is substituted INTO the template, so braces in a prompt
    are inert.
    """
    template = (root / CAPTURE_PROMPT_NAME).read_text(encoding="utf-8")
    return template.format(
        task=prompt.prompt,
        dataset=prompt.dataset_name,
        columns=", ".join(DATASET_COLUMNS[prompt.dataset_name]),
    )


def _normalize(text: str) -> str:
    """Collapse a prompt to its comparison key: case-folded, whitespace-normalized."""
    return " ".join(text.casefold().split())


def check_kinds(corpus: Corpus) -> list[str]:
    """C1 -- each file's declared kind matches the location it was loaded from."""
    return [
        f"{_MANIFESTS[kind]}: kind is {prompt_set.kind!r}, expected {kind!r}"
        for kind, prompt_set in corpus.sets()
        if prompt_set.kind != kind
    ]


def check_counts(corpus: Corpus) -> list[str]:
    """C2 -- every (set, category) group holds exactly its contracted row count."""
    actual = Counter((kind, prompt.category) for kind, prompt in corpus.rows())
    return [
        f"{key[0]}/{key[1]}: {actual[key]} prompts, expected {expected}"
        for key, expected in _EXPECTED_COUNTS.items()
        if actual[key] != expected
    ]


def check_category_balance(corpus: Corpus) -> list[str]:
    """C3 -- within every set the two categories carry equal weight."""
    failures: list[str] = []
    for kind, prompt_set in corpus.sets():
        sizes = {c: sum(p.category == c for p in prompt_set.prompts) for c in CATEGORIES}
        if len(set(sizes.values())) != 1:
            failures.append(f"{kind}: unbalanced categories {sizes}")
    return failures


def check_ids(corpus: Corpus) -> list[str]:
    """C4 -- ids are globally unique, well-shaped, self-consistent and gapless per group."""
    failures: list[str] = []
    seen: Counter[str] = Counter()
    ordinals: dict[tuple[Kind, Category], list[int]] = {}
    for kind, prompt in corpus.rows():
        seen[prompt.id] += 1
        if kind == "sentinels":
            if prompt.id != f"sentinel-{prompt.category}":
                failures.append(f"{prompt.id}: sentinel id must be sentinel-{prompt.category}")
            continue
        match = _SET_ID_RE.fullmatch(prompt.id)
        if match is None or (match[1], match[2]) != (kind, prompt.category):
            failures.append(f"{prompt.id}: id must read {kind}-{prompt.category}-NN")
            continue
        ordinals.setdefault((kind, prompt.category), []).append(int(match[3]))
    failures.extend(f"{pid}: id used {n} times" for pid, n in seen.items() if n > 1)
    for group, seen_ordinals in ordinals.items():
        expected = list(range(1, len(seen_ordinals) + 1))
        if sorted(seen_ordinals) != expected:
            failures.append(f"{group[0]}/{group[1]}: ordinals {sorted(seen_ordinals)} not gapless")
    return failures


def check_disjoint(corpus: Corpus) -> list[str]:
    """C5 -- no prompt repeats inside a set, and the three sets share no prompt."""
    failures: list[str] = []
    keys: dict[Kind, set[str]] = {}
    for kind, prompt_set in corpus.sets():
        counts = Counter(_normalize(p.prompt) for p in prompt_set.prompts)
        failures.extend(f"{kind}: duplicate prompt {k!r}" for k, n in counts.items() if n > 1)
        keys[kind] = set(counts)
    for left, right in _DISJOINT_PAIRS:
        shared = keys[left] & keys[right]
        failures.extend(f"{left} and {right} share prompt {k!r}" for k in sorted(shared))
    return failures


def banned_terms(text: str) -> list[str]:
    """Return every admission-vocabulary term in `text`, in order of appearance."""
    return _BANNED_RE.findall(text)


def check_no_admission_vocabulary(corpus: Corpus) -> list[str]:
    """C6 -- ruling 6: no prompt and no capture template names the admission boundary."""
    failures = [
        f"{prompt.id}: banned term {term!r}"
        for _, prompt in corpus.rows()
        for term in banned_terms(prompt.prompt)
    ]
    template = (corpus.root / CAPTURE_PROMPT_NAME).read_text(encoding="utf-8")
    failures.extend(
        f"{CAPTURE_PROMPT_NAME}: banned term {term!r}" for term in banned_terms(template)
    )
    return failures


def check_capture_prompt(corpus: Corpus) -> list[str]:
    """C7 -- the capture template is byte-pinned, placeholder-exact and few-shot-free."""
    raw = (corpus.root / CAPTURE_PROMPT_NAME).read_bytes()
    text = raw.decode("utf-8")
    failures: list[str] = []
    digest = hashlib.sha256(raw).hexdigest()
    if digest != CAPTURE_PROMPT_SHA256:
        failures.append(f"{CAPTURE_PROMPT_NAME}: sha256 {digest}, pinned {CAPTURE_PROMPT_SHA256}")
    placeholders = set(_PLACEHOLDER_RE.findall(text))
    if placeholders != {"task", "dataset", "columns"}:
        failures.append(f"{CAPTURE_PROMPT_NAME}: placeholders {sorted(placeholders)}")
    if not text.rstrip("\n").endswith(CAPTURE_PROMPT_FORMAT_SENTENCE):
        failures.append(f"{CAPTURE_PROMPT_NAME}: does not end with the pinned format sentence")
    # A few-shot would arrive as example source: a fence, an import, a pyplot call or an assignment.
    failures.extend(
        f"{CAPTURE_PROMPT_NAME}: few-shot marker {marker!r}"
        for marker in ("```", "import ", "plt.", "=")
        if marker in text
    )
    return failures


def check_dataset_binding(corpus: Corpus) -> list[str]:
    """C8 -- declared columns match the real CSVs and both datasets carry every group."""
    failures: list[str] = []
    for name, columns in DATASET_COLUMNS.items():
        # name is a two-member Literal, so the join is confined by construction.
        header = (DATA_ROOT / name).read_text(encoding="utf-8").splitlines()[0]
        if tuple(header.split(",")) != columns:
            failures.append(f"{name}: header {header!r} != declared {columns}")
    for kind, prompt_set in corpus.sets():
        if kind == "sentinels":  # both public sentinels are sales.csv by definition
            continue
        for category in CATEGORIES:
            rows = [p for p in prompt_set.prompts if p.category == category]
            used = Counter(p.dataset_name for p in rows)
            failures.extend(
                f"{kind}/{category}: {name} used {used[name]}/{len(rows)}, want >=25%"
                for name in DATASET_NAMES
                if used[name] * 4 < len(rows)
            )
    return failures


def check_prompt_shape(corpus: Corpus) -> list[str]:
    """C9 -- no placeholder residue; every prompt is one stripped line inside its length band."""
    failures: list[str] = []
    for _, prompt in corpus.rows():
        for field, value in (("idiom", prompt.idiom), ("prompt", prompt.prompt)):
            if "unknown" in value.casefold():
                failures.append(f"{prompt.id}: {field} still carries a placeholder {value!r}")
        if prompt.prompt != prompt.prompt.strip() or "\n" in prompt.prompt:
            failures.append(f"{prompt.id}: prompt must be one stripped line")
        low, high = _LENGTH_BANDS[prompt.category]
        if not low <= len(prompt.prompt) <= high:
            failures.append(f"{prompt.id}: length {len(prompt.prompt)} outside {low}..{high}")
    return failures


def check_idioms(corpus: Corpus) -> list[str]:
    """C10 -- every idiom is in the closed vocabulary, and design + heldout each cover all of it."""
    failures = [
        f"{prompt.id}: idiom {prompt.idiom!r} not in the {prompt.category} vocabulary"
        for _, prompt in corpus.rows()
        if prompt.idiom not in IDIOMS[prompt.category]
    ]
    for kind, prompt_set in corpus.sets():
        if kind == "sentinels":  # two rows cannot cover sixteen idioms
            continue
        used = {p.idiom for p in prompt_set.prompts}
        failures.extend(
            f"{kind}: idiom {idiom!r} never used"
            for category in CATEGORIES
            for idiom in IDIOMS[category]
            if idiom not in used
        )
    return failures


PREDICATES: dict[str, Callable[[Corpus], list[str]]] = {
    "C1": check_kinds,
    "C2": check_counts,
    "C3": check_category_balance,
    "C4": check_ids,
    "C5": check_disjoint,
    "C6": check_no_admission_vocabulary,
    "C7": check_capture_prompt,
    "C8": check_dataset_binding,
    "C9": check_prompt_shape,
    "C10": check_idioms,
}


def validate(root: Path = CORPUS_ROOT) -> list[str]:
    """Run every predicate; return id-prefixed failure lines, empty when the corpus is sound."""
    corpus = load_corpus(root)
    return [f"{pid}: {line}" for pid, check in PREDICATES.items() for line in check(corpus)]


def main() -> int:
    """Grade the committed corpus; failures to stderr, rc 1 when any predicate fails."""
    failures = validate()
    for line in failures:
        sys.stderr.write(f"{line}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
