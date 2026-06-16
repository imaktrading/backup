"""Multi-SKU 取下げ fallback の regression (2026-06-16).

構造バグ: 通常 cycle の revise_csv_generator は単行 (3列) CSV のみ生成 = variation 非対応。
Multi-SKU listing に投げると eBay が 21916736 で拒否 → pending 永久滞留 = fail-OPEN
(2026-06-16 HIGH row55 鬼滅 UT Tシャツ XXL が 8.5h 滞留 / eBay qty=1 live で発覚)。

修正: uploader が 21916736 を検出したら GetItem で variation 列挙 → qty>0 variation を
全て qty=0 化 → 再 GetItem で全 variation available=0 を verify する fallback を追加。

本 test は failure injection 含む:
- 正常系: XXL だけ qty>0 → 取下げ → 全 0 verify → verified=True
- 失敗系: revise しても再 GetItem で qty>0 残存 → verified=False (= fail-OPEN を success と
  誤報告しない = silent drop 禁止原則の担保)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ebay_actions.trading_api_uploader as up  # noqa: E402


def _variation(size, qty, sold):
    return (
        "<Variation><SKU>sku-x</SKU>"
        f"<Quantity>{qty}</Quantity>"
        "<VariationSpecifics>"
        f"<NameValueList><Name>Sizes</Name><Value>{size}</Value></NameValueList>"
        "</VariationSpecifics>"
        f"<SellingStatus><QuantitySold>{sold}</QuantitySold></SellingStatus>"
        "</Variation>"
    )


# 7 サイズ、 XXL だけ qty=1 (= 仕入れていたサイズ)、 他は既に 0
_SIZES = ["US XS(JP S)", "US S(JP M)", "US M(JP L)", "US L(JP XL)",
          "US XL(JP XXL)", "US 2XL(JP 3XL)", "US 3XL(JP 4XL)"]


def _listing_xml(active_size):
    parts = []
    for s in _SIZES:
        parts.append(_variation(s, 1 if s == active_size else 0, 0))
    return "<Variations>" + "".join(parts) + "</Variations>"


def test_enumerate_variations_parses_available():
    xml = _listing_xml("US XL(JP XXL)")
    vs = up._enumerate_variations(xml)
    assert len(vs) == 7
    active = [(sp["Sizes"], av) for sp, av in vs if av > 0]
    assert active == [("US XL(JP XXL)", 1)]


def test_multisku_fallback_zeroes_active_variation(monkeypatch):
    """XXL qty=1 → 取下げ → 再 GetItem 全 0 → verified=True / zeroed=1."""
    state = {"xxl_qty": 1, "getitem_calls": 0}

    def fake_getitem(call, body, **kw):
        state["getitem_calls"] += 1
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None,
                "raw_xml": _listing_xml("US XL(JP XXL)") if state["xxl_qty"] > 0
                else "<Variations>" + "".join(_variation(s, 0, 0) for s in _SIZES) + "</Variations>"}

    def fake_revise_var(item_id, specifics, qty, **kw):
        assert specifics == {"Sizes": "US XL(JP XXL)"}
        assert qty == 0
        state["xxl_qty"] = 0   # 取下げ反映
        return {"success": True, "ack": "Success", "error_code": None, "error_message": None}

    monkeypatch.setattr(up, "_call_trading", fake_getitem)
    monkeypatch.setattr(up, "revise_inventory_status_variation", fake_revise_var)
    monkeypatch.setattr(up.time, "sleep", lambda *_a, **_k: None)

    r = up._revise_multisku_to_zero("357358563233", token="t")
    assert r["success"] is True
    assert r["verified"] is True
    assert r["verify_qty"] == 0
    assert r["zeroed"] == 1 and r["attempted"] == 1


def test_multisku_fallback_failopen_not_reported_success(monkeypatch):
    """revise が API 成功を返しても 再 GetItem で qty>0 残存 → verified=False。

    = 取下げ未反映を 'success' と誤報告しない (fail-OPEN 防止 / silent drop 禁止)。
    """
    def fake_getitem(call, body, **kw):
        # revise しても qty が下がらない状況を再現 (= 取下げ未反映)
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None, "raw_xml": _listing_xml("US XL(JP XXL)")}

    def fake_revise_var(item_id, specifics, qty, **kw):
        return {"success": True, "ack": "Success", "error_code": None, "error_message": None}

    monkeypatch.setattr(up, "_call_trading", fake_getitem)
    monkeypatch.setattr(up, "revise_inventory_status_variation", fake_revise_var)
    monkeypatch.setattr(up.time, "sleep", lambda *_a, **_k: None)

    r = up._revise_multisku_to_zero("357358563233", token="t")
    assert r["success"] is False
    assert r["verified"] is False
    assert r["verify_qty"] == 1   # XXL が残ったまま


def test_multisku_fallback_item_not_found_is_safe(monkeypatch):
    """GetItem が err 17 (Item not found / ended) → qty=0 同等 safe 扱い."""
    def fake_getitem(call, body, **kw):
        return {"success": False, "ack": "Failure", "error_code": "17",
                "error_message": "Item not found", "raw_xml": ""}

    monkeypatch.setattr(up, "_call_trading", fake_getitem)
    monkeypatch.setattr(up.time, "sleep", lambda *_a, **_k: None)

    r = up._revise_multisku_to_zero("999", token="t")
    assert r["success"] is True and r["verified"] is True
    assert r["verify_msg"] == "err_17_safe"


def test_multisku_fallback_already_all_zero(monkeypatch):
    """全 variation が既に 0 → 取下げ不要、 verified=True / zeroed=0."""
    def fake_getitem(call, body, **kw):
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None,
                "raw_xml": "<Variations>" + "".join(_variation(s, 0, 0) for s in _SIZES) + "</Variations>"}

    monkeypatch.setattr(up, "_call_trading", fake_getitem)
    monkeypatch.setattr(up.time, "sleep", lambda *_a, **_k: None)

    r = up._revise_multisku_to_zero("357358563233", token="t")
    assert r["success"] is True and r["zeroed"] == 0
    assert r["verify_msg"] == "already_all_zero"
