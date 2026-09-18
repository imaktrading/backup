"""market_ledger: 台帳が二重に増えないこと / カード番号が取れること。

2026-09-18 新設 (Terapeak 抜き出しの CSV を1本に溜める仕組み)。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iMakHQ", "tools"))

import market_ledger as M


def _row(item_id, title="PSA10 Psyduck AR 175/165 SV2a", sold="3", kw="PSA10 pokemon"):
    return {
        "種別": "Sold",
        "検索語": kw,
        "期間": "Jun 19, 2026 – Sep 17, 2026",
        "itemId": item_id,
        "タイトル": title,
        "売れた数": sold,
        "平均落札": "$127.78",
    }


def test_同じ出品は何度取り込んでも1行():
    rows, added, updated = M.merge([], [_row("1"), _row("2")])
    assert (added, updated, len(rows)) == (2, 0, 2)
    rows, added, updated = M.merge(rows, [_row("1", sold="5")])
    assert (added, updated, len(rows)) == (0, 1, 2)
    assert [r for r in rows if r["itemId"] == "1"][0]["売れた数"] == "5"


def test_検索語や期間が違えば別の行として溜まる():
    rows, _, _ = M.merge([], [_row("1")])
    rows, added, _ = M.merge(rows, [_row("1", kw="PSA10 one piece")])
    assert added == 1 and len(rows) == 2


def test_初めて見た日は上書きしても残る():
    rows, _, _ = M.merge([], [_row("1")], ingested_at="2026-09-18")
    rows, _, _ = M.merge(rows, [_row("1", sold="9")], ingested_at="2026-10-01")
    assert rows[0]["取込日"] == "2026-09-18"


def test_itemIdの無い行は入れない():
    rows, added, _ = M.merge([], [_row("")])
    assert (added, rows) == (0, [])


def test_カード番号の取り出し():
    assert M.card_no("PSA10 Psyduck AR 175/165 SV2a 151") == "175/165"
    assert M.card_no("PSA 10 Red's Pikachu 270/SM-P Promo") == "270/SM-P"
    assert M.card_no("PSA10 Charizard") is None
    assert M.card_no("") is None
    assert M.card_no(None) is None


def test_カード単位の集計は出品をまたいで足す():
    rows = [
        _row("1", "PSA10 Psyduck AR 175/165 SV2a", sold="2"),
        _row("2", "PSA10 コダック AR 175/165 sv2a 151", sold="1"),
        _row("3", "PSA10 Charizard 番号なし", sold="4"),
    ]
    agg, unknown = M.by_card(rows)
    assert agg["175/165"]["sold"] == 3
    assert agg["175/165"]["listings"] == 2
    assert unknown == 4


def test_サマリーCSVは取り込まない(tmp_path):
    (tmp_path / "terapeak_20260918_0702.csv").write_text("x", encoding="utf-8")
    (tmp_path / "terapeak_summary_20260918_0702.csv").write_text("x", encoding="utf-8")
    found = [os.path.basename(p) for p in M.find_files([str(tmp_path)])]
    assert found == ["terapeak_20260918_0702.csv"]


import datetime
import urllib.parse


def _q(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query, keep_blank_values=True)


NOW = datetime.datetime(2026, 9, 18, 9, 0, 0)


def test_条件は毎回同じものが焼かれる():
    q = _q(M.build_url("ポケモン", now=NOW))
    assert q["categoryId"] == ["183454"]
    assert sorted(q["format"]) == ["BEST_OFFER", "FIXED_PRICE"]
    assert q["sellerCountry"] == ["JP"]
    assert q["keywords"] == ["PSA10"]   # 2026-09-18 ユーザー確定
    assert q["sorting"] == ["-itemssold"]
    assert q["dayRange"] == ["90"]
    assert "buyerCountry" not in q          # 買い手の国で絞るのは誤り (2026-09-18)
    assert "price" not in q                 # 価格の下限は入れない


def test_ドラゴンボールはSuperCardGameだけ():
    # 2026-09-18 カタログ回答: Dragon Ball CCG は 2000年代の別ゲーム (Score 社)。
    # うちが扱う FB/DBS の弾は Super Card Game なので入れない
    q = _q(M.build_url("ドラゴンボール", now=NOW))
    assert q["aspect"] == ["Game:::Dragon Ball Super Card Game"]


def test_ACTIVEには売れた数の並びを付けない():
    assert "sorting" not in _q(M.build_url("ポケモン", tab="ACTIVE", now=NOW))
    assert _q(M.build_url("ポケモン", tab="ACTIVE", now=NOW))["tabName"] == ["ACTIVE"]


def test_期間は開始日にも効く():
    q = _q(M.build_url("ポケモン", days=365, now=NOW))
    span = (int(q["endDate"][0]) - int(q["startDate"][0])) / 86400000
    assert round(span) == 365


def test_知らない商材やタブは弾く():
    import pytest
    with pytest.raises(KeyError):
        M.build_url("ガンダム")
    with pytest.raises(ValueError):
        M.build_url("ポケモン", tab="BOTH")


def test_ワンピースとドラゴンボールの番号も読む():
    # 2026-09-18: 斜線の形しか見ておらず、この2ゲームは1枚も読めていなかった
    assert M.card_no("PSA10 Shanks OP03-057 Manga Alt Art") == "OP03-057"
    assert M.card_no("Nami (Full Art) ST29-008 Starter Deck 29") == "ST29-008"
    assert M.card_no("PSA10 Monkey D Luffy P-043 WEEKLY SHONEN JUMP") == "P-043"
    assert M.card_no("2025 DBS Fusion World Son Goku FB02-119 PSA10") == "FB02-119"
    assert M.card_no("PSA10 Super Dragon Ball Heroes MM2-074 Son Goku") == "MM2-074"
    assert M.card_no("PSA10 Dragon Ball Super Divers Goku SDV9-020") == "SDV9-020"


def test_斜線の形を先に見る():
    # 両方あるタイトルでは、ポケモンの形 (斜線) を優先する
    assert M.card_no("PSA10 Psyduck AR 175/165 SV2a sv2a-175") == "175/165"
