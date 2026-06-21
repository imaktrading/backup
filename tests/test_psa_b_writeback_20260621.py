"""Regression: 2026-06-21 — PSA新規出品 itemID を B列 に書戻し(出品済を出品プールから外す)。

歩留まり激減(10→1〜2件)の主因 = 出品後 B列未書戻しで既出品が pool 残留→再scrape→dedup除外。
CustomLabel(PSA10-cert / m-mercari-id)で master を一意特定し B列書込。fail-closed(誤紐付け防止)。
"""
import importlib.util
from pathlib import Path
import sys

_P = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_b_writeback.py"
sys.path.insert(0, str(_P.parent))
_spec = importlib.util.spec_from_file_location("psa_b_writeback_t", _P)
wb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wb)


def test_mercari_id_from_url():
    assert wb.mercari_id_from_url("https://jp.mercari.com/item/m81209020913") == "m81209020913"
    assert wb.mercari_id_from_url("https://jp.mercari.com/item/m123 | https://x/m999") == "m123"  # 先頭
    assert wb.mercari_id_from_url("https://snkrdunk.com/apparels/126668/used/47084366") == ""    # 非mercari
    assert wb.mercari_id_from_url("") == ""


def test_match_label_cert():
    assert wb.match_label_to_cert_or_mid("PSA10-55542036") == ("cert", "55542036")
    assert wb.match_label_to_cert_or_mid("psa10-126337871") == ("cert", "126337871")   # 大小無視


def test_match_label_mercari():
    assert wb.match_label_to_cert_or_mid("m99367005303") == ("mid", "m99367005303")


def test_match_label_bad():
    assert wb.match_label_to_cert_or_mid("008-PSA10") == (None, "")       # cardnum-PSA10 は不明
    assert wb.match_label_to_cert_or_mid("") == (None, "")
    assert wb.match_label_to_cert_or_mid("PSA10-") == (None, "")          # cert無し


def test_plan_write_skip_conflict():
    pairs = [("PSA10-111", "ITEM_A"),       # cert一致, B空 → WRITE
             ("m222", "ITEM_B"),            # mid一致, B空 → WRITE
             ("PSA10-333", "ITEM_C"),       # cert一致, 既に同ID → SKIP_SAME
             ("PSA10-444", "ITEM_NEW"),     # cert一致, 既に別ID → CONFLICT(書かない)
             ("PSA10-999", "ITEM_X"),       # 行特定不可 → NO_MATCH
             ("garbage", "ITEM_Y")]         # 形式不明 → BAD_LABEL
    cert_to_row = {"111": 2, "333": 4, "444": 5}
    mid_to_row = {"m222": 3}
    current_b = {2: "", 3: "", 4: "ITEM_C", 5: "ITEM_OLD"}
    plan = wb.plan_writeback(pairs, cert_to_row, mid_to_row, current_b)
    by = {p["label"]: p["status"] for p in plan}
    assert by["PSA10-111"] == "WRITE"
    assert by["m222"] == "WRITE"
    assert by["PSA10-333"] == "SKIP_SAME"
    assert by["PSA10-444"] == "CONFLICT"       # 既存別IDは上書きしない(fail-closed)
    assert by["PSA10-999"] == "NO_MATCH"
    assert by["garbage"] == "BAD_LABEL"
    # CONFLICT は item_id を current で上書きしない
    conflict = next(p for p in plan if p["label"] == "PSA10-444")
    assert conflict["current"] == "ITEM_OLD" and conflict["item_id"] == "ITEM_NEW"
