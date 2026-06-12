"""eBay active listing snapshot CSV reader.

Phase 1c (= 2026-05-27):
スプシ C 列 title (= mercari 適当 / 公式 brand+name) は抽出失敗率が高いため、
B 列 eBay item ID → snapshot 経由 → eBay 正規 title (= 出品くん生成、 必ず card_id / 型番含む)
で KEY 抽出する。

snapshot 構造 (= 実機 `ebay_active_2026-05-25_145033.csv` で確認):
- Item number  (col 1, str)  = eBay item ID
- Title        (col 2, str)  = eBay 正規 title
- Currency / Current price / Listing site / Available quantity / Shipping profile name
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Optional


DEFAULT_SNAPSHOT_DIR = Path(r"C:/dev/iMak_data/snapshots")
SNAPSHOT_GLOB = "ebay_active_*.csv"

# CSV header field names (= snapshot 仕様、 列名固定)
FIELD_ITEM_NUMBER = "Item number"
FIELD_TITLE = "Title"


def find_latest_snapshot(snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR) -> Optional[Path]:
    """`ebay_active_*.csv` の最新 file を返す.

    sort key = filename (= `ebay_active_YYYY-MM-DD_HHMMSS.csv` 命名規約で
    辞書順 = 時系列順)。 dir / file が無ければ None。
    """
    if not snapshot_dir.exists():
        return None
    candidates = sorted(snapshot_dir.glob(SNAPSHOT_GLOB))
    if not candidates:
        return None
    return candidates[-1]


def load_snapshot_titles(path: Path) -> Dict[str, str]:
    """snapshot CSV から {item_id: title} dict を構築.

    - encoding: UTF-8 (= eBay export 仕様)
    - newline 処理は csv module に委譲 (newline="")
    - 列名不一致なら ValueError raise (= 仕様変更検知)
    """
    out: Dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or FIELD_ITEM_NUMBER not in reader.fieldnames:
            raise ValueError(
                f"snapshot CSV header に {FIELD_ITEM_NUMBER!r} 列がない: "
                f"path={path}  header={reader.fieldnames!r}"
            )
        if FIELD_TITLE not in reader.fieldnames:
            raise ValueError(
                f"snapshot CSV header に {FIELD_TITLE!r} 列がない: "
                f"path={path}  header={reader.fieldnames!r}"
            )
        for row in reader:
            item_id = (row.get(FIELD_ITEM_NUMBER) or "").strip()
            title = (row.get(FIELD_TITLE) or "").strip()
            if item_id:
                out[item_id] = title
    return out
