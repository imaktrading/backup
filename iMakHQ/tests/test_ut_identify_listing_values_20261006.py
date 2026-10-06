"""UT 目視: 色・サイズ・作品名を目視に出して人が確かめ・直す (№501・2026-10-06 ユーザー提案)。

画面の「出品の値」は出品くんと同じ判定 (values_for_entry) で出す。人が直したサイズは台帳の size_hand で
シートのサイズ欄より優先され、英語の作品名は対応表 (ut_title_names.yaml) に足す。
"""
import os
import sys

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, "..", "tools"))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "iMakMercari"))
import pytest  # noqa: E402
import ut_catalog_values as U  # noqa: E402
import ut_identify as UI  # noqa: E402


def _p(**s):
    base = {"data_level": "design_listable", "collab": "鬼滅の刃"}
    base.update(s)
    return {"category": "uniqlo_ut", "product_id": "FP1-01", "name": "鬼滅", "specs": base, "images": []}


def test_hand_size_wins_over_sheet_size(monkeypatch):
    monkeypatch.setattr(U, "load_product", lambda pid, db=None: _p())
    e = {"decision": "go", "product_id": "FP1-01", "color": "ブラック", "size_hand": "XL"}
    v = U.values_for_entry(e, "M", title="鬼滅 UT M", check_images=False)
    assert v["size_jp"] == "XL"


def test_work_en_used_only_when_table_misses(monkeypatch):
    unknown = _p(collab="まだ表に無い作品")
    with pytest.raises(U.NotListable):
        U.build_values(unknown, "ブラック", "L")
    assert U.build_values(unknown, "ブラック", "L", work_en="New Work")["work_en"] == "New Work"
    # 表で当たる時は表が勝つ (人の入力で綴りをぶらさない)
    assert U.build_values(_p(), "ブラック", "L", work_en="Kimetsu")["work_en"] == "Demon Slayer"


def test_preview_returns_values_or_reason():
    def fake(e, size_text, title="", text="", work_en="", check_images=True):
        if not e["size_hand"]:
            raise ValueError("サイズを読めない: ''")
        return {"specs": {"Color": "Black", "Department": "Men"}, "size_jp": e["size_hand"],
                "size_us": "M", "work_en": work_en or "Demon Slayer"}
    ok = UI.listing_preview({"pid": "X", "color": "黒", "size": "L"}, values_for_entry=fake)
    assert ok["ok"] and ok["size_jp"] == "L" and ok["color"] == "Black"
    ng = UI.listing_preview({"pid": "X", "color": "黒", "size": ""}, values_for_entry=fake)
    assert not ng["ok"] and "サイズ" in ng["reason"]
    assert UI.listing_preview({"pid": ""})["ok"] is False


def test_preview_flags_missing_work():
    def fake(e, *a, **k):
        raise ValueError("作品名が対応表に無い: xx")
    assert UI.listing_preview({"pid": "X"}, values_for_entry=fake)["need_work"] is True


def test_add_work_appends_once(tmp_path):
    y = tmp_path / "names.yaml"
    y.write_text("works:\n  鬼滅の刃: Demon Slayer\n", encoding="utf-8")
    assert UI.add_work("新しい作品: 副題", "New Work", path=str(y)) is True
    assert UI.add_work("新しい作品: 副題", "New Work", path=str(y)) is False     # 2回目は表で当たる
    assert UI.add_work("鬼滅の刃", "Kimetsu", path=str(y)) is False               # 既にある作品は足さない
    assert U.load_works(str(y))["新しい作品: 副題"] == "New Work"


def test_parse_result_keeps_size_and_work():
    res = UI.parse_result({"picks": [{"idx": 1, "pid": "P", "color": "", "design": True,
                                      "size": " XL ", "work": "New  Work"}]})
    assert res["picks"][0]["size"] == "XL" and res["picks"][0]["work"] == "New Work"
