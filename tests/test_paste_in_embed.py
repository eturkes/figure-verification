# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""The check-list document as an Open WebUI embed (M16 C5 + M18 E5, kept by M19.5).

Open WebUI sizes an embed only from the frame's own `iframe:height` message, and a same-origin
frame injects Alpine.js or Chart.js on trigger strings; the document carries one fixed reporter
script, no resource reference and no trigger, for every reason, language and anchoring.
"""

import re

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
        evidence=checks.Evidence(_PROGRAM, 3),
    )
    scripts = re.findall(r"<script>(.*?)</script>", source, flags=re.DOTALL)
    assert scripts == [_HEIGHT_REPORTER]
    assert source.count("<script") == 1
    outside_link = re.sub(r'<a class="spec" href="[^"]*"', "", source)
    assert not re.search(r"\bsrc\s*=|url\s*\(|@import|https?:", outside_link, flags=re.IGNORECASE)
    assert not any(trigger in source for trigger in _TRIGGERS)
    assert len(source.encode("utf-8")) < 262_144


def test_the_show_hide_switch_binds_the_outer_disclosure_alone() -> None:
    style = re.search(
        r"<style>(.*?)</style>", checks.breakdown_html(None, japanese=False, anchoring="strict")
    )
    assert style is not None
    for selectors, _body in re.findall(r"([^{}]+)\{([^{}]+)\}", style.group(1)):
        for selector in selectors.split(","):
            if ".show" in selector or ".hide" in selector:
                assert re.match(r"#r>details(?:\[open\]|:not\(\[open\]\))?>summary", selector)
