# -*- coding: utf-8 -*-
"""キャラ軸の探す先 (2026-09-21)。

市場 (テラピーク) で売れたキャラと、うちが売ったキャラを1本にまとめる。
**両方に出るキャラが一番強い**ので先頭に置く。キャラ軸にカードごとの仕入上限は無い。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(r"C:\dev\iMak\iMakHQ", "tools"))

import chara_demand_xlsx as C  # noqa: E402
import chara_targets_build as B  # noqa: E402


def _m(n, cards=1, px=(100.0,), game="pokemon_tcg"):
    return {"枚数": n, "カード数": cards, "価格": list(px), "ゲーム": game, "例": ["001/001"]}


# ---- chara_of: 形態違いは同じキャラ ----

def test_形態違いを同じキャラにまとめる():
    assert C.chara_of("リザードンVSTAR") == "リザードン"
    assert C.chara_of("ミュウVMAX") == "ミュウ"
    assert C.chara_of("ピカチュウV") == "ピカチュウ"
    assert C.chara_of("メガゲンガーex") == "メガゲンガー"
    assert C.chara_of("アローラ キュウコンGX") == "アローラ キュウコン"


def test_形態の付かない名前はそのまま():
    assert C.chara_of("モンキー・D・ルフィ") == "モンキー・D・ルフィ"
    assert C.chara_of("コイキング") == "コイキング"


def test_名前の途中のVは落とさない():
    # 末尾だけを落とす。途中の V を消すとキャラ名が壊れる
    assert C.chara_of("イベルタル") == "イベルタル"


# ---- merge: 出どころの付け方と並び順 ----

def test_両方に出るキャラは市場プラスうち():
    rows = B.merge({"カビゴン": _m(11)}, {"カビゴン": 3})
    assert rows[0]["出どころ"] == "市場+うち"
    assert rows[0]["売れた数"] == 11
    assert rows[0]["うちの実績"] == 3


def test_片方だけのキャラ():
    rows = {r["和名"]: r for r in B.merge({"ルフィ": _m(45)}, {"ゾロアーク": 2})}
    assert rows["ルフィ"]["出どころ"] == "市場"
    assert rows["ルフィ"]["うちの実績"] == 0
    assert rows["ゾロアーク"]["出どころ"] == "うち"
    assert rows["ゾロアーク"]["売れた数"] == 0


def test_並びは_両方_うち_市場_の順():
    market = {"ルフィ": _m(45), "カビゴン": _m(11)}
    ours = {"カビゴン": 3, "ゾロアーク": 2}
    names = [r["和名"] for r in B.merge(market, ours)]
    # 市場で45枚売れたルフィより、両方に出るカビゴン・うちで売れたゾロアークが先
    assert names == ["カビゴン", "ゾロアーク", "ルフィ"]


def test_キャラ軸に仕入上限は入れない():
    # 2026-09-21 ユーザー確定: キャラ軸は会社の上限7万円のみ・値付けは cost-plus。
    # カードごとの上限を入れると、抽出くんの門がキャラの別カードまで落としてしまう
    for r in B.merge({"カビゴン": _m(11)}, {"ゾロアーク": 2}):
        assert r["上限仕入れ値(円)"] == ""


def test_抽出くんが読む列を壊さない():
    # 抽出くんの treasure_keywords は demand_market.csv と同じ列名で読む。
    # 既存の列は変えず、足した列は末尾だけ
    cols = list(B.merge({"カビゴン": _m(11)}, {})[0].keys())
    assert cols[:11] == ["番号", "product_id", "和名", "英名", "画像", "ゲーム", "売れた数",
                         "出品本数", "実売中央値", "上限仕入れ値(円)", "市場のタイトル例"]
    assert cols[11:] == ["うちの実績", "出どころ"]


def test_キャラ名は和名の列に入る():
    # 抽出くんは「和名」列から PSA10 {和名} の検索語を作る
    r = B.merge({}, {"カビゴン": 3})[0]
    assert r["和名"] == "カビゴン"
    assert r["番号"] == ""


# ---- version_of: 通常 / プロモ / パラレル ----

def test_パラレルはproduct_idで決まる():
    assert C.version_of("OP05-119_p1") == "パラレル"
    assert C.version_of("FB08-121_PARA") == "パラレル"


def test_ワンピースはAltArtをパラレルと数える():
    # 2026-09-21 ユーザー確定: ワンピースでは Alt Art / Parallel / Manga = パラレル
    t = "One Piece PRB01 Monkey D. Luffy PSA10 OP05-119 SEC Alt Art"
    assert C.version_of("OP05-119", t, "one_piece_tcg") == "パラレル"
    assert C.version_of("OP13-118", "Luffy Manga Alternate Art PSA10", "one_piece_tcg") == "パラレル"


def test_ワンピース以外のAltArtはパラレルにしない():
    # FB05-119 孫悟空はカード自体が別イラストのSCRで、市場が Alt Art と呼んでいるだけ (9/20)
    t = "PSA10 Son Goku FB05-119 SCR Alt Art"
    assert C.version_of("FB05-119", t, "dragonball_scg") == "通常"


def test_プロモの弾():
    assert C.version_of("S-P-338") == "プロモ"
    assert C.version_of("M-P-017") == "プロモ"
    assert C.version_of("S8a-P-003") == "プロモ"
    assert C.version_of("XYP-122") == "プロモ"
    assert C.version_of("P-043", "", "one_piece_tcg") == "プロモ"


def test_通常版():
    assert C.version_of("SV2a-173", "PSA10 Pikachu 173/165 Sv2a", "pokemon_tcg") == "通常"
    assert C.version_of("S12a-212") == "通常"
    # 弾コードに P が付くだけの通常弾をプロモにしない
    assert C.version_of("SV2P-073") == "通常"


# ---- 全角・半角 / 版の語 ----

def test_全角と半角のキャラ名を揃える():
    assert C.chara_of("モンキー・Ｄ・ルフィ") == C.chara_of("モンキー・D・ルフィ")


def _mv(n, **ver):
    a = _m(n)
    a["版"] = dict(ver)
    return a


def test_通常版が半分未満なら版の語を足す():
    rows = B.merge({"ルフィ": _mv(45, 通常=4, プロモ=26, パラレル=15)}, {})
    assert [r["和名"] for r in rows] == ["ルフィ", "ルフィ プロモ", "ルフィ パラレル"]


def test_キャラ名の語は残す():
    # 減らさず増やす (1語15件が上限なので、語を消すとその枠ごと消える)
    names = [r["和名"] for r in B.merge({"ルフィ": _mv(45, 通常=4, プロモ=26, パラレル=15)}, {})]
    assert "ルフィ" in names


def test_枚数の少ない版は足さない():
    rows = B.merge({"シャンクス": _mv(5, 通常=1, プロモ=1, パラレル=3)}, {})
    assert [r["和名"] for r in rows] == ["シャンクス", "シャンクス パラレル"]


def test_通常版が売れているキャラには足さない():
    rows = B.merge({"ピカチュウ": _mv(26, 通常=24, プロモ=2)}, {})
    assert [r["和名"] for r in rows] == ["ピカチュウ"]
