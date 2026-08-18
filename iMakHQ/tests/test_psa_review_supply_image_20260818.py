# -*- coding: utf-8 -*-
"""目視画面に仕入元の写真を並べる (2026-08-18 ユーザー指示)。

なぜ:
    旧画面は「PSAの証明写真 ↔ カタログ」の2者だけだった。cert 番号を打ち間違えると
    その番号のPSA写真とカタログ候補が並ぶので**最後まで整合して見え**、
    手元に届く現物 (メルカリの出品) とのズレは人にも機械にも見えなかった。

守る性質:
  1. 並びは 仕入元 → PSA表 → PSA裏 → catalog (買う物 → 鑑定された物 → 正体)
  2. 1列=1画像。無い画像の列は作らない (空枠で横幅を食わない)
  3. 期待値が特定できない時も仕入元は出す
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import post_psa_review as R  # noqa: E402

SUPPLY = "https://static.mercdn.net/item/detail/orig/photos/m1_1.jpg"
PSA_F = "https://d1htnxwo4o0jhw.cloudfront.net/cert/1/large/a.jpg"
PSA_B = "https://d1htnxwo4o0jhw.cloudfront.net/cert/1/large/b.jpg"
CAT = "C:/dev/iMak_data/catalog/img/OP01-001.png"


def _t(**kw):
    base = {"supply_image_url": SUPPLY, "cert_image_url": PSA_F,
            "cert_image_url_back": PSA_B, "csv_expected": "OP01-001"}
    base.update(kw)
    return base


def test_4枚がこの順で並ぶ():
    cols = R.confirm_columns(_t(), CAT)
    labels = [c[0] for c in cols]
    assert labels[0].startswith("🛒")
    assert labels[1] == "📋 PSA 表"
    assert labels[2] == "📋 PSA 裏"
    assert labels[3].startswith("📚 catalog")
    assert [c[1] for c in cols][:4] == [SUPPLY, PSA_F, PSA_B, CAT]


def test_無い画像の列は作らない():
    assert [c[0] for c in R.confirm_columns(_t(supply_image_url=""), CAT)][0] == "📋 PSA 表"
    assert "📋 PSA 裏" not in [c[0] for c in R.confirm_columns(_t(cert_image_url_back=""), CAT)]


def test_期待値が無くても仕入元とPSAは出す():
    cols = R.confirm_columns(_t(), "")
    assert [c[0] for c in cols] == ["🛒 仕入元 (現物)", "📋 PSA 表", "📋 PSA 裏"]


def test_全部無ければ空():
    assert R.confirm_columns({}, "") == []


def test_横一列のCSSが入っている():
    src = open(R.__file__, encoding="utf-8").read()
    assert "flex-wrap:nowrap" in src, "折り返すと縦に崩れる"
    assert ".confirm .col{flex:0 0 auto" in src, "1列=1画像の列指定が要る"
    # ★内側スクロールは 2026-07-28 にユーザーが不可と判定済 → 付けない
    #   (test_viewer_image_size_parity_20260728 が .confirm の overflow を禁じている)
    assert "max-width:300px" in src, "4枚が通常の画面幅に収まるサイズにする"


def test_仕入元はシートから引く_失敗しても止めない():
    src = open(R.__file__, encoding="utf-8").read()
    i = src.index("def _supply_pic_by_cert")
    body = src[i:src.index("\ndef ", i + 1)]
    assert "except Exception" in body and "従来どおり続行" in body
    assert "_SUPPLY_PIC_CACHE" in body, "シートは1回だけ読む"
