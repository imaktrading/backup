"""uniqlo_catalog_terms - カタログの **公式売り切れ UT** から メルカリの検索語を作る.

2026-09-11 新設 (Advisor 依頼 `2026-09-11_ut_catalog_link_poc`, [IMPLEMENT-GO])。
user の目的: 「公式ではなく、 メルカリから **公式では買えない新品未使用** を出品する」。
なので **公式で売り切れた UT のコラボ名** で引く。

★KEY (AI列) は付けない。 目視で確定する (user 判断 2026-09-11「PSA と同じように目視で」)。
  ここで作るのは **検索語** と、 目視の材料にする **見つけた語** だけ。
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict

DB_PATH = r"C:/dev/iMak_data/catalog/products.sqlite"

# 汎用すぎて検索語にならない / 扱わない
_GENERIC = {"", "その他", "UT", "ユニクロ", "UNIQLO"}
# 検索の邪魔になる飾り (「ピーナッツ（UT）」→「ピーナッツ」)
_SUFFIX_RE = re.compile(r"[（(]\s*UT\s*[)）]|UTGP\s*\d{4}\s*[:：]?")
_SPLIT_RE = re.compile(r"\s*[/／]\s*")


def clean_term(collab: str) -> list[str]:
    """コラボ名 -> 検索語 (複数に割れることがある). 使えなければ空リスト.

    例:
      「ピーナッツ（UT）」 -> ["ピーナッツ"]
      「アンディ・ウォーホル / ジャン＝ミシェル・バスキア / キース・ヘリング（UT）」
        -> ["アンディ・ウォーホル", "ジャン＝ミシェル・バスキア", "キース・ヘリング"]
    """
    t = _SUFFIX_RE.sub("", collab or "").strip()
    if t in _GENERIC:
        return []
    out = []
    for part in _SPLIT_RE.split(t):
        p = part.strip(" 　:：")
        if len(p) >= 2 and p not in _GENERIC:
            out.append(p)
    return out


def sold_out_collabs(db_path: str = DB_PATH) -> dict[str, list[str]]:
    """公式売り切れの UT Tシャツ -> {コラボ名: [product_id, ...]}.

    条件 (依頼書どおり): not_tee でない / official_gone_at が無い / sold_out_since がある。
    """
    out: dict[str, list[str]] = defaultdict(list)
    con = sqlite3.connect(db_path)
    try:
        for pid, specs in con.execute(
                "select product_id, specs from products where category='uniqlo_ut'"):
            try:
                s = json.loads(specs or "{}")
            except Exception:  # noqa: BLE001
                continue
            if s.get("not_tee") or s.get("official_gone_at") or not s.get("sold_out_since"):
                continue
            out[s.get("collab") or ""].append(pid)
    finally:
        con.close()
    return dict(out)


def build_terms(limit: int = 0, excluded=None, db_path: str = DB_PATH) -> list[dict]:
    """検索語を **売り切れ商品の多い順** に作る.

    excluded: タイトル判定の関数 (True なら捨てる)。 サンリオ等の出せない区分を落とす。
    Returns: [{"term", "collab", "product_ids"}]
    """
    seen: set[str] = set()
    terms: list[dict] = []
    for collab, pids in sorted(sold_out_collabs(db_path).items(),
                               key=lambda kv: -len(kv[1])):
        for term in clean_term(collab):
            if term in seen:
                continue
            if excluded and excluded(term):
                continue
            seen.add(term)
            terms.append({"term": term, "collab": collab, "product_ids": pids})
    return terms[:limit] if limit else terms


def query_for(term: str) -> str:
    """メルカリの検索語. 「ユニクロ」を足して 他社のTに埋もれないようにする."""
    return f"ユニクロ {term} Tシャツ"
