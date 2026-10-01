"""実 eBay × 仕入元 突合せ (サイズ・色) — 2026-10-02 の取下げ漏れ3件を再現して確かめる."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import audit_buyable_vs_supplier as A  # noqa: E402

NOW = datetime(2026, 10, 2, 9, 0)
FRESH = "2026/10/02 3:03"
OLD = "2026/08/24 11:01"


def _row(row, size, color, supplier, chk=FRESH):
    return {"row": row, "size": size, "color": color, "supplier": supplier, "chk": chk}


def _kinds(found):
    return sorted((f["kind"], f["slot"]) for f in found)


def test_color_keys_absorb_notation():
    assert {"BK", "BLACK"} <= A.color_keys("Black(BK)")
    assert "BLACK" in A.color_keys("09 BLACK")
    assert "RDBR" in A.color_keys("Red")          # モンベル RED = RDBR (2026-05-14 ユーザー確認)


def test_jp_size():
    assert A.jp_size("US S(JP M)") == "M"
    assert A.jp_size("JP L") == "L"
    assert A.jp_size("US 2XL(JP 3XL)") == "3XL"
    assert A.jp_size("Montbell Thunder Pass Jacket US L (JP XL) Red") == "XL"


def test_single_listing_with_vanished_color_is_danger():
    """① サンダーパス RED: 単品。古い L 行 (8/24) は使わず、XL の行で判定する."""
    item = {"iid": "357100759244", "title": "Thunder Pass Jacket US L (JP XL) Red",
            "status": "Active", "avail": 1, "color": "Red", "size": "L", "variations": []}
    rows = [_row(613, "L", "RDBR", "◎", OLD), _row(616, "XL", "RDBR", "✕")]
    assert _kinds(A.classify_listing(item, rows, NOW)) == [("danger", "XL / Red")]


def test_size_only_variations_use_listing_color_only():
    """② EVANGELION: 出品は Navy。同じ SKU の OFF WHITE ◎ 行に引きずられず、Navy ✕ で danger."""
    item = {"iid": "358711287999", "title": "Evangelion Tee Navy", "status": "Active",
            "color": "Navy", "variations": [
                {"spec": {"Sizes": "US S(JP M)"}, "avail": 1},
                {"spec": {"Sizes": "US XS(JP S)"}, "avail": 0}]}
    rows = [_row(705, "M", "OFF WHITE", "◎"), _row(719, "M", "NAVY", "✕"),
            _row(718, "S", "NAVY", "✕")]
    found = A.classify_listing(item, rows, NOW)
    assert _kinds(found) == [("danger", "M / Navy")]      # 残り 0 の S は対象外
    assert found[0]["rows"] == [719]


def test_size_and_color_variations_and_gap():
    """③ 色ごと: 対応する行が無い色は gap (監視されていない枠)."""
    item = {"iid": "357849150249", "title": "Puff Tech Vest", "status": "Active", "color": "",
            "variations": [
                {"spec": {"Sizes": "US S(JP M)", "Color": "Black"}, "avail": 1},
                {"spec": {"Sizes": "US S(JP M)", "Color": "Navy"}, "avail": 1}]}
    rows = [_row(18, "M", "BLACK", "◎")]
    assert _kinds(A.classify_listing(item, rows, NOW)) == [("gap", "M / Navy")]


def test_conflicting_rows_for_same_slot_are_ambiguous_not_hidden():
    item = {"iid": "1", "title": "t", "status": "Active", "color": "",
            "variations": [{"spec": {"Sizes": "JP L", "Color": "DGY"}, "avail": 1}]}
    rows = [_row(554, "L", "DGY", "✕"), _row(555, "L", "DGY", "◎")]
    assert _kinds(A.classify_listing(item, rows, NOW)) == [("ambiguous", "L / DGY")]


def test_stale_row_is_reported():
    item = {"iid": "1", "title": "t", "status": "Active", "color": "",
            "variations": [{"spec": {"Sizes": "JP L", "Color": "BK"}, "avail": 1}]}
    rows = [_row(1, "L", "BK", "◎", "2026/10/01 01:00")]
    assert _kinds(A.classify_listing(item, rows, NOW)) == [("stale", "L / BK")]


def test_ended_listing_is_ignored():
    item = {"iid": "1", "title": "t", "status": "Completed", "avail": 1, "variations": []}
    assert A.classify_listing(item, [_row(1, "L", "BK", "✕")], NOW) == []


def test_size_only_with_different_color_name_uses_the_one_color_and_asks_once():
    """② eBay は Beige、仕入元は NATURAL の 1 色だけ → NATURAL で判定し、色の確認を 1 回だけ出す."""
    item = {"iid": "358723727015", "title": "Naruto Tee Beige", "status": "Active", "color": "Beige",
            "variations": [{"spec": {"Sizes": "US S(JP M)"}, "avail": 1},
                           {"spec": {"Sizes": "US M(JP L)"}, "avail": 1}]}
    rows = [_row(1, "M", "NATURAL", "◎"), _row(2, "L", "NATURAL", "✕")]
    assert _kinds(A.classify_listing(item, rows, NOW)) == [
        ("color_check", "eBay Beige / 仕入元 NATURAL"), ("danger", "L / Beige")]
