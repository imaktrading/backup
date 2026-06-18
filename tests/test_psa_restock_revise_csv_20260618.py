"""Regression: 2026-06-18 — RESTOCK Add CSV → Revise CSV 変換(B)。

CSV生成は新規出品と完全同一(psa_to_csv)に保ち、その Add CSV を Revise化するだけの後処理。
itemID維持で復活+刷新。PicURL/ScheduleTime除去(画像維持)、Profile維持(Revise挫折=Profile空欄bug回避)、
Action=Revise、ItemID挿入(cert→itemID)、Quantity=1。itemID未解決はfail-closedでskip。
"""
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_restock_revise_csv.py"
_spec = importlib.util.spec_from_file_location("psa_restock_revise_csv_t", _P)
import sys
sys.path.insert(0, str(_P.parent))
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

_ADD_HEADER = ["*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)", "*Category", "*Title",
               "PicURL", "*StartPrice", "CDA:Certification Number - (ID: 27503)", "ScheduleTime",
               "*Quantity", "ShippingProfileName", "ReturnProfileName", "PaymentProfileName", "C:Set"]


def _row(action, cert, pic="https://p/1.jpg"):
    return [action, "183454", "PSA 10 X", pic, "45.0", cert, "2026-07-01", "1",
            "ship_40", "No return", "SALE", "Romance Dawn"]


def test_transform_to_revise_basic():
    rh, rr, sk = rv.add_rows_to_revise(_ADD_HEADER, [_row("Add", "142490884")],
                                       {"142490884": "358481165472"})
    assert "ItemID" in rh
    assert "PicURL" not in rh and "ScheduleTime" not in rh        # 画像維持/予約不要 → 列ごと除去
    assert "ShippingProfileName" in rh and "ReturnProfileName" in rh and "PaymentProfileName" in rh  # Profile維持
    r = rr[0]
    assert r[0] == "Revise"                                       # Action=Revise
    assert r[rh.index("ItemID")] == "358481165472"               # ItemID挿入
    assert r[rh.index("*Quantity")] == "1"                       # qty=1
    assert r[rh.index("*Title")] == "PSA 10 X"                    # Title等はAddのまま(新コア刷新値)


def test_itemid_unresolved_is_skipped_failclosed():
    rh, rr, sk = rv.add_rows_to_revise(_ADD_HEADER, [_row("Add", "999")], {})  # cert→itemID無
    assert rr == [] and len(sk) == 1 and sk[0][0] == "999"        # Revise不可→出さずskip


def test_itemid_inserted_right_after_action():
    rh, rr, _ = rv.add_rows_to_revise(_ADD_HEADER, [_row("Add", "142490884")], {"142490884": "i1"})
    assert rh[0].startswith("*Action") and rh[1] == "ItemID"      # Action直後にItemID
    assert rr[0][0] == "Revise" and rr[0][1] == "i1"


def test_valid_cert_itemid_filters_pollution():
    # 2026-06-18 試走で検出: 商品管理シート多カテゴリ混在で非TCG行が cert→itemID を汚染
    # (cert='356700921169' → itemID='Cowes T-shirt XL')。形式検証で弾く。
    assert rv._valid_cert_itemid("142490884", "358481165472")        # 正(9桁cert/12桁itemID)
    assert not rv._valid_cert_itemid("356700921169", "Cowes T-shirt XL")  # 名前混入→弾く
    assert not rv._valid_cert_itemid("142490884", "notnum")          # itemID非数字
    assert not rv._valid_cert_itemid("abc", "358481165472")          # cert非数字
    assert not rv._valid_cert_itemid("", "")


def test_bad_format_raises():
    import pytest
    with pytest.raises(ValueError):
        rv.add_rows_to_revise(["foo", "bar"], [["1", "2"]], {})   # Action/cert列無し
