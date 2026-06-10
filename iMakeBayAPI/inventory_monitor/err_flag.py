"""巡回エラー FLG マーカーの生成 / 解析 (公式 inventory_monitor 用).

スプシの「巡回ERR」列 (公式シート1=H) に書く marker の format を一元管理する。

format: ``⚠ <ERRTYPE> ×<N> <MM/DD HH:MM>``  例: ``⚠ Timeout ×2 06/11 06:03``

- ``N`` = 連続エラー回数 (= 同 listing が連続して scrape 失敗した cycle 数)。
  成功した cycle で clear (= "") されるので、N>=2 は「複数 cycle 連続して在庫不明」を意味する。
- 成功行は clear ("") する → 復活したら自動で消える (自己修復、reconciliation 規約)。
- 持続エラー (N>=PERSISTENT_THRESHOLD) はメールに別掲して手動 chk を促す。

※ HIGH/LOW 側 (iMakInventory/err_flag.py) に同一実装を複製している。
   cross-import の脆さを避けるため意図的に複製。format を変える時は両方直すこと。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

#: 連続エラーがこの回数以上でメール別掲 (= 手動 chk 促し)
PERSISTENT_THRESHOLD = 3

_COUNT_RE = re.compile(r"×(\d+)")


def _short_err_type(err: str) -> str:
    """エラー文字列から短い型名を取り出す.

    "ReadTimeoutError: HTTPConnectionPool(...)" -> "ReadTimeout"
    "unsupported supplier: ... " -> "unsupported"
    "scraper returned None (fail-closed)" -> "scraper"
    """
    err = (err or "").strip()
    if not err:
        return "Error"
    head = err.split(":", 1)[0].strip()
    head = head.split()[0] if head else "Error"
    if head.endswith("Error") and len(head) > len("Error"):
        head = head[: -len("Error")]
    return head[:24] or "Error"


def marker_count(marker: str) -> int:
    """marker 文字列から連続エラー回数を取り出す (なければ 0)."""
    m = _COUNT_RE.search(marker or "")
    return int(m.group(1)) if m else 0


def build_err_marker(err: str, prev_marker: str = "", now: Optional[datetime] = None) -> str:
    """エラー行の H 列に書く marker を生成 (連続回数を prev からインクリメント)."""
    now = now or datetime.now()
    etype = _short_err_type(err)
    count = marker_count(prev_marker) + 1
    return f"⚠ {etype} ×{count} {now.strftime('%m/%d %H:%M')}"


def is_persistent(marker: str, threshold: int = PERSISTENT_THRESHOLD) -> bool:
    """marker が持続エラー (連続 threshold 回以上) か."""
    return marker_count(marker) >= threshold
