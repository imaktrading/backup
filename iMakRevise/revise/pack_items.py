"""pack_items.py - パック商品 (multi-pack listing) mapping 読込.

スプシ N 列は 1個分の仕入¥ しか記録されないため、
listing が N個セット販売の場合 cost × pack で effective_cost を計算する必要あり。

HQ が `C:/dev/iMak_data/revise/pack_items.json` を管理 (= 共有 data 領域)、
リバイスくんは読込のみ。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Optional

PACK_ITEMS_PATH = Path("C:/dev/iMak_data/revise/pack_items.json")


def load_pack_items(path: Optional[Path] = None) -> Dict[str, int]:
    """ItemID → pack数 mapping 読込. ファイル無ければ空 dict (= fail-safe).

    `_` prefix の meta key (= _comment / _updated 等) は除外。
    """
    p = path or PACK_ITEMS_PATH
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in data.items()
                if not k.startswith("_") and isinstance(v, int)}
    except (OSError, ValueError, TypeError) as e:
        print(f"  [WARN] pack_items.json 読込失敗: {e}")
        return {}


def get_pack_count(item_id: str, cache: Optional[Dict[str, int]] = None) -> int:
    """ItemID の pack数 取得. 未登録なら 1 (= 通常 listing)."""
    if cache is None:
        cache = load_pack_items()
    return cache.get(str(item_id), 1)


# title から pack 疑い検知 (= 未登録 pack の漏れ防止)
_PACK_KEYWORDS_PATTERN = re.compile(
    r"(セット|枚入り|個入り|本入り|ピース入り|"
    r"\d+\s*(?:枚|個|本|ピース|pcs?|pack|set)|"
    r"[×x]\s*\d+\s*(?:枚|個|本|pcs?|pack|set))",
    re.IGNORECASE,
)


def detect_pack_suspicion(title: str) -> bool:
    """title に pack 系 keyword あれば True (= pack 疑い).

    false positive 抑制のため、数字 + 単位 の組合せを要求 (= 「10」 単独や型番混入を排除)。
    """
    if not title:
        return False
    return bool(_PACK_KEYWORDS_PATTERN.search(title))
