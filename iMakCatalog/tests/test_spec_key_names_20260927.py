# -*- coding: utf-8 -*-
"""specs のキー名が化けていないか (2026-09-27).

PC のブルースクリーンで **キー名の1文字が別の文字に化ける**事故が続いている。
値の化けと違って JSON としては読めるので、`test_json_columns_parse_20260924` では捕まらない。
2026-09-26 は eBay 値のテストが1件だけ赤になって初めて気づいた (4件見つかった)。

    `p_ebay        <- hp_ebay        SVI-040 / DPt4-B-040
    card_type_eba9 <- card_type_ebay
    typd_jp        <- type_jp
    compgsition    <- composition

見つけ方: **そのカテゴリで普通に使われているキーと1文字しか違わないのに、数件しか無いキー**。
新しく足した項目を誤検知しないよう、**同じカテゴリで3件以下**のものだけを見る。
"""
import collections
import difflib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api  # noqa: E402

RARE = 3        # これ以下しか無いキーが疑いの対象
COMMON = 50     # これ以上使われているキーを「正しい形」とみなす


def _suspects() -> list[tuple[str, str, str, str]]:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    rows = db.execute("SELECT category, product_id, specs FROM products").fetchall()
    db.close()
    per_cat: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    parsed = []
    for cat, pid, sp in rows:
        try:
            d = json.loads(sp or "{}")
        except Exception:
            continue          # JSON の壊れは別のテストが見る
        parsed.append((cat, pid, d))
        per_cat[cat].update(d.keys())
    out = []
    for cat, pid, d in parsed:
        cnt = per_cat[cat]
        common = [k for k, n in cnt.items() if n >= COMMON]
        for k in d:
            if cnt[k] > RARE:
                continue
            near = difflib.get_close_matches(k, common, n=1, cutoff=0.9)
            if near and len(near[0]) == len(k) and near[0] != k:
                out.append((cat, pid, k, near[0]))
    return out


def test_no_corrupted_spec_key_names():
    bad = _suspects()
    assert bad == [], (
        f"化けたキー名の疑い {len(bad)}件: {bad[:5]} "
        "(直し方: migrations/2026-09-26_fix_corrupted_spec_keys.py に1行足して走らせる)")
