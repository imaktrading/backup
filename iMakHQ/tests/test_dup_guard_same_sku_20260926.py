"""入稿前ガード: 同じ仕入元の SKU が既に eBay に出ていれば落とす (2026-09-26)。

9/22 の出品の itemID がシートに書き戻されず、9/23 に同じメルカリ出品で10件を二重出品した。
cert の突合は live SKU が PSA10-<cert> の出品しか拾えず、SKU=メルカリ番号の出品が見えなかった。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from dup_guard import same_sku_already_live  # noqa: E402

H = ["CustomLabel", "*Title"]


def test_mercari_sku_already_live_is_dropped():
    rows = [["m95436408251", "Caterpie"], ["m11111111111", "New one"]]
    out = same_sku_already_live(rows, H, {"820158103328": "m95436408251"}.values())
    assert [o["label"] for o in out] == ["m95436408251"]
    assert out[0]["row"] == 0


def test_psa_cert_sku_and_asin_are_checked_too():
    rows = [["PSA10-158716126", "a"], ["B0ABCDEFGH", "b"]]
    assert len(same_sku_already_live(rows, H, ["PSA10-158716126", "B0ABCDEFGH"])) == 2


def test_shared_generic_sku_is_not_treated_as_one_item():
    rows = [["UNIQLO official website", "tee"], ["", "blank"]]
    assert same_sku_already_live(rows, H, ["UNIQLO official website", ""]) == []
