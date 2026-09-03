# -*- coding: utf-8 -*-
"""同じ機能は同じ言葉・同じ並びにする (2026-09-03)。

## なぜ
商材ごとに言い回しが違い、押す前に一瞬考えることになっていた (ユーザー指摘)。

    PSA      🃏 PSA再仕入れ照合 / ♻ RESTOCK Revise CSV生成 / 🔄 RESTOCK状態同期(書戻し)
    UT       🛒 UT 在庫切れ再仕入れ (探す) / (目視→戻す)
    一番くじ  🎴一番くじ補充① supply確定 / 🎴一番くじ補充② 刷新→CSV

同じ「在庫切れ再仕入れ」なのに 照合 / 補充 / RESTOCK と3通りの言い方だった。

## 揃えた形
    <商材> 補URL   ① 当日分 / ② 夜に探す / ③ 目視
    <商材> 再仕入れ ① 探す   / ② …       / ③ …

    商材は PSA / UT / くじ の3語に揃える。ラベルは17字以内 (ボタンからはみ出さない)。

並びもラベルの丸数字で決まるので、商材が増えても崩れない。
"""
import os
import re

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()
_LINES = ("PSA", "UT", "くじ")


def _labels():
    return re.findall(r'"label": "([^"]+)"', _SRC)


def test_every_aux_url_button_uses_the_same_words():
    for lab in _labels():
        if "補URL" not in lab or "全系統" in lab:
            continue
        assert any(x in lab for x in _LINES), f"どの商材か分からない: {lab}"
        assert re.search(r"補URL [①②③]", lab), f"工程の番号が無い: {lab}"


def test_every_restock_button_uses_the_same_words():
    """『照合』『補充』『RESTOCK』と3通りあった言い方を1つにする。"""
    for lab in _labels():
        if "再仕入れ" not in lab or "全商材" in lab:
            continue          # 「📋 再仕入れ一覧 (全商材)」は商材をまたぐ表なので別物
        assert any(x in lab for x in _LINES), f"どの商材か分からない: {lab}"
        assert re.search(r"再仕入れ [①②③]", lab), f"工程の番号が無い: {lab}"
    # 古い言い方が **ラベル** に残っていないこと (コメントの参照は経緯なので可)
    labs = " / ".join(_labels())
    for gone in ("PSA再仕入れ照合", "一番くじ補充①", "一番くじ補充②",
                 "RESTOCK Revise CSV生成", "RESTOCK状態同期", "在庫切れ再仕入れ"):
        assert gone not in labs, f"古い言い方がラベルに残っている: {gone}"


def test_each_product_line_has_both_flows():
    labs = _labels()
    for line in _LINES:
        assert any(f"{line} 補URL" in x for x in labs), line
        assert any(f"{line} 再仕入れ" in x for x in labs), line


def test_order_comes_from_the_label_itself():
    """並びはラベルの 工程 + 丸数字 で決まる (商材が増えても崩れない)。"""
    i = _SRC.index("def _step_rank(")
    body = _SRC[i:i + 500]
    assert '"補URL" in lab' in body
    assert '"在庫切れ再仕入れ" in lab' in body
    assert '"①②③④"' in body
