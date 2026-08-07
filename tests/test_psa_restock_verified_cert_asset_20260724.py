# -*- coding: utf-8 -*-
"""RESTOCK が出品時の目視確定(verified_certs.json)を資産回収する回帰テスト (2026-07-24)。

欠陥: 出品時に HTML viewer で人が変種を確定(verified_certs.json cert→product_id に資産化)
していても、RESTOCK 再仕入れ照合は itemID→商品管理シートAI列 の join でしか KEY を引かず、
promo 12変種曖昧カード等で AI列書き戻しが漏れると「出品したのに未解決」で再目視を要求した。
= 出品時に払った目視コストが捨てられる欠陥(ユーザー指摘: 「特定したなら資産化しないと意味がない」)。
対策: itemID→cert→verified_certs で、出品時に確定した KEY を cert 経由で回収する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools"))
import psa_resource_gate as g  # noqa: E402


_VC = {
    "154803822": {"choice": "CHOSEN", "product_id": "P-001_OTHER PRODUCT CARD_GC01"},
    "153621583": {"choice": "OK", "product_id": "SM9-038"},
    "99999999": {"choice": "NONE", "product_id": ""},
}


def test_chosen_recovers_key():
    """★本命: CHOSEN(人が選択)の変種KEYを cert から回収。"""
    assert g.key_from_verified_cert("154803822", _VC) == "P-001_OTHER PRODUCT CARD_GC01"


def test_ok_recovers_key():
    """OK(期待通り=自動確定を承認)も product_id を持ち回収対象。"""
    assert g.key_from_verified_cert("153621583", _VC) == "SM9-038"


def test_none_not_recovered():
    """NONE(未確定)は推測でKEYを作らない=空(fail-closed)。"""
    assert g.key_from_verified_cert("99999999", _VC) == ""


def test_missing_cert_empty():
    assert g.key_from_verified_cert("000", _VC) == ""
    assert g.key_from_verified_cert("", _VC) == ""
    assert g.key_from_verified_cert(None, _VC) == ""


def test_load_missing_file_returns_empty():
    """ファイル欠落/壊れでも例外を出さず {}(照合本体を壊さない)。"""
    assert g.load_verified_certs(path=r"C:/nonexistent/verified_certs.json") == {}
