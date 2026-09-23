"""chara_keywords - HQ の `chara_market.csv` から トレジャーハント(キャラ軸)の検索語を作る.

2026-09-21 新設 (HQ 依頼 `2026-09-21_chara_keywords_draft`)。
`treasure_keywords.py` (demand_market.csv = カード番号軸) とは別の需要ソース:
  - テラピーク実売台帳をキャラ名に束ね、5枚以上売れたキャラだけを残した一覧
  - 列は demand_market.csv と同じ + 末尾2列 (`うちの実績` / `出どころ`)。
    キャラ名は「和名」列。「番号」列は空 (キャラ軸には番号が無い)

カードごとの上限仕入れ値は **意図的に空**(2026-09-21 ユーザー確定: キャラ軸に個別上限は無く、
会社の上限 ¥70,000 だけが効く)。`card_cost_ok` はこの表を渡しても limits が空になるので
常に通す (fail-open のまま = 仕様どおり)。

語は **和名のみ**(番号が無いので番号語は作らない)。
"""
from __future__ import annotations

import csv
from pathlib import Path

from scrapers.demand_keywords import PREFIX

CSV_PATH = Path("C:/dev/iMak_data/hq/market_sold/chara_market.csv")


def load_rows(csv_path: Path | None = None) -> list[dict]:
    """`chara_market.csv` を読む。 無ければ空 list (= 走らない扱いは呼出側の判断)."""
    path = csv_path or CSV_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if any((row or {}).values())]


def build_keywords(rows: list[dict], prefix: str = PREFIX) -> list[str]:
    """和名を語にする (純関数)。 重複は落とす。 CSV の行順 (= 優先順) を保つ."""
    seen: list[str] = []
    for r in rows:
        name = (r.get("和名") or "").strip()
        if not name:
            continue
        term = f"{prefix} {name}"
        if term not in seen:
            seen.append(term)
    return seen
