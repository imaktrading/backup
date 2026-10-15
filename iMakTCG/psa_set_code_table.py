# -*- coding: utf-8 -*-
"""PSA のセット名 → セット記号 を、カタログの表 (psa_brand_set_code.yaml) で **補う** (残務 №330・2026-10-15)。

なぜ:
    PSA のセット名 (Brand) からセット記号を引く表は、カタログの引き方 (integrations/psa_to_csv.py の
    extract_set_code_from_brand*) にコードで直書きされていて、表に無いセット名は引けず出品されない
    (2026-09-22 時点で 64種。例 メタモンV S4a-323 `SWORD & SHIELD SHINY STAR V`)。
    カタログが 9/22 に表を yaml で作った (依頼 catalog/requests/2026-09-22_psa_brand_set_code_table.md)。

決まり (ユーザー判断 2026-09-22 / 2026-10-15「修正が修正を生まないように」):
    - 引き方は変えない。**今のコードが引けなかった (None) 時だけ** 表を見る → 今引けている物の結果は変わらない
    - 表の status が `ok` で set_codes が1つの時だけ使う。multi / not_in_catalog / out_of_scope は今までどおり None
    - 表が読めなければ何もしない (今までどおり)
"""
from __future__ import annotations

import os

TABLE_PATH = r"C:/dev/iMak_data/catalog/psa_brand_set_code.yaml"
# カタログの引き方の関数名 → 表のカテゴリ
_FUNCS = {
    "extract_set_code_from_brand": "one_piece_tcg",
    "extract_set_code_from_brand_pokemon": "pokemon_tcg",
    "extract_set_code_from_brand_gundam": "gundam_tcg",
    "extract_set_code_from_brand_dragonball": "dragonball_scg",
}
STATS = {"filled": 0}          # 走行で表から補った回数 (走行ログ用)


def _norm(s):
    return " ".join(str(s or "").upper().split())


def load_table(path=None):
    """{category: {PSA セット名 (大文字・空白詰め): set_code}} — status ok かつ1つの物だけ。読めなければ {}。"""
    try:
        import yaml
        with open(path or TABLE_PATH, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
    except Exception:                                          # noqa: BLE001 読めなければ今までどおり
        return {}
    out = {}
    for cat, rows in (d or {}).items():
        if not isinstance(rows, list):
            continue
        m = out.setdefault(cat, {})
        for r in rows:
            codes = (r or {}).get("set_codes") or []
            if (r or {}).get("status") == "ok" and len(codes) == 1 and r.get("psa_brand"):
                m[_norm(r["psa_brand"])] = str(codes[0])
    return out


def wrap(fn, table_for_cat):
    """引き方 fn が None を返した時だけ、表の値を返す関数 (純関数)。"""
    def wrapped(brand, *a, **k):
        got = fn(brand, *a, **k)
        if got:
            return got
        hit = table_for_cat.get(_norm(brand))
        if hit:
            STATS["filled"] += 1
            print(f"    📗 セット記号を表から補った: {brand} → {hit} (psa_brand_set_code.yaml)")
        return hit or got
    wrapped._imak_set_table = True
    return wrapped


def install(catalog_psa, path=None):
    """カタログの引き方のモジュールに、表での補いを付ける (何度呼んでも1回だけ)。付けた関数の数を返す。"""
    table = load_table(path)
    if not table:
        return 0
    n = 0
    for name, cat in _FUNCS.items():
        fn = getattr(catalog_psa, name, None)
        if fn is None or getattr(fn, "_imak_set_table", False) or not table.get(cat):
            continue
        setattr(catalog_psa, name, wrap(fn, table[cat]))
        n += 1
    return n
