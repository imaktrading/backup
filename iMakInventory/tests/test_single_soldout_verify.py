"""sold-out 単品 listing の verify 偽滞留 regression (2026-06-22).

bug: 単品 verify の GetItem が raw_xml_cap=2000 で呼ばれ、 <QuantitySold> が
SellingStatus 内で 2000 字より後ろ (実測 pos≈3669) に来るため取りこぼし → sold=0 と
誤算 → available = Quantity(1) - 0 = 1 と過大評価。 結果、 Quantity=1/QuantitySold=1 で
実 available=0 の sold-out 単品 (= 購入不可) を永久に qty_gt0 と誤判定 → verify_qty_gt0_giveup
= 偽「滞留」spam。 iid=358251931733 (2026-05-13 売却済 Active listing) が amazon 源切れ flag で
~18h 偽滞留 → 09:30 cycle で ⚠️要対応 誤報。

修正: 単品 verify も raw_xml_cap=None で GetItem 全文取得し QuantitySold を確実に読む
(variation 経路は既に cap 解除済)。 cap を尊重する mock で 修正前は fail / 修正後は pass。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ebay_actions.trading_api_uploader as up  # noqa: E402


def _write_single_csv(tmp_path, item_id):
    p = tmp_path / "revise.csv"
    p.write_text(
        '"*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","*Quantity"\n'
        f'"Revise","{item_id}","0"\n',
        encoding="utf-8",
    )
    return p


def _full_xml(quantity, sold):
    """QuantitySold を 2000 字より後ろに置いた GetItem 全文 (= 本番の構造を模す)."""
    padding = "<Description>" + ("x" * 3000) + "</Description>"
    return (
        "<Item><ListingStatus>Active</ListingStatus>"
        f"<Quantity>{quantity}</Quantity>"
        f"{padding}"
        f"<SellingStatus><QuantitySold>{sold}</QuantitySold>"
        "<ListingStatus>Active</ListingStatus></SellingStatus></Item>"
    )


def _make_fake_call_trading(quantity, sold, capture):
    full = _full_xml(quantity, sold)

    def fake_call_trading(call, body, **kw):
        cap = kw.get("raw_xml_cap", 2000)
        capture.append(cap)
        raw = full if cap is None else full[:cap]
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None, "raw_xml": raw}

    return fake_call_trading


def test_soldout_single_redundant_revise_verifies_zero(tmp_path, monkeypatch):
    """Quantity=1/QuantitySold=1 (available=0) の sold-out 単品が verified=True で drain 対象。

    修正前 (cap=2000) は QuantitySold 取りこぼしで available=1 → verified=False → fail。
    """
    csv_path = _write_single_csv(tmp_path, "358251931733")
    capture = []

    def fake_revise(item_id, qty, **kw):
        # 実 eBay 応答: available 既に 0 → "redundant" warning (success=True)
        return {"success": True, "ack": "Warning", "error_code": "21917092",
                "error_message": "Requested Quantity revision is redundant."}

    monkeypatch.setattr(up, "revise_inventory_status", fake_revise)
    monkeypatch.setattr(up, "_call_trading",
                        _make_fake_call_trading(1, 1, capture))
    monkeypatch.setattr(up, "load_access_token", lambda: "tok")
    monkeypatch.setattr(up.time, "sleep", lambda *_a, **_k: None)

    res = up.upload_csv_via_trading_api(csv_path, dry_run=False)

    entry = res["results"][0]
    assert entry["success"] is True, f"verify_msg={entry.get('verify_msg')}"
    assert entry["verified"] is True
    assert entry["verify_qty"] == 0
    # verify GetItem は cap 解除 (None) で呼ばれること (= 回帰防止の核心)
    assert None in capture, f"GetItem caps used = {capture} (cap=None で呼ばれていない)"


def test_genuine_instock_single_still_flags(tmp_path, monkeypatch):
    """Quantity=1/QuantitySold=0 (available=1) の在庫残存は従来どおり success=False。"""
    csv_path = _write_single_csv(tmp_path, "111222333444")
    capture = []

    def fake_revise(item_id, qty, **kw):
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None}

    monkeypatch.setattr(up, "revise_inventory_status", fake_revise)
    monkeypatch.setattr(up, "_call_trading",
                        _make_fake_call_trading(1, 0, capture))
    monkeypatch.setattr(up, "load_access_token", lambda: "tok")
    monkeypatch.setattr(up.time, "sleep", lambda *_a, **_k: None)

    res = up.upload_csv_via_trading_api(csv_path, dry_run=False)

    entry = res["results"][0]
    assert entry["success"] is False
    assert entry["verified"] is False
