# -*- coding: utf-8 -*-
"""入稿CSV → eBay API 出品 の回帰テスト (2026-08-18)。

守る性質:
  1. 値を作らない (CSV に無いものを推測で埋めない)。欠けていたら出さない
  2. PSA の 等級/鑑定会社/証明番号 は **状態の詳細 (Condition Descriptors)** で送る。
     Item Specifics に入れるだけでは「Grade (27502) is a required field」で拒否される
  3. 証明番号のような自由入力は AdditionalInfo (Value で送ると弾かれる)
  いずれも 2026-08-18 に実機の VerifyAddFixedPriceItem で確かめた挙動。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from ebay_upload_csv import (build_item_xml, condition_descriptors, item_specifics,  # noqa: E402
                             missing_fields, pic_urls, parse_ack, VERIFY_CALL, ADD_CALL)

ROW = {
    "*Title": "PSA 10 Pokemon Card", "*Category": "183454", "*StartPrice": "306.98",
    "*Quantity": "1", "ConditionID": "2750", "CustomLabel": "PSA10-153025508",
    "*Duration": "GTC", "*Location": "Osaka", "*Description": "<html>x</html>",
    "PicURL": "https://x/1.jpg|https://x/2.jpg", "StoreCategoryID": "42054519010",
    "ShippingProfileName": "DDP-A-P21", "PaymentProfileName": "SALE",
    "ReturnProfileName": "No return",
    "C:Game": "Pokémon TCG", "C:Grade": "10", "C:Empty": "",
    "CD:Professional Grader - (ID: 27501)": "275010",
    "CD:Grade - (ID: 27502)": "275020",
    "CDA:Certification Number - (ID: 27503)": "153025508",
}


def test_検証と本番で呼ぶAPIが違う():
    assert VERIFY_CALL == "VerifyAddFixedPriceItem" and ADD_CALL == "AddFixedPriceItem"


def test_写真は縦棒区切りを分解する():
    assert pic_urls(ROW) == ["https://x/1.jpg", "https://x/2.jpg"]
    assert pic_urls({"PicURL": ""}) == []


def test_空欄のItem_Specificsは送らない():
    names = [n for n, _v in item_specifics(ROW)]
    assert "Game" in names and "Grade" in names and "Empty" not in names


def test_状態の詳細はIDと値で拾う():
    cds = condition_descriptors(ROW)
    assert ("27501", "275010", False) in cds
    assert ("27502", "275020", False) in cds
    # CDA: = 自由入力 → AdditionalInfo で送る印が立つ
    assert ("27503", "153025508", True) in cds


def test_XMLに状態の詳細が入る():
    xml = build_item_xml(ROW)
    assert "<ConditionDescriptors>" in xml
    assert "<Name>27502</Name><Value>275020</Value>" in xml
    assert "<Name>27503</Name><AdditionalInfo>153025508</AdditionalInfo>" in xml


def test_XMLの基本要素():
    xml = build_item_xml(ROW)
    for frag in ("<SKU>PSA10-153025508</SKU>", "<ConditionID>2750</ConditionID>",
                 "<ShippingProfileName>DDP-A-P21</ShippingProfileName>",
                 "<StoreCategoryID>42054519010</StoreCategoryID>",
                 '<StartPrice currencyID="USD">306.98</StartPrice>'):
        assert frag in xml, frag


def test_スケジュールは指定した時だけ入る():
    assert "<ScheduleTime>" not in build_item_xml(ROW)
    assert "<ScheduleTime>2026-09-01 00:00:00</ScheduleTime>" in build_item_xml(
        ROW, schedule_time="2026-09-01 00:00:00")


def test_足りない値は出品前に弾く():
    assert missing_fields(ROW) == []
    bad = dict(ROW, **{"ShippingProfileName": "", "PicURL": ""})
    m = missing_fields(bad)
    assert "ShippingProfileName" in m and "PicURL" in m


def test_ConditionIDはアスタリスク有無どちらの列名でも読む():
    assert missing_fields(dict(ROW, ConditionID="", **{"*ConditionID": "2750"})) == []
    assert "ConditionID" in missing_fields(dict(ROW, ConditionID=""))


def test_応答の判定():
    assert parse_ack("<Ack>Success</Ack><ItemID>123</ItemID>") == ("Success", "123", "")
    ack, iid, err = parse_ack("<Ack>Failure</Ack><LongMessage>だめ</LongMessage>")
    assert ack == "Failure" and iid == "" and "だめ" in err
    assert parse_ack("")[0] == "NoAck"
