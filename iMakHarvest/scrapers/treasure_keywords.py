"""treasure_keywords - HQ の `demand_market.csv` から トレジャーハントの検索語と上限仕入れ値を作る.

2026-09-18 新設 (HQ 依頼 `2026-09-18_treasure_hunt_harvest`)。
`demand_keywords.py` (ファネル分析 RESTOCK) とは **別の需要ソース**:
  - こちらは eBay Research (Terapeak) の実売台帳から
    「2個以上売れ、かつ うちが出していない」カードだけを残した一覧 (HQ 側で毎回作り直す)。
  - 列: 番号 / product_id / 和名 / 英名 / ゲーム / 売れた数 / 出品本数 /
        実売中央値 / 上限仕入れ値(円) / 市場のタイトル例

語は **和名 + 番号 の両方**を作る (HQ 回答 2026-09-18)。番号は必ず入っているので
lookup に失敗することはない (和名が空の行 = product_id が引けなかった行でも番号はある)。
"""
from __future__ import annotations

import csv
from pathlib import Path

import re

from scrapers.demand_keywords import PREFIX, extract_card_number

CSV_PATH = Path("C:/dev/iMak_data/hq/market_sold/demand_market.csv")

# demand_keywords.extract_card_number の分数表記 (#077/071) は先頭に "#" を要求するが、
# 出品タイトルは "020/M-P" のように "#" 無しで書かれることが多い。 こちらは CSV の
# 番号列 (例 "020/M-P" "080/073") と同じ書式でそのまま拾う。
_BARE_FRACTION_RE = re.compile(r"\b(\d{2,3}/[A-Za-z0-9]{1,4}(?:-[A-Za-z0-9]{1,2})?)\b")


def extract_number(title: str) -> str:
    """タイトルから CSV の番号列と同じ書式の番号を抜く (取れなければ "").

    分数表記 (020/M-P 等) を先に見る。 `demand_keywords.extract_card_number` の
    弾コード正規表現は "PSA10 020/..." の "PSA10" を弾コード風 (PSA+10) と
    誤認して "PSA10-020" を作ってしまうため (実測)、 先に分数表記で確定させる。
    """
    m = _BARE_FRACTION_RE.search(title or "")
    if m:
        return m.group(1)
    return extract_card_number(title or "")


def load_rows(csv_path: Path | None = None) -> list[dict]:
    """`demand_market.csv` を読む。 無ければ空 list (= 走らない扱いは呼出側の判断)."""
    path = csv_path or CSV_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if any((row or {}).values())]


def build_keywords(rows: list[dict], prefix: str = PREFIX) -> list[str]:
    """和名 + 番号 の両方を語にする (純関数)。 重複は落とす。 番号は必ずある前提."""
    seen: list[str] = []
    for r in rows:
        number = (r.get("番号") or "").strip()
        name = (r.get("和名") or "").strip()
        for term in (f"{prefix} {name}" if name else None,
                     f"{prefix} {number}" if number else None):
            if term and term not in seen:
                seen.append(term)
    return seen


def build_cost_limits(rows: list[dict]) -> dict[str, int]:
    """番号 → 上限仕入れ値(円) の表。 番号は demand_keywords.extract_card_number と
    同じ表記 (例 "020/M-P" "OP08-106") で揃っているので、 候補側もこの関数で
    抜いた番号をそのまま key にして引ける。
    """
    out: dict[str, int] = {}
    for r in rows:
        number = (r.get("番号") or "").strip()
        limit = (r.get("上限仕入れ値(円)") or "").strip()
        if number and limit:
            try:
                out[number] = int(float(limit.replace(",", "")))
            except ValueError:
                continue
    return out


def judge_cost(title: str, cost_jpy: int | None, limits: dict[str, int]) -> str:
    """候補 1 件の仕入原価が上限内かを判定する (純関数).

    番号が候補タイトルから抜けない / 一覧に該当が無い / 価格不明 のいずれかは
    判定できないので "" (空欄) を返す。**落とさず残す**のが依頼の要件なので、
    判定できない事と超過している事を混同しない。
    """
    number = extract_number(title)
    limit = limits.get(number)
    if limit is None or cost_jpy is None:
        return ""
    return "上限内" if cost_jpy <= limit else "超過"


# ---------------------------------------------------------------------------
# カードごとの上限仕入れ値の門 (2026-09-20 user 確定 / HQ 依頼 treasure_new_targets)
# ---------------------------------------------------------------------------
# 「上限仕入れ値」は HQ が eBay 実売中央値から pricing_engine で逆算した値。 自前で計算しない。
# 上限ぴったりで切ると 8% しか残らないので上振れを許す。 ただし13倍の差は埋まらない。
#   仕入値 <= 上限 + 7,000  かつ  仕入値 <= 上限 x 1.5   (厳しい方が効く)
CARD_LIMIT_MARGIN_JPY = 7000
CARD_LIMIT_MARGIN_RATIO = 1.5


def card_cost_ok(title: str, cost_jpy: int | None, limits: dict[str, int]) -> bool:
    """カードごとの上限の門 (純関数). 通してよければ True.

    番号が読めない / 一覧に無い / 価格不明 は **この門では落とさない**
    (¥70,000 の門だけが効く = 従来どおり)。
    """
    limit = limits.get(extract_number(title))
    if limit is None or cost_jpy is None:
        return True
    return cost_jpy <= min(limit + CARD_LIMIT_MARGIN_JPY, limit * CARD_LIMIT_MARGIN_RATIO)
