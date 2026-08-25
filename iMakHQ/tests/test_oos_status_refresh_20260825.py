# -*- coding: utf-8 -*-
"""在庫なしシートの「状態」列が、取下げボタンを押した後も古いままだった (2026-08-25)。

S列はファネルを回した時点の状態で書かれる。取下げを押すと済みリストが増えるので、
**押した瞬間からシートが嘘になる**。実際に 122件 落とした直後、その122行が
「🗑 取下げ 未 (次回の対象)」のまま残っていた。

→ 取下げボタンの最後に S列を実態へ戻す。材料は funnel CSV と 済み台帳だけで eBay は叩かない。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import oos_status_refresh as R  # noqa: E402

_CSV = ("item_id,title,site,price,age_days,flags\n"
        "111,Porter Bag,US,189,90,OUT_OF_STOCK|CULL\n"
        "222,G-Shock,US,251,90,OUT_OF_STOCK|RESTOCK\n"
        "333,Tee,US,38,90,OUT_OF_STOCK|CULL\n")


def _csv(tmp_path):
    p = tmp_path / "funnel_20260825.csv"
    p.write_text(_CSV, encoding="utf-8")
    return str(p)


def test_ended_row_becomes_done(tmp_path):
    m = R.build_status_map(_csv(tmp_path), done_ids={"111"})
    assert m["111"] == "🗑 取下げ 済"
    assert m["222"] == "🛒 在庫切れ (戻す口が無い)"   # G-Shock = 戻す仕組みが無い
    assert "取下げ 未" in m["333"]        # $100未満で対象外のまま


def test_plan_only_touches_changed_rows(tmp_path):
    m = R.build_status_map(_csv(tmp_path), done_ids={"111"})
    sheet = [["item_id"] + [""] * 17 + ["状態"],
             ["111"] + [""] * 17 + ["🗑 取下げ 未 (次回の対象)"],   # 古い = 直す
             ["222"] + [""] * 17 + ["🛒 在庫切れ (戻す口が無い)"]]   # 合っている = 触らない
    ch = R.plan(sheet, m)
    assert ch == [(2, "🗑 取下げ 済")]


def test_row_missing_from_csv_is_left_alone(tmp_path):
    """CSV に無い行は触らない (作り話をしない)。"""
    m = R.build_status_map(_csv(tmp_path), done_ids=set())
    sheet = [["item_id"] + [""] * 17 + ["状態"],
             ["999"] + [""] * 17 + ["🛒 在庫切れ (戻す口が無い)"]]
    assert R.plan(sheet, m) == []


def test_button_refreshes_the_column():
    """取下げボタン (cull_end) が最後に状態列を直すこと。"""
    src = open(os.path.join(_TOOLS, "cull_end.py"), encoding="utf-8").read()
    assert "oos_status_refresh" in src and "main_commit" in src


def test_ended_row_shows_done_even_if_bucket_moved(tmp_path):
    """★落とした事実が最優先。

    取り下げるとスプシの B列が空になり、次の走行では仕入元URLが取れないので、同じ行が
    RESTOCK に振り直される。バケツで先に判定すると、もう終わっている出品が
    「🛒 再仕入れ」に見える (実測 133件)。
    """
    p = tmp_path / "funnel_20260825.csv"
    p.write_text("item_id,title,site,price,age_days,flags\n"
                 "111,Porter Bag,US,189,90,OUT_OF_STOCK|RESTOCK\n", encoding="utf-8")
    m = R.build_status_map(str(p), done_ids={"111"})
    assert m["111"] == "🗑 取下げ 済"


# ---- 「再仕入れ」の中身を書き分ける (2026-08-25 ユーザー要望: S列のメンテ) ----

def _funnel(tmp_path, title, flags="OUT_OF_STOCK|RESTOCK"):
    p = tmp_path / "funnel_20260825.csv"
    p.write_text("item_id,title,site,price,age_days,flags\n"
                 f"111,{title},US,189,90,{flags}\n", encoding="utf-8")
    return str(p)


def test_psa10_shows_who_restocks_it(tmp_path):
    m = R.build_status_map(
        _funnel(tmp_path, "PSA 10 Pokemon Japanese Charizard #003/184"), done_ids=set())
    assert m["111"] == "🛒 再仕入れ (PSA10)"


def test_ichibankuji_shows_who_restocks_it(tmp_path):
    m = R.build_status_map(
        _funnel(tmp_path, "Ichiban Kuji One Piece A Prize Luffy"), done_ids=set())
    assert m["111"] == "🛒 再仕入れ (一番くじ)"


def test_no_owner_is_named_as_such(tmp_path):
    """戻す口が無いものを「再仕入れ」と書かない (戻る予定に見えてしまう)。"""
    m = R.build_status_map(
        _funnel(tmp_path, "CASIO G-Shock GA-B2100BEG-1AJF"), done_ids=set())
    assert m["111"] == "🛒 在庫切れ (戻す口が無い)"
