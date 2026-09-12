# -*- coding: utf-8 -*-
"""UT の探索結果を **置き場を間違えて** 保存していた (2026-09-13)。

`search(sold_out=True)` (再仕入れ) の最後の保存が `save_cache(cache)` = 置き場の指定なし
だった。既定は **補URL用** なので、再仕入れを回すたびに補URL用のキャッシュが丸ごと
上書きされ、中身が全部「売り切れた行」になっていた。
補URL の目視 (`confirm`) は出品中の行しか見ないので **毎回 0件**。

実測 2026-09-13: 補URL用 36件が全部 売切の行 / `confirm` の目視できる UT = 0件。
(再仕入れ側は 4件 出ていたので、壊れていたのは補URLの線だけ)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_hoju_fill as U  # noqa: E402


def test_two_caches_are_different_files():
    assert U.CACHE_PATH != U.RESTOCK_CACHE_PATH
    assert U._cache_path(False) == U.CACHE_PATH
    assert U._cache_path(True) == U.RESTOCK_CACHE_PATH


def test_search_never_saves_without_a_path():
    """置き場を指定しない保存が1つでも残っていたら、また混ざる。"""
    import io
    src = io.open(ROOT / "iMakHQ" / "tools" / "ut_hoju_fill.py", encoding="utf-8").read()
    i = src.index("def search(")
    body = src[i:src.index("\ndef ", i + 1)]
    code = "\n".join(ln for ln in body.split("\n") if not ln.strip().startswith("#"))
    assert "save_cache(cache)" not in code, "置き場なしの保存が残っている (補URL用を上書きする)"
    assert code.count("save_cache(cache, _cache_path(sold_out))") >= 2


def test_aux_confirm_only_looks_at_live_rows():
    """補URL は **出品中** の行だけ。売り切れた行が混ざると 0件になる (今回の症状)。"""
    rows = [
        [""] * 40,
        _row(item_id="358000000001", sold="", aux=0),
        _row(item_id="358000000002", sold="○", aux=0),
    ]
    got = {t["itemID"] for t in U.select_targets(rows)}
    assert got == {"358000000001"}
    got_sold = {t["itemID"] for t in U.select_targets(rows, sold_out=True)}
    assert got_sold == {"358000000002"}


def _row(item_id, sold, aux):
    import sheet_io
    r = [""] * 40
    r[0] = "https://jp.mercari.com/item/m12345678901"
    r[sheet_io.PRODUCT_COL_ITEMID] = item_id
    r[2] = "UNIQLO UT テスト L"
    r[3] = sold
    r[sheet_io.PRODUCT_COL_CATEGORY] = "Tシャツ"
    for k in range(aux):
        r[sheet_io.PRODUCT_COL_AUX_START + k] = f"https://jp.mercari.com/item/m9999999999{k}"
    return r
