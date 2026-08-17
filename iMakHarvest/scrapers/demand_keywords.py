"""demand_keywords - 「需要が実証されたカード」から収集キーワードを作る.

2026-08-18 新設 (user 指摘「ファネル分析はそのための分析では？」)。

これまでの収集キーワードは弾コードの総当たり (`psa_search_terms`) で、
**市場にある物を舐めているだけで需要を見ていなかった**。
HQ の「ファネル分析」スプシには 在庫切れ × 需要実証済 (= RESTOCK バケツ) が
既に出ているので、そこからカード番号を取って検索語にする。

  RESTOCK の定義 (ファネル分析 Summary より):
    在庫=0 ∩ 需要>0 (生涯販売 + watch + 90日 impressions)

つまり **「売れる/見られているのに今 出せていないカード」**。ここを埋めるのが
一番 効率がよい。番号が取れない行 (キャラ名だけの出品等) は対象外にする
(推測で検索語を作ると別カードを拾うため = 出品の正確性原則)。
"""
from __future__ import annotations

import re

FUNNEL_SHEET_ID = "1UkaI4W6YCJgUbjgF7LLNN9_fHeVuz5qB4r9RqImElwg"
RESTOCK_TAB = "RESTOCK"
PREFIX = "PSA10"

# カード番号 (例 OP08-106 / GD02-072 / SB02-001 / SV4a-123)。
# 弾コード = 英字2-4 + 数字2 (+ 英小文字1)、 通し番号 = 数字3。
_CARD_NO_RE = re.compile(r"\b([A-Z]{2,4}\d{2}[A-Za-z]?)[-‐ ]?(\d{3})\b")

# PSA 出品だけを対象にする (同じ RESTOCK に PSA でない出品も入っている)
_PSA_RE = re.compile(r"\bPSA\s*10\b|\bPSA\b", re.IGNORECASE)


def extract_card_number(title: str) -> str:
    """出品タイトルからカード番号を取り出す (取れなければ "")."""
    m = _CARD_NO_RE.search((title or "").upper())
    if not m:
        return ""
    return f"{m.group(1)}-{m.group(2)}"


def demand_score(row: dict) -> float:
    """需要の強さ。 実売 > watch > 露出 の順に効かせる (並べ替え用の目安)."""
    def _num(key: str) -> float:
        try:
            return float(str(row.get(key) or "0").replace(",", ""))
        except ValueError:
            return 0.0

    return _num("sales90") * 100 + _num("watch") * 10 + _num("impr") / 1000.0


def build_keywords_from_rows(rows: list[dict], prefix: str = PREFIX,
                             limit: int = 0) -> list[str]:
    """RESTOCK 行から検索キーワードを作る (純関数).

    Args:
        rows: {"title","watch","impr","sales90",...} の dict 列 (ヘッダ行は含めない)
        limit: 上位何語まで (0 = 全部)
    Returns:
        需要の強い順・重複なしの検索キーワード (例 "PSA10 OP08-106")
    """
    best: dict[str, float] = {}
    for r in rows:
        title = r.get("title") or ""
        if not _PSA_RE.search(title):
            continue
        code = extract_card_number(title)
        if not code:
            continue
        score = demand_score(r)
        if score > best.get(code, -1.0):
            best[code] = score
    ordered = sorted(best, key=lambda c: (-best[c], c))
    if limit:
        ordered = ordered[:limit]
    return [f"{prefix} {c}" for c in ordered]


def fetch_restock_rows(sheet_id: str = FUNNEL_SHEET_ID, tab: str = RESTOCK_TAB) -> list[dict]:
    """ファネル分析スプシの RESTOCK タブを読む (通信あり)."""
    import sheet_writer  # noqa: PLC0415

    ws = sheet_writer.open_sheet_by_id(sheet_id).worksheet(tab)
    values = ws.get_all_values()
    if len(values) < 2:
        return []
    header = values[0]
    return [dict(zip(header, r)) for r in values[1:] if any(r)]


def build_demand_keywords(sheet_id: str = FUNNEL_SHEET_ID, prefix: str = PREFIX,
                          limit: int = 0) -> list[str]:
    """ファネル分析から 需要実証済カードの検索キーワードを作る (通信あり)."""
    return build_keywords_from_rows(fetch_restock_rows(sheet_id), prefix=prefix,
                                    limit=limit)
