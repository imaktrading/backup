# -*- coding: utf-8 -*-
"""連番・複数枚まとめ売りを出品しない (2026-08-23 ユーザー確認事項)。

ユーザーの問い:「自動化になってきているので、念のため — 連番等の複数枚ははじくロジックに
なっている？」実機を見た結果、**なっていなかった**:
  - 1つの仕入元出品に複数枚入っているのを見抜く仕組みは無く、人が候補確認画面で
    「まとめ売り・複数枚」を選ぶ手動運用だけだった
  - 同じ仕入元URLを2つの出品が指す状態は検出していたが、**出品した後**の棚卸しだけで、
    入稿の前には見ていなかった

なぜ危ないか:
  - まとめ売りは **1枚だけ買えない**。売れても仕入値が想定と違う (全部付いてくる) し、
    出品は1つしか作れないのに現物は複数枚になる
  - 同じURLを2つの出品が指すと、**1つ買っても2つは埋められない** → 片方はキャンセル
    → Defect Rate → 無在庫運営では致命的
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (os.path.join(_ROOT, "iMakTCG"), os.path.join(_ROOT, "iMakHQ", "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)


# ── ① 仕入元タイトルが「まとめ売り」と言っている ──────────────────
@pytest.fixture(scope="module")
def P():
    import psa_to_csv
    return psa_to_csv


@pytest.mark.parametrize("title,why", [
    # 実データ (商品管理シート 2026-08-23 時点) から
    ("PSA10連番 エールストライクガンダム イージスガンダムST04 LR+", "連番"),
    ("PSA10 OP01-077 ペローナ, ST12-012 プリン 2枚セット", "2枚"),
    ("PSA10 連番 ホウオウ 004/028 ルギア 005/028 25th", "連番"),
    ("PSA10 かがやくイーブイ 3枚セット ポケモンカード", "3枚"),
    ("超希少【 PSA 10 】 ゲンガー 3連番セット　240/193", "連番"),
    ("ポケカ まとめ売り PSA10", "まとめ売り"),
    ("PSA10 リザードン セット売り", "セット売り"),
])
def test_lot_titles_are_caught(P, title, why):
    assert P.supply_lot_hint(title) == why, title


@pytest.mark.parametrize("title", [
    # ★実データで唯一の誤検出。「世界に4枚」は **希少さの自慢**で出品枚数ではない
    "【8/8時点世界に4枚！】【PSA10】ロロノア・ゾロ(R){緑}〈OP13-037〉",
    "【PSA10】ピカチュウ 1枚",
    "PSA10 ソウブレイズex SAR 現存5枚",
    "PSA10 リザードンex 美品 即購入可",
    "",
])
def test_single_card_titles_are_not_caught(P, title):
    assert P.supply_lot_hint(title) is None, title


def test_multi_card_certs_maps_cert_to_reason(P):
    m = {"111": "PSA10 かがやくイーブイ 3枚セット",
         "222": "【PSA10】ピカチュウ",
         "333": "PSA10 連番 ホウオウ ルギア"}
    assert P.multi_card_certs(m) == {"111": "3枚", "333": "連番"}


def test_entry_filter_drops_lots(P):
    """入口で落とす分岐が残っていること (枠を選ぶ前に落とす)。"""
    src = open(os.path.join(_ROOT, "iMakTCG", "psa_to_csv.py"), encoding="utf-8").read()
    assert "_lots = multi_card_certs(mercari_title_map)" in src
    assert "まとめ売り/連番を除外" in src


# ── ② 仕入元URLが既に出品中の行に取られている ────────────────────
@pytest.fixture(scope="module")
def G():
    import dup_guard
    return dup_guard


_URL = "https://jp.mercari.com/item/m111"


def _sheet(G):
    """[header, 出品中の行(URL=m111), これから出す行(同じURL・itemID空)]"""
    w = max(G.CERT, G.B, G.AUX0 + G.AUXN) + 2
    head = [""] * w
    live = [""] * w
    live[G.A], live[G.B], live[G.CERT] = _URL, "820000000001", "999"
    new = [""] * w
    new[G.A], new[G.CERT] = _URL, "888"          # itemID 空 = これから出す
    return [head, live, new]


_HDR = ["CustomLabel", "CDA:Certification Number - (ID: 27503)"]


def test_supply_url_already_taken_is_detected(G):
    rows = [["m888", "888"]]
    got = G.supply_url_taken_by_live(rows, _HDR, _sheet(G))
    assert len(got) == 1
    assert got[0]["cert"] == "888"
    assert got[0]["owner"] == ["820000000001"]


def test_free_supply_url_is_not_flagged(G):
    sheet = _sheet(G)
    sheet[1][G.A] = "https://jp.mercari.com/item/m222"     # 出品中は別URL
    assert G.supply_url_taken_by_live([["m888", "888"]], _HDR, sheet) == []


def test_ended_listing_does_not_hold_the_url(G):
    """取り下げ済 (D列が埋まっている) 行は URL を押さえていない。"""
    sheet = _sheet(G)
    sheet[1][G.D] = "売り切れ"
    assert G.supply_url_taken_by_live([["m888", "888"]], _HDR, sheet) == []


def test_aux_url_also_counts(G):
    """補URLで押さえている場合も、そこから仕入れる前提なので同じ扱い。"""
    sheet = _sheet(G)
    sheet[1][G.A] = "https://jp.mercari.com/item/m999"
    sheet[1][G.AUX0] = _URL
    got = G.supply_url_taken_by_live([["m888", "888"]], _HDR, sheet)
    assert len(got) == 1


def test_query_string_does_not_hide_the_match(G):
    sheet = _sheet(G)
    sheet[1][G.A] = _URL + "?afid=123"
    assert len(G.supply_url_taken_by_live([["m888", "888"]], _HDR, sheet)) == 1


def test_precheck_is_wired_before_upload(G):
    src = open(os.path.join(_ROOT, "iMakHQ", "tools", "dup_guard.py"), encoding="utf-8").read()
    assert "taken = supply_url_taken_by_live(rows, header, vals)" in src, \
        "入稿前チェックから呼ばれていない (出品後の棚卸しだけに戻っている)"
    assert "pre_upload_stripped_shared_url" in src, "除外した記録が残らない"
