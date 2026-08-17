"""split_psa10_by_game - 既存の `mercari_psa10` をゲーム毎タブに振り分ける.

2026-08-18 新設 (user 指示「中間スプシへは カード毎にシートわけて」→ ゲーム毎4タブ)。

- 判定は `psa_game.detect_item_game` (タイトル + カタログ和名 + 弾コード)。判らない物は `_other`。
- **元タブは触らない** (コピーのみ)。中身を確認してから元タブを消すのは人の判断。
- 重複は 全 mercari_* タブ横断で見るので、 二度流しても増えない。

使い方:
  python tools/split_psa10_by_game.py --dry-run
  python tools/split_psa10_by_game.py
"""
from __future__ import annotations

import argparse
import collections
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sheet_writer_amazon import (  # noqa: E402
    COL_CERT, COL_CONDITION, COL_DESCRIPTION, COL_IMAGES, COL_PRICE, COL_TITLE, COL_URL,
)
from run_harvest_mercari_psa10 import item_game  # noqa: E402
from scrapers import psa_game  # noqa: E402


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _cell(row: list, col: int) -> str:
    return (row[col - 1] or "").strip() if len(row) >= col else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-label", default="psa10", help="元タブ (= mercari_<label>)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from sheet_writer_mercari_search import (  # noqa: PLC0415
        append_mercari_search_items, build_mercari_tab_name,
    )
    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    sh = open_seller_staging_sheet()
    src = build_mercari_tab_name(args.src_label)
    values = sh.worksheet(src).get_all_values()
    _log(f"{src}: {len(values) - 1} 行")

    groups: dict[str, list] = collections.defaultdict(list)
    for row in values[1:]:
        url = _cell(row, COL_URL)
        if not url:
            continue
        title = _cell(row, COL_TITLE)
        game = item_game({"title": title, "vision": {}})
        groups[game].append({
            "url": url, "title": title,
            "condition": _cell(row, COL_CONDITION),
            "price_jpy": _cell(row, COL_PRICE),
            "image_urls": _cell(row, COL_IMAGES),
            "description": _cell(row, COL_DESCRIPTION),
            "cert": _cell(row, COL_CERT),
        })

    for game, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        _log(f"  {psa_game.tab_label(args.src_label, game)}: {len(items)} 行")
    if args.dry_run:
        _log("dry-run → 書込なし")
        return 0

    for game, items in groups.items():
        # ★ここでは横断 dedupe を使わない。 元タブ自身が「既にある」判定になって
        # 1 行も移せなくなるため。 移送先タブ内の dedupe は効くので二度流しても増えない。
        res = append_mercari_search_items(items, label=psa_game.tab_label(args.src_label, game),
                                          cross_tab_dedupe=False)
        _log(f"[SHEET] {res}")
    _log("★元タブ (mercari_psa10) はそのまま残してある。中身を確認してから消すこと")
    return 0


if __name__ == "__main__":
    sys.exit(main())
