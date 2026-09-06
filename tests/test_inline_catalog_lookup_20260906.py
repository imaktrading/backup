# -*- coding: utf-8 -*-
"""番号を打った所で、その場でカタログを引いて候補を出す (2026-09-06 ユーザー要望)。

従来は「番号を打つ → 確定 → 次回また開く」の2往復。その間、候補ゼロの画面を見た人が
「カタログに無い」と判断して追加依頼を押していた。
実測 (2026-09-06): 押した16件すべて、番号を入れたらカタログに**在って**依頼が取り消された
(= 押し損 + 翌日また同じ行を見る)。打った所で見せれば、その場で版まで決まる。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import newcand_confirm as nc          # noqa: E402
import psa_resource_confirm as prc    # noqa: E402

ITEM = {"idx": 0, "url": "https://jp.mercari.com/item/m1", "title": "PSA10 なにか",
        "price": 100, "card_no": "", "variants": [], "src": "補URL候補NG",
        "src_itemid": "358", "dups": [], "no_from_typed": False}

VS = [{"pid": "OP01-001", "category": "one_piece_tcg", "name": "ルフィ",
       "image": "https://img/1.jpg", "en_only": False}]


def test_api_returns_cards_for_a_known_number(monkeypatch):
    monkeypatch.setattr(nc, "catalog_variants", lambda no, *a, **k: VS)
    out = nc.lookup_api("/api/variants", {"no": "op01-001"})
    assert out["n"] == 1 and out["no"] == "OP01-001"
    assert "OP01-001" in out["html"] and "pickV(this)" in out["html"]


def test_api_says_zero_when_catalog_really_lacks_it(monkeypatch):
    """0件で初めて『カタログに無い』が確定する (画面もその文言に切り替わる)。"""
    monkeypatch.setattr(nc, "catalog_variants", lambda no, *a, **k: [])
    out = nc.lookup_api("/api/variants", {"no": "ZZ99-999"})
    assert out["n"] == 0 and out["html"] == ""


def test_api_ignores_other_paths():
    assert nc.lookup_api("/api/other", {}) is None


def test_api_handles_empty_number(monkeypatch):
    monkeypatch.setattr(nc, "catalog_variants", lambda no, *a, **k: VS)
    assert nc.lookup_api("/api/variants", {"no": "  "})["n"] == 0


def test_screen_is_wired_to_the_api():
    h = nc.build_html([dict(ITEM)]).decode("utf-8")
    assert "class='vslot'" in h            # 差し替え先の枠
    assert "onchange='lookupNo(this)'" in h
    assert "function lookupNo" in h and "/api/variants" in h


def test_typed_number_is_still_recorded():
    """その場で引けても、番号は台帳に残す (dataset.cno を書き換えない)。

    書き換えると go() が「番号を打った」と見なさなくなり、CNO_TAB に残らず
    次回また候補ゼロで出てくる。
    """
    h = nc.build_html([dict(ITEM)]).decode("utf-8")
    assert "box.dataset.cno=no" not in h


def test_first_render_and_inline_render_share_one_function(monkeypatch):
    """最初の描画と差し込みで同じ HTML (onclick がズレると選べなくなる)。"""
    monkeypatch.setattr(nc, "catalog_variants", lambda no, *a, **k: VS)
    inline = nc.lookup_api("/api/variants", {"no": "OP01-001"})["html"]
    assert inline == nc.variant_cards_html(VS)


def test_serve_confirm_accepts_an_api_hook():
    """API の口が残っていること (無いと画面から問い合わせできない)。"""
    import inspect
    assert "api" in inspect.signature(prc._serve_confirm).parameters
