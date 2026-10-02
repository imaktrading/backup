"""実 eBay × 仕入元 (サイズ・色) の判断 — 2026-10-02 の取下げ漏れ・誤復活を再現して確かめる."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ebay_supplier_sync as S  # noqa: E402


def _sup(entries, trusted=()):
    return {"stock": {(frozenset(k), sz): ok for k, sz, ok in entries},
            "trusted_colors": set(trusted), "ok": True}


def test_slots_by_listing_type():
    single = {"ebay_title": "Thunder Pass US L (JP XL) Red", "color": "Red", "avail": 1, "variations": []}
    assert S.ebay_slots(single)[0]["kind"] == 1 and S.ebay_slots(single)[0]["size"] == "XL"
    size_only = {"color": "Navy", "variations": [{"spec": {"Sizes": "US S(JP M)"}, "avail": 1}]}
    s = S.ebay_slots(size_only)[0]
    assert (s["kind"], s["size"], s["color"]) == (2, "M", "Navy")
    both = {"variations": [{"spec": {"Sizes": "US S(JP M)", "Color": "BK"}, "avail": 0}]}
    assert S.ebay_slots(both)[0]["kind"] == 3


def test_single_listing_color_vanished_is_zeroed():
    """① サンダーパス RED: 公式に RDBR が無くなった (GP/OC だけ) → 消えた = 0."""
    slot = {"kind": 1, "size": "XL", "color": "Red", "spec": None, "avail": 1}
    sup = _sup([({"GP/OC"}, "XL", True)], trusted={"RDBR"})
    st, _ = S.supplier_state(slot, sup)
    assert st == "vanished" and S.decide(slot, st, 0) == "zero"


def test_size_only_uses_url_color_not_other_color_rows():
    """② EVANGELION: URL の色 (NAVY) で判定。OFF WHITE の在庫に引きずられない."""
    slot = {"kind": 2, "size": "M", "color": "Navy", "spec": {"Sizes": "US S(JP M)"}, "avail": 1}
    sup = _sup([({"69", "NAVY"}, "M", False), ({"01", "OFF WHITE"}, "M", True)], trusted={"69", "NAVY"})
    st, _ = S.supplier_state(slot, sup)
    assert st == "out" and S.decide(slot, st, 0) == "zero"


def test_montbell_regular_size_is_not_confused_with_r_size():
    """③ ウインドブラスト Men's: eBay JP M = 公式 M。M-R の ◎ で戻さない (03:08 の誤復活)."""
    slot = {"kind": 3, "size": "M", "color": "DGN", "spec": {"Sizes": "US S(JP M)", "Color": "DGN"}, "avail": 0}
    sup = _sup([({"DGN"}, "M", False), ({"DGN"}, "M-R", True)])
    st, _ = S.supplier_state(slot, sup)
    assert st == "out" and S.decide(slot, st, 5) == "keep"


def test_restore_needs_two_cycles_in_stock():
    slot = {"kind": 3, "size": "L", "color": "BL", "spec": {}, "avail": 0}
    assert S.decide(slot, "in", 1) == "keep"
    assert S.decide(slot, "in", 2) == "restore"


def test_unknown_color_name_in_size_and_color_listing_is_not_acted_on():
    """③ で色名が仕入元と合わない時は 変えない (名前の不一致で誤って落とさない)."""
    slot = {"kind": 3, "size": "M", "color": "DARK GRAY", "spec": {}, "avail": 1}
    sup = _sup([({"09", "BLACK"}, "M", True)])
    st, why = S.supplier_state(slot, sup)
    assert st == "unknown" and S.decide(slot, st, 0) == "keep"


def test_unreadable_supplier_is_unknown():
    slot = {"kind": 1, "size": "L", "color": "", "spec": None, "avail": 1}
    st, _ = S.supplier_state(slot, {"stock": {}, "trusted_colors": set(), "ok": False})
    assert st == "unknown" and S.decide(slot, st, 0) == "keep"


def test_colorless_supplier_single_size():
    slot = {"kind": 1, "size": "", "color": "", "spec": None, "avail": 1}
    sup = _sup([({"*"}, "*", False)])
    assert S.supplier_state(slot, sup)[0] == "out"


def test_assorted_needs_every_color_in_stock():
    """Assorted (5 Colors Mix) = 全色を 1 枚ずつ。1 色でも ✕ なら ✕ (2026-10-02 ユーザー確認)."""
    slot = {"kind": 3, "size": "S", "color": "Assorted (5 Colors Mix)", "spec": {}, "avail": 3}
    sup = _sup([({"05", "GRAY"}, "S", True), ({"09", "BLACK"}, "S", False), ({"05", "GRAY"}, "4XL", True),
                ({"09", "BLACK"}, "4XL", True)])
    assert S.supplier_state(slot, sup)[0] == "out" and S.decide(slot, "out", 0) == "zero"
    assert S.supplier_state({**slot, "size": "4XL"}, sup)[0] == "in"


# ------------------------------------------------------------------ SKU 詳細シートを eBay の枠に合わせる
NOW = "2026/10/02 11:30"


def _r(row, size, color, sku=""):
    return {"row": row, "size": size, "color": color, "sku": sku}


def test_sheet_adds_rows_for_ebay_colors_missing_from_sheet():
    """③ パフテック: eBay の DARK GRAY が シートに無い → 行を足す (色は仕入元の名前)."""
    sup = _sup([({"08", "DARK GRAY", "08 DARK GRAY"}, "M", True), ({"09", "BLACK", "09 BLACK"}, "M", True)])
    slots = [{"slot": {"kind": 3, "size": "M", "color": "Black", "spec": {}, "avail": 1, "sku": "u1"},
              "sup": sup, "state": "in", "avail": 1},
             {"slot": {"kind": 3, "size": "M", "color": "DARK GRAY", "spec": {}, "avail": 1, "sku": "u2"},
              "sup": sup, "state": "in", "avail": 1}]
    p = S.plan_sheet("357849150249", "Puff Tech", slots, [_r(18, "M", "BLACK", "u1")], NOW)
    assert p["updates"][18] == {"I": "◎", "K": 1, "L": NOW, "V": "対応あり"}
    assert len(p["appends"]) == 1
    new = p["appends"][0]
    assert (new[3], new[5], new[6], new[7], new[8]) == ("357849150249", "u2", "M", "DARK GRAY", "◎")


def test_sheet_marks_other_color_rows_without_ebay_slot():
    """② EVANGELION: 出品は NAVY。OFF WHITE の行は消さずに「eBay に対応なし」."""
    sup = _sup([({"69", "NAVY"}, "M", False), ({"01", "OFF WHITE"}, "M", True)], trusted={"69", "NAVY"})
    slots = [{"slot": {"kind": 2, "size": "M", "color": "Navy", "spec": {}, "avail": 0, "sku": "d1"},
              "sup": sup, "state": "out", "avail": 0}]
    p = S.plan_sheet("358711287999", "Eva", slots, [_r(705, "M", "OFF WHITE"), _r(719, "M", "NAVY")], NOW)
    assert p["updates"][719]["I"] == "✕" and p["updates"][719]["K"] == 0
    assert p["updates"][705] == {"V": "eBay に対応なし"} and p["orphans"] == [705]
    assert p["appends"] == []


def test_sheet_unknown_state_does_not_overwrite_supplier_mark():
    sup = {"stock": {}, "trusted_colors": set(), "ok": False}
    slots = [{"slot": {"kind": 1, "size": "XL", "color": "Red", "spec": None, "avail": 1, "sku": "x"},
              "sup": sup, "state": "unknown", "avail": 1}]
    p = S.plan_sheet("1", "t", slots, [_r(616, "XL", "RDBR")], NOW)
    assert "I" not in p["updates"][616] and p["updates"][616]["K"] == 1


def test_sheet_duplicate_rows_for_one_slot_are_marked():
    sup = _sup([({"BK"}, "M", True)])
    slots = [{"slot": {"kind": 3, "size": "M", "color": "BK", "spec": {}, "avail": 1, "sku": "s"},
              "sup": sup, "state": "in", "avail": 1}]
    p = S.plan_sheet("1", "t", slots, [_r(245, "M", "BK"), _r(300, "M", "BK")], NOW)
    assert p["updates"][245]["V"] == "対応あり"
    assert p["updates"][300] == {"V": "重複 (同じ eBay 枠に複数行)"}
