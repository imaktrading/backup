# -*- coding: utf-8 -*-
"""2026-09-14 窓口で処理した依頼のうち、HQ 側のコードで直した2件の見張り。

1. UT の特定候補に、ファッション記事から拾ったデザイン行 (fp_design / not_for_listing) を出さない
   (catalog 依頼 hq/requests/2026-09-13_ut_fp_design_rows_key_notice)。
   commerce の値 (素材・原産国・実寸) を持たないので、特定できても写す値が何も無い出品になる。

2. OPCG 月次取得の検査で、Ultra Prism の空欄化 tag の期待値を 327 → 0 にする
   (catalog 依頼 catalog/requests/2026-09-13_scheduled_checks_not_acted_on)。
   327件はその後の是正で正しい値に埋め直され、tag の行は 0件 (catalog 実測)。
   期待値が古いと、月次の取得のたびに「件数が動いた = 異常」として巻き戻す。
"""
import io
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, _TOOLS)


def _src(name):
    return io.open(os.path.join(_TOOLS, name), encoding="utf-8").read()


def test_fp_designの行はUT特定の候補に出さない():
    src = _src("ut_identify.py")
    body = src[src.index("def load_catalog("):]
    body = body[:body.index("\ndef ", 1)]
    assert 's.get("not_for_listing") is True' in body
    assert 's.get("data_level") == "fp_design"' in body
    # region_only と同じ入口で弾いている (候補を作る前)
    assert body.index("not_for_listing") > body.index("region_only")


def test_ultra_prism空欄化tagの期待値は0():
    import opcg_dump_refresh as R
    assert R.INVARIANTS["blanked_by_ultra_prism_mismap_20260731"] == 0


def test_他の2つの期待値は変えていない():
    """変えたのは実測で動いていた1つだけ (21 / 76 は実測でも一致)。"""
    import opcg_dump_refresh as R
    assert R.INVARIANTS["filter_map_backfill_20260801"] == 21
    assert R.INVARIANTS["filter_map_restamp_20260801"] == 76


def test_フラグの無いfashion_press行も情報源で弾く(tmp_path):
    """フラグだけに頼ると漏れる (実例 FP-102598 / FP-143930 / FP-143792 は両フラグ無し)。

    文言ではなく**振る舞い**で見る: 普通の商品だけが候補に残ること。
    """
    import json
    import sqlite3
    import ut_identify as U
    db = tmp_path / "p.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table products (category, product_id, name, specs, images, source)")
    rows = [
        ("E1", {"gender": "MEN", "collab": "ポケモン"}, "uniqlo_official_api"),             # 普通の商品
        ("FP-1", {"collab": "ポケモン"}, "fashion_press_143930"),                          # フラグ無しの記事行
        ("FP-2", {"collab": "ポケモン", "not_for_listing": True}, "fashion_press_2"),      # フラグ付きの記事行
        ("E2", {"gender": "MEN", "collab": "ポケモン", "data_level": "fp_design"}, "x"),  # data_level だけ
    ]
    for pid, spec, src in rows:
        con.execute("insert into products values ('uniqlo_ut', ?, 'ポケモン UT', ?, '[]', ?)",
                    (pid, json.dumps(spec), src))
    con.commit()
    con.close()
    assert {p["pid"] for p in U.load_catalog(str(db))} == {"E1"}


def test_表のセルは縦棒と改行を壊さない():
    import pdca_store as P
    assert P._md_cell("083/062 | Chili\nSv3a") == "083/062 ｜ Chili Sv3a"
    assert P._md_cell("abcdef", 3) == "abc"
    assert P._md_cell(None) == ""


def test_identityに縦棒があっても列数が崩れない():
    """catalog が列境界を読み違えた実例 (identity に生の | が入っていた)。"""
    import pdca_store as P
    rows = P._queue_table([{
        "priority": 5.0, "item_id": "m11172088185",
        "identity": "083/062 | Chili | Sv3a: Raging Surf | Japanese",
        "target_field": "name_en", "suggested_value": "Rika", "confidence": 1.0,
        "evidence": "PSA Subject='RIKA SUPER' の語が CSV の C:Character と一致しない | 詳細あり",
    }])
    header_cols = rows[0].count("|")
    assert all(r.count("|") == header_cols for r in rows[1:]), rows
