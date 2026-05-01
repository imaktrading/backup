"""compare_sheets - 2 つのスプシの D 列 (売切○) を突き合わせて差分を出す.

並走運用 (trabajo 本番 vs inventory コピー) で「同じ行に対して両者が同じ判定を
出しているか」を検証するためのツール。

使い方:
    python tools/compare_sheets.py --a <trabajo_sheet_id> --b <inventory_sheet_id>
    python tools/compare_sheets.py --a <id1> --b <id2> --label-a trabajo --label-b inventory

出力:
    decision_log/sheet_diff_<ts>.md (突合レポート、4 区分集計):
      - 一致 ○○:    両者とも売切判定
      - 一致 -- :    両者とも在庫あり判定
      - A=○ B=- :   inventory 漏れ (trabajo は ○ だが inventory が空欄 = 漏れ NG)
      - A=- B=○ :   inventory 過剰 (trabajo は空欄だが inventory が ○ = 過剰検知)

マッチング: 列 A (URL) を primary key、なければ row_index で fallback。

売切判定文字: U+25CB (○ WHITE CIRCLE, inventory 側) と U+3007 (〇 IDEOGRAPHIC NUMBER
ZERO, trabajo 側) の双方を売切扱いとする (Phase 9c 突合で文字コード違いによる
判定スベりが発覚した実例あり, 2026-05-01).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

SOLD_MARKS = {"○", "〇"}  # ○ (inventory) / 〇 (trabajo)


def _is_sold(v: str) -> bool:
    return (v or "").strip() in SOLD_MARKS

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sheet_updater import (  # noqa: E402
    open_sheet_by_id, get_listings_worksheet, read_listings_rows, LISTINGS_GID,
)


def fetch_sold_marks(sheet_id: str) -> dict:
    """sheet から row_index, url, item_id, sold_mark を取り込んで dict 化.

    Returns: {
        "by_url":     {url: {row, item_id, title, sold}},
        "by_row":     {row_index: {url, item_id, title, sold}},
        "title":      spreadsheet title,
        "ws_title":   worksheet title,
        "row_count":  rows 件数,
    }
    """
    sh = open_sheet_by_id(sheet_id)
    ws = get_listings_worksheet(sh, gid=LISTINGS_GID)
    rows = read_listings_rows(ws, start_row=2, end_row=None, only_with_url=False)
    by_url = {}
    by_row = {}
    for r in rows:
        info = {
            "row": r["row_index"],
            "url": r.get("url", ""),
            "item_id": r.get("item_id", ""),
            "title": (r.get("title") or "")[:50],
            "sold": (r.get("current_sold") or "").strip(),  # "○" or ""
        }
        if info["url"]:
            by_url[info["url"]] = info
        by_row[info["row"]] = info
    return {
        "by_url": by_url,
        "by_row": by_row,
        "title": sh.title,
        "ws_title": ws.title,
        "row_count": len(rows),
    }


def diff_sheets(a: dict, b: dict, label_a: str = "A", label_b: str = "B") -> dict:
    """A と B の sold marks を比較して 4 区分にまとめる."""
    both_sold = []      # ○ ○
    both_blank = []     # - -
    a_only_sold = []    # A=○ B=-  (B の漏れ)
    b_only_sold = []    # A=- B=○  (B の過剰)
    only_in_a = []      # B に存在しない URL
    only_in_b = []      # A に存在しない URL

    a_urls = set(a["by_url"].keys())
    b_urls = set(b["by_url"].keys())
    common = a_urls & b_urls

    for u in common:
        ai = a["by_url"][u]
        bi = b["by_url"][u]
        a_sold = _is_sold(ai["sold"])
        b_sold = _is_sold(bi["sold"])
        info = {
            "url": u,
            f"{label_a}_row": ai["row"],
            f"{label_b}_row": bi["row"],
            f"{label_a}_sold": ai["sold"],
            f"{label_b}_sold": bi["sold"],
            "item_id": ai["item_id"] or bi["item_id"],
            "title": ai["title"] or bi["title"],
        }
        if a_sold and b_sold:
            both_sold.append(info)
        elif not a_sold and not b_sold:
            both_blank.append(info)
        elif a_sold and not b_sold:
            a_only_sold.append(info)
        else:
            b_only_sold.append(info)

    for u in a_urls - b_urls:
        only_in_a.append(a["by_url"][u])
    for u in b_urls - a_urls:
        only_in_b.append(b["by_url"][u])

    return {
        "both_sold": both_sold,
        "both_blank": both_blank,
        "a_only_sold": a_only_sold,
        "b_only_sold": b_only_sold,
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "common_count": len(common),
    }


def render_md(diff: dict, a: dict, b: dict, label_a: str, label_b: str,
              sheet_id_a: str, sheet_id_b: str) -> str:
    lines = []
    lines.append(f"# スプシ突合レポート: {label_a} vs {label_b}")
    lines.append("")
    lines.append(f"- ts: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- {label_a}: `{sheet_id_a}` ({a['title']} / {a['ws_title']}) rows={a['row_count']}")
    lines.append(f"- {label_b}: `{sheet_id_b}` ({b['title']} / {b['ws_title']}) rows={b['row_count']}")
    lines.append(f"- 共通 URL: {diff['common_count']} 件")
    lines.append("")
    lines.append("## サマリ")
    lines.append("")
    lines.append("| 区分 | 件数 | 意味 |")
    lines.append("|---|---:|---|")
    lines.append(f"| 一致 ○○ | {len(diff['both_sold'])} | 両者とも売切判定 |")
    lines.append(f"| 一致 -- | {len(diff['both_blank'])} | 両者とも在庫あり判定 |")
    lines.append(f"| **{label_a}=○ {label_b}=-** | **{len(diff['a_only_sold'])}** | **{label_b} の漏れ (在庫なしを在庫ありと誤判定)** |")
    lines.append(f"| {label_a}=- {label_b}=○ | {len(diff['b_only_sold'])} | {label_b} の過剰 (在庫ありを在庫なしと誤判定) |")
    lines.append(f"| {label_a} のみ | {len(diff['only_in_a'])} | {label_b} に該当 URL なし |")
    lines.append(f"| {label_b} のみ | {len(diff['only_in_b'])} | {label_a} に該当 URL なし |")
    lines.append("")

    if diff['a_only_sold']:
        lines.append(f"## ⚠️ {label_b} 漏れ (= 致命、在庫切れ検知できてない)")
        lines.append(f"({label_a} は ○ なのに {label_b} は空欄)")
        lines.append("")
        lines.append(f"| {label_a}_row | {label_b}_row | item_id | url | title |")
        lines.append("|---|---|---|---|---|")
        for r in diff['a_only_sold'][:50]:
            lines.append(f"| {r[f'{label_a}_row']} | {r[f'{label_b}_row']} | {r['item_id']} | {r['url']} | {r['title']} |")
        if len(diff['a_only_sold']) > 50:
            lines.append(f"\n... +{len(diff['a_only_sold']) - 50} 件")
        lines.append("")

    if diff['b_only_sold']:
        lines.append(f"## {label_b} 過剰 (= 機会損失、在庫を売切と誤判定)")
        lines.append(f"({label_a} は空欄なのに {label_b} は ○)")
        lines.append("")
        lines.append(f"| {label_a}_row | {label_b}_row | item_id | url | title |")
        lines.append("|---|---|---|---|---|")
        for r in diff['b_only_sold'][:50]:
            lines.append(f"| {r[f'{label_a}_row']} | {r[f'{label_b}_row']} | {r['item_id']} | {r['url']} | {r['title']} |")
        if len(diff['b_only_sold']) > 50:
            lines.append(f"\n... +{len(diff['b_only_sold']) - 50} 件")
        lines.append("")

    if diff['only_in_a']:
        lines.append(f"## {label_a} のみに存在 ({len(diff['only_in_a'])} 件)")
        lines.append(f"{label_b} スプシに同じ URL の行が無い (= スプシ構成差、商品追加 timing 差 等)")
        lines.append("")
    if diff['only_in_b']:
        lines.append(f"## {label_b} のみに存在 ({len(diff['only_in_b'])} 件)")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="2 スプシの D 列を突合 (Phase 9c)")
    parser.add_argument("--a", required=True, help="A 側 (基準) スプシ ID or URL")
    parser.add_argument("--b", required=True, help="B 側 (比較) スプシ ID or URL")
    parser.add_argument("--label-a", default="trabajo", help="A 側ラベル (default: trabajo)")
    parser.add_argument("--label-b", default="inventory", help="B 側ラベル (default: inventory)")
    args = parser.parse_args()

    # URL から ID 抽出 (簡易)
    import re
    def _extract(s):
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", s)
        return m.group(1) if m else s.strip()
    sid_a = _extract(args.a)
    sid_b = _extract(args.b)

    print(f"[fetch] {args.label_a}: {sid_a}")
    a = fetch_sold_marks(sid_a)
    print(f"  → {a['title']} / {a['ws_title']} rows={a['row_count']}")
    print(f"[fetch] {args.label_b}: {sid_b}")
    b = fetch_sold_marks(sid_b)
    print(f"  → {b['title']} / {b['ws_title']} rows={b['row_count']}")

    diff = diff_sheets(a, b, label_a=args.label_a, label_b=args.label_b)
    md = render_md(diff, a, b, args.label_a, args.label_b, sid_a, sid_b)

    out = ROOT / "decision_log" / f"sheet_diff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    out.write_text(md, encoding="utf-8")

    print()
    print("=" * 60)
    print(f"共通 URL: {diff['common_count']}")
    print(f"  一致 ○○: {len(diff['both_sold'])}")
    print(f"  一致 --:  {len(diff['both_blank'])}")
    print(f"  ⚠️ {args.label_a}=○ {args.label_b}=-: {len(diff['a_only_sold'])} 件 ({args.label_b} 漏れ)")
    print(f"  {args.label_a}=- {args.label_b}=○:    {len(diff['b_only_sold'])} 件 ({args.label_b} 過剰)")
    print(f"  {args.label_a} のみ: {len(diff['only_in_a'])} / {args.label_b} のみ: {len(diff['only_in_b'])}")
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
