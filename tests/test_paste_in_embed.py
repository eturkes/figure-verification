# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The check-list document as an Open WebUI embed (M16 C5 + M18 E5, kept by M19.5).

Open WebUI sizes an embed only from the frame's own `iframe:height` message, and a same-origin
frame injects Alpine.js or Chart.js on trigger strings; the document carries one fixed reporter
script, no resource reference and no trigger, for every reason, language and anchoring.
"""

import re
from typing import TypeAlias

import pytest

from webui.paste_in import checks
from webui.paste_in.reasons import REASONS

# Hand-stated: the one script the document may carry (reviewer-2 K7, M16).
_HEIGHT_REPORTER = (
    'const r=document.getElementById("r");'
    "new ResizeObserver(()=>parent.postMessage("
    '{type:"iframe:height",height:Math.ceil(r.getBoundingClientRect().height)},"*")'
    ").observe(r);"
)
_TRIGGERS = ("x-data", "x-init", "x-show", "x-bind", "x-on", "new Chart(", "Chart.")
_PROGRAM = (
    "import matplotlib.pyplot as plt  # https://x-data.example/@import url(a) src=b\n"
    "plt.bar(['<b>', 'Chart.x'], [1, 2])\nplt.ylim(1, 3)\n"
)


@pytest.mark.parametrize("anchoring", ["strict", "substitution"])
@pytest.mark.parametrize("japanese", [False, True], ids=["en", "ja"])
@pytest.mark.parametrize("reason", [None, *sorted(REASONS)])
def test_every_document_carries_the_reporter_alone_and_no_trigger(
    reason: str | None, *, japanese: bool, anchoring: str
) -> None:
    source = checks.breakdown_html(
        reason,  # type: ignore[arg-type]
        japanese=japanese,
        anchoring=anchoring,  # type: ignore[arg-type]
        evidence=checks.Evidence(
            _PROGRAM, 3, tuple((check, frozenset({1, 2, 3})) for check in checks.CHECKS)
        ),
    )
    # HTML tag names are case-insensitive and an end tag may carry text before its `>`, so an
    # exact `<script>` match would let `<SCRIPT>` past the one-reporter pin (CodeQL
    # py/bad-tag-filter).
    scripts = re.findall(
        r"<script\b[^>]*>(.*?)</script\b[^>]*>", source, flags=re.DOTALL | re.IGNORECASE
    )
    assert scripts == [_HEIGHT_REPORTER]
    assert len(re.findall("<script", source, flags=re.IGNORECASE)) == 1
    outside_link = re.sub(r'<a class="spec" href="[^"]*"', "", source)
    assert not re.search(r"\bsrc\s*=|url\s*\(|@import|https?:", outside_link, flags=re.IGNORECASE)
    assert not any(trigger in source for trigger in _TRIGGERS)
    assert len(source.encode("utf-8")) < 262_144


_Rules: TypeAlias = list[tuple[str, dict[str, str]]]


def _style() -> tuple[_Rules, dict[str, _Rules]]:
    """The document's stylesheet as (selector, declarations) rules: top level, then per `@media`."""
    style = re.search(
        r"<style>(.*?)</style>", checks.breakdown_html(None, japanese=False, anchoring="strict")
    )
    assert style is not None
    css = style.group(1)

    def rules(text: str) -> _Rules:
        found: _Rules = []
        for head, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
            declarations = {
                name.strip(): value.strip()
                for name, _, value in (item.partition(":") for item in body.split(";") if item)
            }
            found.extend((selector.strip(), declarations) for selector in head.split(","))
        return found

    media: dict[str, _Rules] = {}
    top = ""
    rest = css
    while (at := rest.find("@media")) != -1:
        top += rest[:at]
        opened = rest.index("{", at)
        depth, end = 1, opened + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(rest[end], 0)
            end += 1
        media[rest[at:opened].strip()] = rules(rest[opened + 1 : end - 1])
        rest = rest[end:]
    return rules(top + rest), media


def _palette(rules: _Rules) -> dict[str, str]:
    (root,) = [declarations for selector, declarations in rules if selector == ":root"]
    return {name.removeprefix("--"): value for name, value in root.items()}


def _contrast(first: str, second: str) -> float:
    """WCAG 2 contrast ratio of two `#rrggbb` colours."""

    def luminance(colour: str) -> float:
        channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# Hand-stated (Q62): Open WebUI 0.12.3's message surfaces behind the frame, light `bg-white` + dark
# `bg-gray-900`, as measurement M16 `surfaces` reads them live.
_SURFACES = {"light": "#ffffff", "dark": "#161616"}
# Hand-stated: every text or mark colour on each background it sits on in the document, with its
# floor (WCAG AA: text 4.5:1, marks + the focus ring 3:1). `text` = body text, listings, the marked
# line + its highlight; `muted` = not-checked rows + line numbers, on the listing and the marked
# line too; `fail` = the failing row's cause (text) + its mark; `ok` = the passed mark; `link` = the
# reference link (text) + the focus ring.
_PAIRS = (
    ("text", "surface", 4.5),
    ("text", "code", 4.5),
    ("text", "at", 4.5),
    ("text", "hit", 4.5),
    ("muted", "surface", 4.5),
    ("muted", "code", 4.5),
    ("muted", "at", 4.5),
    ("fail", "surface", 4.5),
    ("link", "surface", 4.5),
    ("ok", "surface", 3.0),
)
# Hand-stated: every paint declaration outside `:root`. A colour, background or outline added here
# must join `_PAIRS`; `opacity` never appears, since it would blend a colour past the pairs above.
_PAINT = {
    ("body", "color", "var(--text)"),
    ("body", "background", "var(--surface)"),
    ("summary:focus-visible", "outline", "2px solid var(--link)"),
    ("a:focus-visible", "outline", "2px solid var(--link)"),
    (".pass .mark", "color", "var(--ok)"),
    (".fail .mark", "color", "var(--fail)"),
    (".cause", "color", "var(--fail)"),
    (".skip", "color", "var(--muted)"),
    (".listing", "background", "var(--code)"),
    (".ln", "color", "var(--muted)"),
    (".at", "background", "var(--at)"),
    ("mark", "background", "var(--hit)"),
    ("mark", "color", "inherit"),
    ("a.spec", "color", "var(--link)"),
}
# Every property that paints a colour or blends one.
_PAINTING = re.compile(
    r"color|background(?:-color)?|outline(?:-color)?|border(?:-(?:top|right|bottom|left))?"
    r"(?:-color)?|(?:box|text)-shadow|opacity|filter|mix-blend-mode|fill|stroke"
)


def test_wcag_contrast_reproduces_known_ratios() -> None:
    assert _contrast("#000000", "#ffffff") == 21
    assert round(_contrast("#767676", "#ffffff"), 2) == 4.54
    assert round(_contrast("#777777", "#ffffff"), 2) == 4.48


def test_each_scheme_paints_open_webuis_surface() -> None:
    top, media = _style()
    assert list(media) == ["@media (prefers-color-scheme:dark)"]
    light, dark = _palette(top), _palette(media["@media (prefers-color-scheme:dark)"])
    assert light.keys() == dark.keys()
    assert {"light": light["surface"], "dark": dark["surface"]} == _SURFACES


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_every_colour_meets_its_contrast_floor_on_its_surface(scheme: str) -> None:
    """Q62: each text colour >= 4.5:1, each mark + the focus ring >= 3:1, against the background it
    sits on under that scheme."""
    top, media = _style()
    palette = _palette(top if scheme == "light" else next(iter(media.values())))
    short = [
        f"{fore} on {back} = {_contrast(palette[fore], palette[back]):.2f}"
        for fore, back, floor in _PAIRS
        if _contrast(palette[fore], palette[back]) < floor
    ]
    assert not short


def test_paint_declarations_are_the_closed_set() -> None:
    top, _ = _style()
    paint = {
        (selector, name, value)
        for selector, declarations in top
        if selector != ":root"
        for name, value in declarations.items()
        if _PAINTING.fullmatch(name)
    }
    assert paint == _PAINT
    used = {name for *_, value in _PAINT for name in re.findall(r"var\(--([a-z]+)\)", value)}
    assert used == {name for pair in _PAIRS for name in pair[:2]}


def test_selectors_stay_flat() -> None:
    """Q62: class and element selectors only (no id), and no `!important`."""
    top, media = _style()
    every = [*top, *(rule for rules in media.values() for rule in rules)]
    assert not [selector for selector, _ in every if "#" in selector]
    assert not [
        value for _, declarations in every for value in declarations.values() if "!" in value
    ]


def test_the_show_hide_switch_binds_the_outer_disclosure_alone() -> None:
    top, _ = _style()
    switches = [selector for selector, _ in top if ".show" in selector or ".hide" in selector]
    assert len(switches) == 2
    for selector in switches:
        assert re.match(r"\.checks>details(?:\[open\]|:not\(\[open\]\))?>summary ", selector)
