# -*- coding: utf-8 -*-
"""既存メンテの残り6ボタンに「押したら何件動くか」を出す配線の回帰テスト (2026-09-01).

ユーザー「ボタンが増えてきて、何をしたらいいのかわからない」。
40個中ヒントが在るのは9個だけで、既存メンテの6個 (PSA 再仕入れ ① 探す / RESTOCK Revise CSV /
RESTOCK状態同期 / 補URL件数感 / 一番くじ補充①②) は説明も件数も無かった。

出す数字は **押したら今すぐ動く件数だけ** (ユーザー決定。0件なら黒のまま)。
"""
import io
import os
import sys

import pytest

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_TOOLS = os.path.join(_ROOT, "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

_DEF = chr(10) + "def "


def _src(*parts):
    return io.open(os.path.join(_ROOT, *parts), encoding="utf-8").read()


def _panel_src():
    return _src("iMakHQ", "control_panel.py")


def _fn_body(src, name):
    i = src.index("def " + name)
    j = src.find(_DEF, i + 10)
    return src[i:j if j > 0 else len(src)]


SIX = [
    ("PSA 再仕入れ ① 探す", "psa_gate", "pg_txt"),
    ("PSA 再仕入れ ② CSV", "restock_build", "rb_txt"),
    ("PSA 再仕入れ ③ 確認", "restock_wb", "rw_txt"),
    ("補URL 件数感 (全系統)", "hoju_status", "hs_txt"),
    ("くじ 再仕入れ ① 目視", "kuji_supply", "kv_txt"),
    ("くじ 再仕入れ ② CSV", "kuji_refresh", "kr_txt"),
]


@pytest.mark.parametrize("label,badge,var", SIX)
def test_six_buttons_have_tip_and_badge(label, badge, var):
    src = _panel_src()
    i = src.index(label + chr(34))
    blk = src[i:i + 900]
    assert chr(34) + "tip" + chr(34) + ":" in blk, label + " にヒント (tip) が無い"
    assert chr(34) + "badge" + chr(34) + ": " + chr(34) + badge in blk, label + " に badge が無い"


@pytest.mark.parametrize("label,badge,var", SIX)
def test_badge_kind_is_wired_to_hint_text(label, badge, var):
    """badge を付けただけでは空欄になる。by_kind に文言が入っているか。"""
    src = _panel_src()
    assert chr(34) + badge + chr(34) + ": " + var in src, "by_kind に " + badge + " の文言が無い"


def test_status_button_never_turns_blue():
    """補URL件数感 は **見るだけ**。押しても何も変わらないので色を変えない。"""
    src = _panel_src()
    i = src.index("act_kind = {")
    blk = src[i:src.index("except Exception as e:", i)]
    assert chr(34) + "hoju_status" + chr(34) not in blk, "見るだけのボタンを青にしてはいけない"
    for _l, badge, _v in SIX:
        if badge == "hoju_status":
            continue
        assert chr(34) + badge + chr(34) in blk, badge + " の青条件が無い"


def test_badge_subprocess_counts_the_new_tools():
    """数える側 (subprocess) に3本足りていること + RESTOCK確定 を2回読まないこと。"""
    src = _panel_src()
    for mod in ("psa_resource_gate", "psa_restock_build", "psa_restock_writeback"):
        assert "import " + mod in src, mod + " を数えていない"
    assert src.count("_rt('RESTOCK確定')") == 1, "RESTOCK確定 は1回だけ読んで両方に渡すこと"


def test_restock_psa10_candidates_is_shared_by_both_callers():
    """絞り込みの真理表は1つ (CSVを書く側と件数を数える側で条件がズレない)。"""
    import mercari_psa_resource as mp
    rows = [
        {"flags": "RESTOCK", "title": "PSA 10 Pokemon Japanese Pikachu", "watch": "2"},
        {"flags": "RESTOCK", "title": "PSA 10 Pokemon Japanese Eevee", "impr_total": "500"},
        {"flags": "OUT_OF_STOCK|CULL", "title": "PSA 10 Pokemon Japanese Mew", "watch": "9"},
        {"flags": "RESTOCK", "title": "UNIQLO UT Tee", "watch": "9"},
    ]
    allrows, cands = mp.restock_psa10_candidates(rows)
    assert len(allrows) == 2
    assert [r["title"] for r in cands] == ["PSA 10 Pokemon Japanese Pikachu"], (
        "実需 (実売/watch/organic impr) が無い行は候補にしない")
    assert _src("iMakHQ", "tools", "mercari_psa_resource.py").count(
        "restock_psa10_candidates(") >= 2, "CSV生成側もこの関数を通すこと"


def test_restock_build_counts_only_unlisted():
    import psa_restock_build as RB
    rows = [["itemID", "最安¥", "仕入URL", "RESTOCK状態"],
            ["111", "1000", "u1", "実行済(qty復活)"],
            ["222", "2000", "u2", ""],
            ["333", "3000", "u3", "入稿待ち(qty=0)"],
            []]
    assert RB.count_workload(rows) == {"actionable": 2, "done": 1, "total": 3}


def test_restock_writeback_counts_rows_not_done():
    import psa_restock_writeback as RW
    rows = [["itemID", "RESTOCK状態"],
            ["111", "実行済(qty復活)"],
            ["222", ""],
            ["333", "状態不明(要確認)"],
            ["", "実行済(qty復活)"]]
    assert RW.pending_rows_from_confirmed(rows) == (2, 1)
    assert RW.count_workload(rows)["actionable"] == 2


def test_count_workload_never_calls_ebay():
    """表示のために eBay API を使わない (2026-08-24 に取下げが5時間止まった実害)。"""
    for f in ("psa_restock_build.py", "psa_restock_writeback.py", "psa_resource_gate.py"):
        body = _fn_body(_src("iMakHQ", "tools", f), "count_workload")
        for bad in ("fetch_listing_qty", "GetItem", "_scrape", "webdriver"):
            assert bad not in body, f + " の count_workload が " + bad + " を呼んでいる"


def test_gate_count_is_silent_when_sheet_unreadable():
    """スプシが読めない時に「全部が新規」と多めに言わない (青が出っぱなしになる)。"""
    body = _fn_body(_src("iMakHQ", "tools", "psa_resource_gate.py"), "count_workload")
    assert chr(34) + "actionable" + chr(34) + ": 0" in body, "スプシ未読の時は actionable=0"


def test_ichibankuji_count_has_supply_and_refresh():
    body = _fn_body(_src("iMakHQ", "tools", "ichibankuji_restock.py"), "count_workload")
    q = chr(34)
    assert q + "supply" + q in body and q + "refresh" + q in body, "①②の件数を返していない"
    assert "get_oos_ichibankuji" in body and "_load_confirmed" in body
