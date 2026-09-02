# -*- coding: utf-8 -*-
"""棚のENDルールを実測から決め直した (2026-09-02)。

金額枠が97%埋まり、何を落とすかを決める必要が出た。生存分析
(売れた分だけでなく **まだ売れていない在庫も母数に入れる**) で、
年齢別に「その先90日で売れる割合」を出した結果:

  TCG      0日〜4.34%(369) / 30日〜0.84%(239) / 60日〜0.00%(104)
           売れた実績の最長は49日。ウォッチ/クリック/表示のどれで切っても
           30日超は全区分0% (ウォッチ261件・クリック761件で確認) = 4方向から同じ答え
  G-shock  0日〜1.78% / 90日〜0.41% / 180日〜0.87% / 270日〜1.32% / 365日〜0.00%(96)
           中央値284日で売れる。**30日で落としてはいけない**。365日超だけ0件
  他       分母20〜70件で0〜8%を行き来し、線を引けるデータが無い → 触らない

途中で採らなかった案 (前向き検証で落ちたもの):
  ・ウォッチで判定  → 期間を分けると順序が逆転 (0日〜0.59% / 1日〜0.00% / 2以上1.54%)
  ・表示量で判定    → 相関なし (1000-4999で1.28% / 5000以上で1.14%)
  ・価格帯で判定    → 信頼区間が重なる
  ・クリック10回以上 → 該当4件が全部UNIQLOで、カテゴリの言い換えだった
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import shelf_evict as SE  # noqa: E402


def _row(iid="1", qty=1, sold=0, age=100, impr=0, price=100.0, watch=0):
    return {"item_id": iid, "qty": qty, "sold_qty": sold, "sales90": 0,
            "age_days": age, "impr_total": impr, "price": price, "watch": watch}


def test_thresholds_are_per_category():
    """一律の日数にしない。カテゴリで30倍ちがう。"""
    assert SE.STALE_MAX_AGE == {"TCG": 30, "G-shock": 365}


def test_tcg_dies_at_30_days():
    assert SE.tier_of(_row(age=29), category="TCG") is None
    assert SE.tier_of(_row(age=31), category="TCG") == SE.TIER_STALE


def test_gshock_survives_until_365():
    """G-shock は中央値284日で売れる。30日や90日で落とすと売れる在庫を捨てる。"""
    for age in (31, 100, 200, 300, 365):
        assert SE.tier_of(_row(age=age), category="G-shock") is None, "%d日で落としている" % age
    assert SE.tier_of(_row(age=366), category="G-shock") == SE.TIER_STALE


def test_other_categories_are_never_dropped_by_age():
    """線を引けるデータが無いカテゴリは触らない (Tシャツは365日超が最も売れる)。"""
    for cat in ("Tシャツ", "フィギュア", "モンベル", "バッグ", None):
        assert SE.tier_of(_row(age=9999), category=cat) is None


def test_sold_before_is_always_kept():
    """一度売れたものは14倍売れやすい (11.11% vs 0.77%)。年齢を問わず残す。"""
    assert SE.tier_of(_row(age=9999, sold=1), category="TCG") is None


def test_out_of_stock_is_all_categories():
    """買えないものはどのカテゴリでも落とす (年齢も見ない)。"""
    for cat in ("TCG", "G-shock", "Tシャツ", None):
        assert SE.tier_of(_row(qty=0, age=1), category=cat) == SE.TIER_OOS


def test_tier2_can_run_alone():
    """在庫ありの取下げはボタンを分ける (判断の重さが違う)。"""
    oos = _row("oos", qty=0, price=500.0)
    stale = _row("stale", age=100, price=500.0)
    picked, _ = SE.pick([oos, stale], target=10, shelf_of=lambda r: r["price"],
                        cat_of=lambda r: "TCG", only_tier=SE.TIER_STALE)
    assert [r["item_id"] for _t, r in picked] == ["stale"]
    picked2, _ = SE.pick([oos, stale], target=10, shelf_of=lambda r: r["price"],
                         cat_of=lambda r: "TCG", only_tier=SE.TIER_OOS)
    assert [r["item_id"] for _t, r in picked2] == ["oos"]


def test_candidate_csv_has_what_a_human_needs():
    """CSVだけで判断できること (ユーザー指示: 価格・経過日数・VIEW・WATCH)。"""
    for col in ("価格$", "経過日数", "表示", "クリック", "ウォッチ"):
        assert col in SE.CAND_HEADER, "%s が候補CSVに無い" % col
    rows = SE.candidate_rows(
        [(SE.TIER_STALE, _row("x", age=45, impr=1500, price=242.0, watch=3))],
        shelf_of=lambda r: 1053.0, cat_of=lambda r: "TCG", clicks={"x": (2.0, 1500.0)})
    got = dict(zip(SE.CAND_HEADER, rows[0]))
    assert got["経過日数"] == 45 and got["ウォッチ"] == 3
    assert got["表示"] == 1500 and got["クリック"] == 2
    assert got["価格$"] == 242.0 and got["空く枠$"] == 1053


def test_review_tool_exists_for_revisiting_the_line():
    """線は固定しない。四半期ごとに測り直す口があること。"""
    p = os.path.join(os.path.dirname(__file__), "..", "tools", "shelf_evict_review.py")
    assert os.path.exists(p), "見直しツールが無い"
    s = io.open(p, encoding="utf-8").read()
    assert "def conditional_rate" in s and "def wilson" in s, "区間つきで出すこと"
