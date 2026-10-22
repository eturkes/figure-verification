# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Q82.1 T1 + T2 (`.agent/contracts/q82.md`): the generated nucllei tool + skill files.

The llens deployment reads both with `scripts/nucllei/sync.py`: the tool's first docstring
`key: value` lines name its row, the skill's one-line frontmatter carries its description,
`tool_ids` and `auto_load_content_types`. The replicas below restate that parser (llens
`e6a1b6f`), so a header the deployment would misread fails here.
"""

from __future__ import annotations

import ast
import asyncio
import re
import sys
from pathlib import Path

import pytest

from nucllei_support import CHAT_ID, USER_ID, World, history, install, ref
from paste_in_support import REPO_ROOT, load_bundle

TOOL = REPO_ROOT / "llens/nucllei/tools/figure_verification.py"
SKILL = REPO_ROOT / "llens/nucllei/skills/figure-verification.md"
SALES = b"month,revenue\nJan,100\nFeb,120\nMar,90\n"


def _llens_frontmatter(content: str) -> dict[str, str]:
    """llens `sync.py::parse_frontmatter` (single-line values)."""
    found = re.search(r'^"""(.*?)"""', content, re.DOTALL | re.MULTILINE)
    assert found is not None
    fields: dict[str, str] = {}
    for line in found.group(1).splitlines():
        pair = re.match(r"^([a-zA-Z_]+):\s*(.*)$", line.strip())
        if pair:
            fields[pair.group(1)] = pair.group(2).strip()
    return fields


def _llens_md_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """llens `sync.py::parse_md_frontmatter`."""
    found = re.search(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.DOTALL)
    assert found is not None
    fields: dict[str, str] = {}
    for line in found.group(1).splitlines():
        pair = re.match(r"^([a-zA-Z_]+):\s*(.+)$", line.strip())
        if pair:
            value = pair.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            fields[pair.group(1)] = value
    return fields, content[found.end() :]


def test_q82_t1_both_files_are_their_sources_rendered() -> None:
    bundle = load_bundle()
    assert TOOL.read_text(encoding="utf-8") == bundle.render("nucllei_skill.tool")
    assert SKILL.read_text(encoding="utf-8") == bundle.render_text("nucllei_skill.skill")


def test_q82_t1_the_tool_row_llens_creates_has_this_name_and_description() -> None:
    assert _llens_frontmatter(TOOL.read_text(encoding="utf-8")) == {
        "title": "Figure Verification",
        "description": "グラフを描くプログラムを実行し、検証に合格した図だけを表示します。",
    }


def _imported_roots(text: str) -> set[str]:
    bundle = load_bundle()
    roots: set[str] = set()
    for source in (text, *bundle.embedded_sources(text).values()):
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                roots |= {alias.name.partition(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                roots.add(node.module.partition(".")[0])
    return roots


def test_q82_t1_each_artifact_reaches_only_its_own_host() -> None:
    bundle = load_bundle()
    first_party = {"verifier", "webui", "nucllei_skill"}
    nucllei = _imported_roots(TOOL.read_text(encoding="utf-8")) - set(sys.stdlib_module_names)
    assert nucllei - first_party == {"nucllei", "pydantic"}
    for relative in (
        "paste-in/figure_verification_tool.py",
        "paste-in/figure_verification_filter.py",
    ):
        owui = _imported_roots((REPO_ROOT / relative).read_text(encoding="utf-8"))
        assert "nucllei" not in owui
        assert "nucllei_skill" not in owui
    planted = "import open_webui\n"
    assert bundle.offending_import_roots(planted, "nucllei_skill.tool") == ["open_webui"]
    assert bundle.offending_import_roots("import nucllei\n", "webui.paste_in.tool") == ["nucllei"]


def test_q82_t2_the_skill_row_llens_creates() -> None:
    fields, body = _llens_md_frontmatter(SKILL.read_text(encoding="utf-8"))
    assert set(fields) == {"title", "description", "tool_ids", "auto_load_content_types"}
    assert fields["title"] == "Figure Verification"
    assert fields["tool_ids"] == "figure_verification"
    assert [t.strip() for t in fields["auto_load_content_types"].split(",")] == [
        "text/csv",
        "application/vnd.ms-excel",
    ]
    assert fields["description"].startswith("データをグラフ・図にするときにロードする")
    assert "draw_figure" in fields["description"]
    assert body.strip().startswith("# 検証付きのグラフ (draw_figure)\n")


@pytest.mark.parametrize(
    "rule",
    [
        "/workspace/imports/<ファイル名>",
        "pandas の read_csv で読む",
        "棒と塗りつぶした面はゼロから始める",
        "軸は線形にし、反転しない",
        "すべての点、棒、基準線を軸の範囲の中に収める",
        "1 つのパネルに軸は 1 つにする",
        "凡例ですべての系列に名前を付ける",
        'legend_elements("sizes")',
        "errorbar=None",
        "ヒストグラムは plt.hist で描く",
        "note は日本語の依頼なら日本語で、それ以外の依頼なら英語で書く。",
        "グラフを run_python で描いたり、fetch_from_workspace で見せたりしない。",
        "画像を本文に貼り直したり、合否を言い直したりしない。",
        "本文はユーザーの依頼と同じ言語で書く。日本語の依頼なら日本語で、それ以外の依頼なら英語で書く。",
        "理由に沿ってプログラムを直して呼び直してよい (2 回まで)。",
        "添付ファイルか依頼文の数値があるときは描いた値がそのデータであることだけ。",
        "データが無い図は規則だけを確かめる。",
    ],
)
def test_q82_t2_the_skill_states_each_rule(rule: str) -> None:
    _fields, body = _llens_md_frontmatter(SKILL.read_text(encoding="utf-8"))
    assert rule in body.replace("\n", "")


def test_q82_t1_the_generated_file_runs_as_nucllei_loads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The artifact itself, executed the way `utils/plugin.py::load_tool_module_by_id` does,
    exposes a docstring-free `Tools` and publishes a pass from its embedded reader + judge."""
    world = World(root=tmp_path)
    install(monkeypatch, world)
    world.program = (
        "import matplotlib.pyplot as plt\nplt.bar(['Jan', 'Feb', 'Mar'], [100, 120, 90])\n"
        "plt.show()\n"
    )
    world.attach("f1", "sales.csv", SALES)
    world.chats[(CHAT_ID, USER_ID)] = history(
        {"role": "user", "content": "Plot revenue by month", "files": [ref("f1", "sales.csv")]}
    )
    namespace: dict[str, object] = {"__name__": "tool_figure_verification"}
    before = sys.modules.get("nucllei_skill.tool")
    exec(compile(TOOL.read_text(encoding="utf-8"), "tool", "exec"), namespace)  # noqa: S102
    assert sys.modules.get("nucllei_skill.tool") is before  # the loader restores its slots
    tools_class = namespace["Tools"]
    assert isinstance(tools_class, type)
    assert tools_class.__doc__ is None
    tools = tools_class()
    asyncio.run(
        tools.draw_figure(
            world.program,
            "",
            __user__={"id": USER_ID},
            __chat_id__=CHAT_ID,
            __message_id__="assistant-pending",
            __display__=world.display,
        )
    )
    assert world.displays[0][0].startswith("Figure verification passed")
