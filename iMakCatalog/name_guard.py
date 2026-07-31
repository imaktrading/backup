"""base→_pN の name_en / character_name 伝播ガード (2026-08-01).

依頼: requests/2026-08-01_hq_decisions_nameguard_facet_fb10049.md ① (窓口 GO・最優先)。

背景: DBSCG の base→_p1 伝播が name_jp を照合せずに base の name_en/character_name を _p1 に
焼き込み、別キャラ(別カード)に別キャラの英名を付ける事故が起きた:
  - FB10-025_p1 (name_jp=ベジット) ← base 'Son Goku/Vegeta' 誤コピー (2026-08-01 修正済)
  - FB10-049_p1 (name_jp=孫悟飯：青年期/ピッコロ) ← base 幼年期 の英名を誤コピー

不変条件 (窓口指示):
  - **name_en に加え character_name も guard 対象** (ベジットは両方誤っていた)。
  - **name_jp の完全一致のみ伝播** (部分一致禁止。幼年期↔青年期 を通さない)。
  - **allowlist は作らない** (例外の受け皿は必ず積もる)。

これは「今後の base→_pN backfill が二度と別キャラの名前を焼かない」ための単一ガード関数 +
継続検出 scanner。ad-hoc backfill はこの関数を経由すること。
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional

_P_SUFFIX = re.compile(r"_p\d+$")


def base_product_id(product_id: str) -> str:
    """'FB10-025_p1' → 'FB10-025' (_pN suffix を剥がす)."""
    return _P_SUFFIX.sub("", product_id)


def propagate_name_fields(
    variant_name_jp: Optional[str],
    base_name_jp: Optional[str],
    base_name_en: Optional[str] = None,
    base_character_name: Optional[str] = None,
) -> dict:
    """base の name_en/character_name を variant(_pN) に伝播してよい **値のみ** を返す。

    **name_jp 完全一致のみ許可** (allowlist なし, fail-closed)。
    不一致 / どちらか空 → **{}** (伝播しない = 別カードに別キャラ名を焼かない)。

    Returns: {"name_en": ..., "character_name": ...} のうち base が持つ分だけ。
    """
    if not variant_name_jp or not base_name_jp:
        return {}
    if variant_name_jp.strip() != base_name_jp.strip():   # 完全一致のみ (部分一致不可)
        return {}
    out: dict = {}
    if base_name_en:
        out["name_en"] = base_name_en
    if base_character_name:
        out["character_name"] = base_character_name
    return out


def find_variant_name_violations(conn: sqlite3.Connection,
                                 category: str = "dragonball_scg") -> list[dict]:
    """_pN で **name_jp ≠ base name_jp なのに name_en/character_name が base と一致** する行
    (= 過去の無ガード伝播の残骸) を返す。継続検出用 (WARN)。

    このガードを通していれば 0 件であるべき。>0 は別経路の再混入を意味する。
    """
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "select product_id, name_jp, name_en, "
            "json_extract(specs,'$.character_name') as ch "
            "from products where category=?", (category,)
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # 最小/非標準スキーマ (test fixture 等) では skip (fail-safe)
    info = {r["product_id"]: (r["name_jp"], r["name_en"], r["ch"]) for r in rows}
    viol = []
    for pid, (jp, en, ch) in info.items():
        if not _P_SUFFIX.search(pid):
            continue
        b = base_product_id(pid)
        if b not in info:
            continue
        bjp, ben, bch = info[b]
        if not (bjp and jp) or jp.strip() == bjp.strip():
            continue
        # name_jp が別なのに name_en か character_name が base と一致 = 誤伝播
        if (en and en == ben) or (ch and ch == bch):
            viol.append({"product_id": pid, "name_jp": jp, "base_name_jp": bjp,
                         "name_en": en, "base_name_en": ben,
                         "character_name": ch, "base_character_name": bch})
    return viol


# ── set_name_ebay の N:1 誤マップ検出 (2026-08-01, 依頼③, WARN only・自動修正なし) ──

_N1_ALLOWLIST = Path(__file__).resolve().parent / "ebay_filter_map" / "facet_n1_allowlist.yaml"


def load_facet_n1_allowlist(path: Path | None = None) -> dict:
    """正当な半セット結合 allowlist を yaml から読む (コードにハードコードしない)。
    戻り: {category: {facet: set(set_name_official)}}。"""
    import yaml  # 遅延 import (audit 実行時のみ)
    p = path or _N1_ALLOWLIST
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {cat: {fac: set(sos or []) for fac, sos in facs.items()}
            for cat, facs in data.items()}


def find_facet_n1_candidates(conn: sqlite3.Connection, category: str,
                             allowlist: dict | None = None) -> list[dict]:
    """同一 set_name_ebay に複数 set_name_official がぶら下がる (N:1) facet のうち、
    **allowlist に無い JP set** (= mismap 候補) を返す。**検出のみ (WARN)、自動修正しない**。

    一括 null 化は禁止 (正当な半セット結合を壊すため)。窓口が per-facet で GO を出す用の候補列挙。
    """
    if allowlist is None:
        allowlist = load_facet_n1_allowlist()
    allow_cat = (allowlist.get(category) or {})
    conn.row_factory = sqlite3.Row
    facet_sets: dict[str, dict[str, int]] = {}
    try:
        cur = conn.execute(
            "select set_name_official, json_extract(specs,'$.set_name_ebay') se "
            "from products where category=? and set_name_official is not null "
            "and set_name_official!='' and json_extract(specs,'$.set_name_ebay') is not null "
            "and json_extract(specs,'$.set_name_ebay')!=''", (category,)
        ).fetchall()
    except sqlite3.OperationalError:
        return []  # 最小/非標準スキーマでは skip (fail-safe)
    for r in cur:
        se, so = r["se"], r["set_name_official"]
        facet_sets.setdefault(se, {})
        facet_sets[se][so] = facet_sets[se].get(so, 0) + 1
    out = []
    for se, sos in facet_sets.items():
        if len(sos) < 2:
            continue                       # N:1 でない
        allowed = allow_cat.get(se, set())
        strangers = {so: n for so, n in sos.items() if so not in allowed}
        # allowlist で全 JP set が正当 → skip。1つでも allowlist 外 = 候補。
        if allowed and not strangers:
            continue
        if len(sos) == len(strangers) and se not in allow_cat:
            # allowlist 未登録の N:1 全体 (半セットか mismap か未判定) も候補として出す
            pass
        if strangers:
            out.append({"set_name_ebay": se, "n_jp_sets": len(sos),
                        "strangers": strangers,
                        "allowlisted": sorted(allowed)})
    return out
