"""巡回エラー FLG マーカーの生成 / 解析 (HIGH/LOW listings 共通).

スプシの「巡回ERR」列 (HIGH/LOW=AK, 公式=H) に書く marker の format を一元管理する。

format: ``⚠ <ERRTYPE> ×<N> <MM/DD HH:MM>``  例: ``⚠ ReadTimeout ×2 06/11 06:03``

- ``N`` = 連続エラー回数 (= 同 row が連続して scrape 失敗した cycle 数)。
  成功した cycle で clear (= "") されるので、N>=2 は「複数 cycle 連続して在庫不明」を意味する。
- 成功行は clear ("") する → 復活したら自動で消える (自己修復、reconciliation 規約)。
- 持続エラー (N>=PERSISTENT_THRESHOLD) はメールに別掲して手動 chk を促す。

※ 公式側 (iMakeBayAPI/inventory_monitor/err_flag.py) に同一実装を複製している。
   cross-import の脆さを避けるため意図的に複製。format を変える時は両方直すこと。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

#: 連続エラーがこの回数以上でメール別掲 (= 手動 chk 促し)
PERSISTENT_THRESHOLD = 3

#: 連続エラーがこの回数以上 = 「回復待ち」ではなく「死んだ仕入元 (要 URL 差替)」として別枠化。
#: LOW は 1 日 3 巡回・HIGH は 6 巡回なので ×8 ≒ 1〜3 日回復しない = transient ではない。
DEAD_SOURCE_THRESHOLD = 8

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
    # "XxxError" -> "Xxx" (末尾 Error を落として簡潔化)
    if head.endswith("Error") and len(head) > len("Error"):
        head = head[: -len("Error")]
    return head[:24] or "Error"


def marker_count(marker: str) -> int:
    """marker 文字列から連続エラー回数を取り出す (なければ 0)."""
    m = _COUNT_RE.search(marker or "")
    return int(m.group(1)) if m else 0


def build_err_marker(err: str, prev_marker: str = "", now: Optional[datetime] = None) -> str:
    """エラー行の AK/H 列に書く marker を生成 (連続回数を prev からインクリメント).

    Args:
        err:         今 cycle のエラー文字列 (例 "ReadTimeoutError: ...")
        prev_marker: 前 cycle に書かれていた marker (空なら今回が連続1回目)
        now:         時刻 (test 用に注入可、省略時は datetime.now())
    """
    now = now or datetime.now()
    etype = _short_err_type(err)
    count = marker_count(prev_marker) + 1
    return f"⚠ {etype} ×{count} {now.strftime('%m/%d %H:%M')}"


def is_persistent(marker: str, threshold: int = PERSISTENT_THRESHOLD) -> bool:
    """marker が持続エラー (連続 threshold 回以上) か."""
    return marker_count(marker) >= threshold


def is_dead_source(marker: str, threshold: int = DEAD_SOURCE_THRESHOLD) -> bool:
    """marker が「死んだ仕入元」(連続 threshold 回以上 = 自己回復を待っても戻らない) か.

    2026-07-28 HQ 指摘: 持続エラーは ×3 で「要手動 chk」に上がるが、そこから**降りる経路が
    自己回復しかない**。回復しない URL (出品終了・削除済 等) は ×4 → ×10 → ×20 と単調に育ち、
    「要対応リスト」が墓場になる (安全原則3: DLQ を墓場にしない、に反する)。
    ×DEAD_SOURCE_THRESHOLD 以降は **「回復待ち」ではなく「仕入元の差替が要る」** と分類を変え、
    別枠で提示する (件数を消すのではなく、必要な対処の種類を変える)。
    """
    return marker_count(marker) >= threshold
