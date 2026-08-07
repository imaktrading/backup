"""オファー判定が仕入値とカテゴリを黙って間違えないこと (2026-08-02)。

なぜ (ユーザー報告「オファー判定だけど、仕入れ値を読み込まなくなった」):
    実オファー `358785699167` で cost=0 / cat=TCG(PSA10) になっていた。実測すると:
      - この出品は **eBaymag のミラー** (ApplicationData=`ebaymag.com-750522208`)。
        `Site` は US 固定、`Currency` は EUR、**SKU は無し**、商品管理シートにも存在しない
      - 突合は「SKU = 仕入元メルカリID」1本しか無く、**PSA (SKU=`PSA10-<cert>`) でも外れる**
      - シート行が引けないとカテゴリが**既定値の TCG(PSA10)** に落ちる
        → 一番くじのフィギュアが TCG と表示され、その採算表で判断しかけた

    仕入値 0 のまま採算を見ると**赤字オファーを承諾しかねない**。
    取れないなら「取れない」と出すのが正しい (fail-closed)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import offer_calc as OC  # noqa: E402
import sheet_io as S  # noqa: E402


def test_cert_column_matches_sheet_io():
    """cert 列を二重定義しているので、ズレたら落とす (見出しは 'Title' のままだが中身は cert)."""
    assert OC.COL_CERT == S.PRODUCT_COL_CERT


def test_category_falls_back_to_ebay_category_not_tcg():
    """★シートに無い出品を黙って TCG(PSA10) にしない.

    一番くじ (69528) の出品が TCG と表示されていたのが発端。
    """
    assert OC.CATID2CALC["69528"] == "一番くじ"
    assert OC.CATID2CALC["183454"] == "TCG(PSA10)"
    assert "TCG" not in OC.CATID2CALC["31387"]


def test_psa_sku_is_recognised_as_cert():
    """PSA 出品の SKU は `PSA10-<cert>`。メルカリID前提の突合では絶対に当たらない."""
    import re
    for sku, cert in (("PSA10-79616349", "79616349"), ("psa10-12345678", "12345678")):
        m = re.match(r"(?i)^PSA10?-(\d{6,10})$", sku)
        assert m and m.group(1) == cert
    # 仕入元メルカリID は cert 扱いしない (誤突合を作らない)
    assert not re.match(r"(?i)^PSA10?-(\d{6,10})$", "m12345678901")


def test_mirror_marker_is_application_data():
    """ミラー判定は ApplicationData。Site/Currency では判定できない (実測).

    Site=US 固定 / Currency は EUR だが、US本体にも EUR 建てはありうる。
    US本体 120件を GetItem した実測では ApplicationData は **0件**だった。
    """
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "tools", "offer_calc.py"), encoding="utf-8").read()
    assert "ApplicationData" in src and "ebaymag" in src
    assert "is_mirror" in src


def test_unresolved_cost_is_explained_not_silent():
    """★仕入値が取れない時は理由を出す。黙って 0 を出すと赤字オファーを承諾しかねない."""
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "tools", "offer_calc.py"), encoding="utf-8").read()
    assert "仕入値は手入力" in src
    assert "ミラー出品のためシートに無い" in src
