# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
# ruff: noqa: T201, E501  (demo-only: prints + long bilingual data strings / HTML template lines)
"""Throwaway PoC demo builder (branch poc/bilingual-demo) — NOT part of the verifier.

Runs the FULL M1 golden corpus (examples/index.json) through the trusted verifier and
writes one self-contained offline page, demo/index.html:

- 10 good specs -> render.render() -> inline SVG chart (base64 <img>, isolating each
  SVG's id namespace) + its VCert provenance certificate;
- 18 bad specs -> the real seam (decode_spec -> manifest -> checks.verify) -> blocked
  card with the verifier's actual output; the page renders NO chart for them.

Demo UI chrome is bilingual EN+JA, stacked or side-by-side (deliberately no toggle).
Verifier output (check ids, messages, JSON artifacts) is data, shown verbatim (EN).
Deterministic: no timestamps; rebuild -> identical bytes for an unchanged repo.
Fails loudly (SystemExit) if the corpus disagrees with index.json expectations.
"""

import base64
import json
import re
from html import escape
from pathlib import Path

import msgspec

from verifier import checks, render
from verifier.ingest import load_manifest
from verifier.schema import decode_spec

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
GOOD_DIR = ROOT / "examples" / "good_specs"
BAD_DIR = ROOT / "examples" / "bad_specs"
OUT = ROOT / "demo" / "index.html"

# --- bilingual text (EN from examples/index.json; JA hand-authored here) -----
INTENT_JA = {
    "g01_total_revenue_by_month.json": "月別の総売上を表示する。",
    "g02_revenue_by_region.json": "地域別の売上を比較する。",
    "g03_order_count_by_month.json": "月別の注文数を表示する。",
    "g04_revenue_vs_orders.json": "売上と注文数の関係をプロットする。",
    "g05_avg_revenue_by_region.json": "地域別の平均売上を表示する。",
    "g06_max_temp_by_city.json": "都市別の最高気温を表示する。",
    "g07_temp_over_time_by_city.json": "都市ごとの気温の推移をプロットする。",
    "g08_na_revenue_by_month.json": "NA地域の月別総売上を表示する。",
    "g09_min_revenue_by_month.json": "月別の最低売上を表示する。",
    "g10_temp_vs_precip.json": "気温と降水量の関係をプロットする。",
}
REASON_JA = {
    "b01_unknown_mark.json": "マーク 'pie' は {bar, line, scatter} に含まれません。",
    "b02_unknown_transform_op.json": "変換オペレーション 'pivot' は許可リストのタグ付きユニオンに含まれません。",
    "b03_unknown_agg_fn.json": "集計関数 'median' は {sum, mean, count, min, max} に含まれません。",
    "b04_float_filter_value.json": "フィルタ値 1.5 はJSON浮動小数点数です。厳密デコードはfloatトークンを拒否します。",
    "b05_unknown_channel_field.json": "チャネルに未知のキー 'title' があります。モデルはタイトルを提案できません。",
    "b06_wrong_version.json": "バージョン 'vplot-0.2' は固定リテラル 'vplot-0.1' ではありません。",
    "b17_injection_encoding_aggregate.json": (
        "Vega-Liteのエンコーディングレベルの 'aggregate' はデコード時に拒否されます(インジェクション経路)。"
    ),
    "b18_injection_top_level_url.json": (
        "Vega-Liteのトップレベル 'url' ローダーはデコード時に拒否されます(インジェクション経路)。"
    ),
    "b07_nonexistent_field.json": "フィルタフィールド 'profit' は sales.csv に存在しません。",
    "b08_dataset_hash_mismatch.json": "宣言された dataset.hash がソース sales.csv のバイト列と一致しません。",
    "b09_sum_on_string_field.json": "sum には数値列が必要ですが、region は文字列です。",
    "b10_filter_int_vs_string.json": "整数リテラル 5 は文字列列 region に変換できません。",
    "b11_axis_type_mismatch.json": "y は quantitative 型ですが、region は文字列列です。",
    "b12_encoding_field_absent.json": "orders は集計で除外され、プロット表 {month, total_revenue} に存在しません。",
    "b13_missing_y_unit.json": "aqi は quantitative ですが、weather マニフェストに単位の宣言がありません。",
    "b14_group_by_without_aggregate.json": "group_by は aggregate の直前でのみ有効ですが、ここでは sort の前にあります。",
    "b15_aggregate_as_collides_group_key.json": "集計出力 'region' がグループキー 'region' と衝突します。",
    "b16_sort_fields_not_distinct.json": "sort.by がフィールド 'month' を重複指定しています。",
}
LAYER_JA = {
    "decode": "デコード",
    "dataset-binding": "データセット結合",
    "encoding": "エンコーディング",
    "transform": "変換",
}


# --- bilingual markup helpers -------------------------------------------------
def bi(en: str, ja: str) -> str:
    """Side-by-side EN + JA pair (inline)."""
    return f'<span class="bi"><span lang="en">{escape(en)}</span><span lang="ja">{escape(ja)}</span></span>'


def bi_stack(en: str, ja: str, cls: str = "bi-stack") -> str:
    """Stacked EN-over-JA pair (block)."""
    return f'<div class="{cls}"><p lang="en">{escape(en)}</p><p lang="ja">{escape(ja)}</p></div>'


def chip(label_en: str, label_ja: str, value: str) -> str:
    return f'<span class="chip">{bi(label_en, label_ja)}<code>{escape(value)}</code></span>'


BADGE_OK = (
    '<span class="badge ok"><span class="ic" aria-hidden="true">✓</span>'
    '<span lang="en">Verified</span><span lang="ja">検証済み</span></span>'
)
BADGE_NO = (
    '<span class="badge no"><span class="ic" aria-hidden="true">✕</span>'
    '<span lang="en">Blocked</span><span lang="ja">ブロック</span></span>'
)


def details(summary_en: str, summary_ja: str, body: str) -> str:
    return (
        f"<details><summary>{bi(summary_en, summary_ja)}</summary>"
        f"<pre><code>{escape(body)}</code></pre></details>"
    )


def pretty_json(raw: bytes) -> str:
    try:
        return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except json.JSONDecodeError:  # pragma: no cover - corpus files are valid JSON
        return raw.decode("utf-8", errors="replace")


# --- cards --------------------------------------------------------------------
def manifest_bytes_for(dataset_name: str) -> bytes:
    return (DATA_DIR / "schemas" / (Path(dataset_name).stem + ".json")).read_bytes()


def good_card(entry: dict[str, str]) -> str:
    file = entry["file"]
    raw = (GOOD_DIR / file).read_bytes()
    spec = decode_spec(raw)
    result = render.render(spec, manifest_bytes_for(spec.dataset.name), data_dir=DATA_DIR)
    if result is None:
        msg = f"corpus invariant broken: good spec blocked: {file}"
        raise SystemExit(msg)
    cert = result.certificate
    svg64 = base64.b64encode(result.svg.encode("utf-8")).decode("ascii")
    width_m = re.search(r'width="(\d+(?:\.\d+)?)"', result.svg)
    width = width_m.group(1) if width_m else "640"
    alt = escape(f"Verified chart / 検証済みチャート — {entry['intent']}")
    cert_json = json.dumps(msgspec.to_builtins(cert), indent=2, ensure_ascii=False)
    return f"""
<article class="card" id="{escape(Path(file).stem.split("_")[0])}">
  <header class="cardhead">{BADGE_OK}<code class="file">{escape(file)}</code></header>
  <h3 class="bi-stack intent"><span lang="en">{escape(entry["intent"])}</span><span lang="ja">{escape(INTENT_JA[file])}</span></h3>
  <div class="chips">
    {chip("mark", "マーク", entry["mark"])}
    {chip("dataset", "データセット", entry["dataset"])}
    {chip("checks passed", "合格した検査", str(len(cert.checks_passed)))}
  </div>
  <div class="well"><img width="{width}" src="data:image/svg+xml;base64,{svg64}" alt="{alt}"></div>
  {render.badge_html(cert)}
  {details("Certificate as canonical JSON", "証明書(正規JSON)", cert_json)}
  {details("Proposed spec (pretty-printed)", "提案された仕様(整形表示)", pretty_json(raw))}
</article>"""


def bad_card(entry: dict[str, str]) -> str:
    file = entry["file"]
    raw = (BAD_DIR / file).read_bytes()
    try:
        spec = decode_spec(raw)
    except (msgspec.DecodeError, msgspec.ValidationError) as exc:
        verdict = f"decode_spec -> {type(exc).__name__}:\n{exc}"
        stage_en = "Blocked at decode — the spec never reaches the evaluator."
        stage_ja = "デコード時にブロック — 仕様は評価器に到達しません。"
    else:
        report = checks.verify(
            spec, load_manifest(manifest_bytes_for(spec.dataset.name)), data_dir=DATA_DIR
        )
        if report.passed:
            msg = f"corpus invariant broken: bad spec verified: {file}"
            raise SystemExit(msg)
        fails = [r for r in report.results if r.status == "fail"]
        verdict = "\n".join(f"{r.check} [{r.severity}]\n  {r.message}" for r in fails)
        stage_en = "Blocked by checks — verified: false, no chart is rendered."
        stage_ja = "検査でブロック — verified: false、チャートは描画されません。"
    return f"""
<article class="card blocked" id="{escape(Path(file).stem.split("_")[0])}">
  <header class="cardhead">{BADGE_NO}<code class="file">{escape(file)}</code></header>
  <div class="chips">
    {chip("layer", "レイヤー", f"{entry['layer']} / {LAYER_JA[entry['layer']]}")}
    {chip("check", "検査", entry["check"])}
  </div>
  {bi_stack(entry["reason"], REASON_JA[file], "bi-stack reason")}
  <p class="stage"><span lang="en">{escape(stage_en)}</span><span lang="ja">{escape(stage_ja)}</span></p>
  <div class="nochart">{bi("No chart rendered", "チャートは描画されません")}</div>
  {details("Verifier output (verbatim)", "検証器の出力(原文)", verdict)}
  {details("Proposed spec (pretty-printed)", "提案された仕様(整形表示)", pretty_json(raw))}
</article>"""


# --- page ---------------------------------------------------------------------
CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
  --hairline:rgba(11,11,11,.10);--well:#fcfcfb;--well-border:#e1e0d9;
  --good:#0ca30c;--crit:#d03b3b;--code-bg:rgba(11,11,11,.045);--hatch:rgba(11,11,11,.04);
}
@media (prefers-color-scheme:dark){
  :root{
    --plane:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;
    --hairline:rgba(255,255,255,.10);--code-bg:rgba(255,255,255,.06);--hatch:rgba(255,255,255,.05);
  }
}
body{margin:0 auto;max-width:1240px;padding:40px 24px 72px;background:var(--plane);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans","Noto Sans CJK JP",
  "Hiragino Kaku Gothic ProN","Yu Gothic UI",Meiryo,sans-serif;line-height:1.55}
:lang(ja){font-family:"Noto Sans CJK JP","Noto Sans JP","Hiragino Kaku Gothic ProN",
  "Yu Gothic UI",Meiryo,sans-serif}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.86em}
h1{font-size:2.2rem;margin:.15em 0 .25em;display:flex;gap:.55em;align-items:baseline;flex-wrap:wrap}
h2{margin:52px 0 8px;font-size:1.3rem;display:flex;gap:.6em;align-items:baseline;flex-wrap:wrap}
.kicker{margin:0;color:var(--muted);font-size:.85rem;letter-spacing:.04em;display:flex;gap:1.2em;flex-wrap:wrap}
.tag{margin:0;font-size:1.02rem;color:var(--ink2)}
.bi{display:inline-flex;gap:.6em;align-items:baseline;flex-wrap:wrap}
.bi-stack p{margin:0}
.bi-stack p+p{margin-top:2px}
.lede{margin:14px 0 0;max-width:75ch}
.lede p{color:var(--ink2);font-size:.95rem}
.count{font-size:.85rem;font-weight:600;color:var(--ink2);border:1px solid var(--hairline);
  border-radius:999px;padding:1px 10px}
.intro{margin:0 0 16px;max-width:75ch}
.intro p{color:var(--ink2);font-size:.92rem}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-top:26px}
.tile{background:var(--surface);border:1px solid var(--hairline);border-radius:10px;padding:14px 16px}
.tile .num{font-size:2rem;font-weight:700;line-height:1.15}
.tile .lbl{font-size:.84rem;color:var(--ink2)}
.tile .lbl span{display:block}
.dot{display:inline-block;width:.55em;height:.55em;border-radius:50%;margin-right:.45em}
.dot.ok{background:var(--good)}
.dot.no{background:var(--crit)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px;margin-top:14px}
.step{background:var(--surface);border:1px solid var(--hairline);border-radius:10px;padding:16px}
.step .n{font-size:1.5rem;font-weight:700;color:var(--muted)}
.step h3{margin:.15em 0 .3em;font-size:1.02rem;display:flex;gap:.55em;align-items:baseline;flex-wrap:wrap}
.step .bi-stack p{font-size:.88rem;color:var(--ink2)}
.cards{display:grid;gap:18px;grid-template-columns:repeat(auto-fill,minmax(480px,1fr))}
.cards.blockedgrid{grid-template-columns:repeat(auto-fill,minmax(370px,1fr))}
@media (max-width:560px){.cards,.cards.blockedgrid{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--hairline);border-radius:10px;
  padding:16px 16px 12px;display:flex;flex-direction:column;gap:11px}
.cardhead{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:space-between}
.file{color:var(--muted);font-size:.78rem}
.intent span{display:block;font-weight:600}
.badge{display:inline-flex;align-items:center;gap:.5em;border:1px solid;border-radius:999px;
  padding:1px 12px;font-size:.88rem;font-weight:600}
.badge.ok{border-color:var(--good)}
.badge.ok .ic{color:var(--good)}
.badge.no{border-color:var(--crit)}
.badge.no .ic{color:var(--crit)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;gap:.55em;align-items:baseline;border:1px solid var(--hairline);
  border-radius:6px;padding:2px 9px;font-size:.8rem;color:var(--ink2)}
.chip code{color:var(--ink)}
.well{background:var(--well);border:1px solid var(--well-border);border-radius:8px;padding:10px;
  overflow-x:auto;text-align:center}
.well img{max-width:100%;height:auto}
.vcert{border:1px solid var(--hairline);border-radius:8px;padding:12px 14px;font-size:.8rem}
.vcert h2{margin:0 0 8px;font-size:.92rem;display:block}
.vcert h3{margin:10px 0 3px;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.vcert ul{margin:0;padding-left:1.15em;columns:2;column-gap:18px;color:var(--ink2)}
.vcert dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:0}
.vcert dt{color:var(--muted)}
.vcert dd{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:.7rem;word-break:break-all;color:var(--ink2)}
.reason p{font-size:.92rem}
.stage{margin:0;font-size:.84rem;color:var(--muted)}
.stage span{display:block}
.nochart{border:1px dashed var(--well-border);border-radius:8px;padding:14px;text-align:center;
  color:var(--muted);font-size:.9rem;
  background:repeating-linear-gradient(45deg,transparent 0 10px,var(--hatch) 10px 11px)}
details{border-top:1px solid var(--hairline);padding-top:8px}
details summary{cursor:pointer;color:var(--ink2);font-size:.88rem;font-weight:600}
details pre{background:var(--code-bg);border-radius:6px;padding:10px 12px;overflow-x:auto;
  font-size:.78rem;line-height:1.45;margin:8px 0 4px;white-space:pre-wrap;word-break:break-word}
footer{margin-top:60px;border-top:1px solid var(--hairline);padding-top:22px;font-size:.9rem;color:var(--ink2)}
footer .bi-stack{margin:0 0 14px;max-width:85ch}
footer code{color:var(--ink)}
"""


def tile(num: str, dot: str, label_en: str, label_ja: str) -> str:
    dot_html = f'<span class="dot {dot}"></span>' if dot else ""
    return (
        f'<div class="tile"><div class="num">{escape(num)}</div>'
        f'<div class="lbl">{dot_html}<span lang="en">{escape(label_en)}</span>'
        f'<span lang="ja">{escape(label_ja)}</span></div></div>'
    )


def step(n: int, title_en: str, title_ja: str, body_en: str, body_ja: str) -> str:
    return (
        f'<div class="step"><div class="n">{n}</div>'
        f'<h3><span lang="en">{escape(title_en)}</span><span lang="ja">{escape(title_ja)}</span></h3>'
        f"{bi_stack(body_en, body_ja)}</div>"
    )


def build_page(good_cards: list[str], bad_cards: list[str]) -> str:
    n_good, n_bad = len(good_cards), len(bad_cards)
    steps = "".join(
        [
            step(
                1,
                "Propose",
                "提案",
                "An untrusted model emits a VPlot spec: pure JSON data — transforms, encoding, "
                "a declared dataset hash. Never plotted values, never code.",
                "信頼されていないモデルがVPlot仕様を出力します。変換・エンコーディング・宣言された"
                "データセットハッシュからなる純粋なJSONデータです。プロット値もコードも一切含みません。",
            ),
            step(
                2,
                "Verify",
                "検証",
                "The trusted verifier strictly decodes the spec, recomputes the plotted table "
                "from the source CSV, and runs every blocking check "
                "(schema, dataset binding, encoding, policy).",
                "信頼済み検証器が仕様を厳密にデコードし、ソースCSVからプロット表を再計算し、"
                "すべてのブロッキング検査(スキーマ、データセット結合、エンコーディング、ポリシー)を実行します。",
            ),
            step(
                3,
                "Render or block",
                "描画またはブロック",
                "Only a fully verified spec becomes an SVG chart with an embedded certificate "
                "badge. Everything else: no chart.",
                "完全に検証された仕様だけが、証明バッジ埋め込みのSVGチャートになります。"
                "それ以外にチャートはありません。",
            ),
        ]
    )
    tiles = "".join(
        [
            tile(str(n_good), "ok", "Verified & rendered", "検証済み・描画"),
            tile(str(n_bad), "no", "Blocked, no chart", "ブロック・チャートなし"),
            tile("4", "", "Hashes per certificate", "証明書あたりのハッシュ数"),
            tile("0", "", "Model-supplied numbers plotted", "プロットされたモデル提供数値"),
        ]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Verified plots — PoC demo / 検証済みプロット — PoCデモ</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <p class="kicker"><span lang="en">figure-verification · throwaway PoC demo</span><span lang="ja">図表検証 · 使い捨てPoCデモ</span></p>
  <h1><span lang="en">Verified plots</span><span lang="ja">検証済みプロット</span></h1>
  <p class="tag" lang="en">A chart renders only after every check passes.</p>
  <p class="tag" lang="ja">すべての検査に合格したチャートだけが描画されます。</p>
  <div class="lede">{
        bi_stack(
            "A weak local LLM only proposes a restricted JSON chart spec (VPlot). A separate "
            "trusted verifier deterministically recomputes the plotted data from the source CSV, "
            "runs structured checks, blocks any spec that fails, and renders only verified "
            "charts — each carrying a provenance certificate.",
            "非力なローカルLLMは、制限付きJSONチャート仕様(VPlot)を提案するだけです。独立した"
            "信頼済み検証器がソースCSVからプロットデータを決定論的に再計算し、構造化された検査を"
            "実行して、不合格の仕様をブロックし、検証済みチャートのみを描画します。各チャートには"
            "来歴証明書が付属します。",
        )
    }</div>
  <div class="tiles">{tiles}</div>
</header>

<h2>{bi("How it works", "仕組み")}</h2>
<div class="steps">{steps}</div>

<h2 id="verified">{bi("Verified — rendered", "検証済み — 描画されたチャート")}<span class="count">{
        n_good
    }/{n_good}</span></h2>
<div class="intro">{
        bi_stack(
            "All 10 good specs from the golden corpus, rendered through render(): "
            "decode → recompute → checks → SVG + certificate. The certificate badge under "
            "each chart is the trusted renderer's own output (badge_html) — this page "
            "styles it, never alters it.",
            "ゴールデンコーパスの正常仕様10件。render()を通して描画します:デコード → 再計算 → "
            "検査 → SVG+証明書。各チャート下の証明バッジは信頼済みレンダラー自身の出力"
            "(badge_html)です。このページは体裁を整えるだけで、内容は変えません。",
        )
    }</div>
<div class="cards">{"".join(good_cards)}</div>

<h2 id="blocked">{bi("Blocked — no chart", "ブロック — チャートなし")}<span class="count">{n_bad}/{
        n_bad
    }</span></h2>
<div class="intro">{
        bi_stack(
            "All 18 bad specs from the golden corpus — each blocked at its layer, shown with the "
            "verifier's real output. This page renders no chart for any of them.",
            "ゴールデンコーパスの不正仕様18件 — それぞれの層でブロックされ、検証器の実際の出力と"
            "ともに表示します。これらに対してチャートは一切描画されません。",
        )
    }</div>
<div class="cards blockedgrid">{"".join(bad_cards)}</div>

<footer>
{
        bi_stack(
            "“Verified” means four artifacts are mutually consistent and every check passed: the "
            "spec validated against the VPlot v0.1 DSL; the plotted table the verifier recomputed "
            "independently from the source CSV; the emitted Vega-Lite, which inlines only that "
            "recomputed table; and the provenance badge (dataset hash, spec hash, plotted-table "
            "hash, passed checks).",
            "「検証済み」とは、4つの成果物が相互に整合し、すべての検査に合格したことを意味します:"
            "VPlot v0.1 DSLとして検証された仕様、検証器がソースCSVから独立に再計算したプロット表、"
            "その再計算された表のみを埋め込むVega-Lite出力、そして来歴バッジ(データセットハッシュ、"
            "仕様ハッシュ、プロット表ハッシュ、合格した検査)です。",
        )
    }
{
        bi_stack(
            "The renderer only ever receives verifier-recomputed data, so a chart cannot display "
            "model-supplied numbers — that class of lie is impossible by construction. Not "
            "covered: representativeness or intent — a spec may select an unflattering-but-real "
            "subset and still pass every check; honest selection stays the author's job.",
            "レンダラーは検証器が再計算したデータしか受け取らないため、チャートがモデル提供の数値を"
            "表示することは構造上不可能です。対象外:代表性と意図 — 仕様は実在するものの不都合な"
            "部分集合を選んでもすべての検査に合格し得ます。誠実な選択は作成者の責任のままです。",
        )
    }
{
        bi_stack(
            "Trusted but not formally verified: the vl-convert Vega runtime, SVG rasterization, "
            "the browser, the final pixels. The claim is about the data-and-spec layer, not the "
            "renderer. Chart SVGs and certificate badges appear verbatim as the trusted M1 "
            "renderer produced them; this page only frames and styles them.",
            "信頼するものの形式的には検証していない領域:vl-convert Vegaランタイム、SVGラスタライズ、"
            "ブラウザ、最終的なピクセル。この主張はデータと仕様の層に関するもので、レンダラーに"
            "関するものではありません。チャートSVGとそのバッジは信頼済みM1レンダラーの出力を"
            "そのまま掲載しています。このページはそれを額装するだけです。",
        )
    }
{
        bi_stack(
            "This page is fully offline: no scripts, no external requests. Throwaway demo on "
            "branch poc/bilingual-demo; rebuild with: uv run demo/build_demo.py",
            "このページは完全オフラインです:スクリプトなし、外部リクエストなし。ブランチ "
            "poc/bilingual-demo 上の使い捨てデモです。再生成: uv run demo/build_demo.py",
        )
    }
</footer>
</body>
</html>
"""


def main() -> None:
    index = json.loads((ROOT / "examples" / "index.json").read_text(encoding="utf-8"))
    good_entries: list[dict[str, str]] = index["good_specs"]
    bad_entries: list[dict[str, str]] = index["bad_specs"]
    if len(good_entries) != len(INTENT_JA) or len(bad_entries) != len(REASON_JA):
        msg = "index.json corpus size diverged from the JA translation tables"
        raise SystemExit(msg)
    good_cards = [good_card(e) for e in good_entries]
    bad_cards = [bad_card(e) for e in bad_entries]
    page = build_page(good_cards, bad_cards)
    OUT.write_text(page, encoding="utf-8")
    print(
        f"wrote {OUT} ({OUT.stat().st_size:,} bytes): {len(good_cards)} verified, {len(bad_cards)} blocked"
    )


if __name__ == "__main__":
    main()
