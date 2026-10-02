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
