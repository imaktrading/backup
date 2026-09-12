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
DEMAND_PATH = r"C:/dev/iMak_data/harvest/ut_demand_words.json"

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


# アニメ・漫画の目印 (2026-09-13 user 確定「アニメ・漫画系が欲しい」)。
# 商品名 / コラボ名 / character_family / 説明文 のどれかに出れば該当とみなす
ANIME_WORDS = (
    "ワンピース", "ONE PIECE", "鬼滅", "呪術", "ドラゴンボール", "NARUTO", "ナルト",
    "スパイファミリー", "SPY", "チェンソーマン", "進撃", "ハイキュー", "銀魂", "ジョジョ",
    "キングダム", "ジャンプ", "MANGA", "ポケモン", "スラムダンク", "コナン", "ガンダム",
    "エヴァ", "ダンダダン", "ベルセルク", "ハンター", "セーラームーン", "ヒロアカ",
    "東京リベンジャーズ", "アニメ", "少年",
)


def is_anime(specs: dict, name: str = "") -> bool:
    """アニメ・漫画のコラボか (カタログの値だけで判定)."""
    text = " ".join(str(specs.get(k) or "") for k in
                    ("collab", "character_family", "long_description")) + " " + (name or "")
    return any(w in text for w in ANIME_WORDS)


def sold_out_collabs(db_path: str = DB_PATH, include_gone: bool = True,
                     only_anime: bool = False) -> dict[str, list[str]]:
    """公式で **買えない** UT Tシャツ -> {コラボ名: [product_id, ...]}.

    include_gone=True (既定): **公式から消えた商品も含む** (2026-09-13 user 確定)。
      UT は発売から数ヶ月でページごと消えるため、 「売り切れだが公式に残っている物」だけに
      絞ると アニメ・漫画がほとんど残らない (実測: 341件中ごく一部しか見えなかった)。
    only_anime=True: アニメ・漫画のコラボだけ。
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
            if s.get("not_tee"):
                continue
            gone = bool(s.get("official_gone_at"))
            if not gone and not s.get("sold_out_since"):
                continue                      # 公式でまだ買える = 対象外
            if gone and not include_gone:
                continue
            if only_anime and not is_anime(s, ""):
                continue
            out[s.get("collab") or ""].append(pid)
    finally:
        con.close()
    return dict(out)


def _demand_scores(path: str = DEMAND_PATH) -> dict[str, int]:
    """`ut_demand_words.json` の collab_jp -> score. 無い/壊れていれば空."""
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except Exception:  # noqa: BLE001
        return {}
    return {w["collab_jp"]: w.get("score", 0)
            for w in data.get("works", []) if w.get("collab_jp")}


def build_terms(limit: int = 0, excluded=None, db_path: str = DB_PATH,
                demand_path: str = DEMAND_PATH, include_gone: bool = True,
                only_anime: bool = False) -> list[dict]:
    """検索語を作る。 **売れている作品 (score 降順) を先に**、 それ以外は売り切れ商品の多い順.

    excluded: タイトル判定の関数 (True なら捨てる)。 サンリオ等の出せない区分を落とす。
    demand_path が無い/壊れていれば従来どおり件数順のまま (止めない)。
    include_gone / only_anime は `sold_out_collabs` と同じ意味 (2026-09-13 user 確定)。
    Returns: [{"term", "collab", "product_ids"}]
    """
    seen: set[str] = set()
    terms: list[dict] = []
    for collab, pids in sorted(sold_out_collabs(db_path, include_gone, only_anime).items(),
                               key=lambda kv: -len(kv[1])):
        for term in clean_term(collab):
            if term in seen:
                continue
            if excluded and excluded(term):
                continue
            seen.add(term)
            terms.append({"term": term, "collab": collab, "product_ids": pids})
    scores = _demand_scores(demand_path)
    scored = sorted([t for t in terms if t["term"] in scores], key=lambda t: -scores[t["term"]])
    unscored = [t for t in terms if t["term"] not in scores]
    terms = scored + unscored
    return terms[:limit] if limit else terms


def query_for(term: str) -> str:
    """メルカリの検索語. 「ユニクロ」を足して 他社のTに埋もれないようにする."""
    return f"ユニクロ {term} Tシャツ"
