"""終了済 (Completed) listing の verify safe 扱い regression (2026-06-17).

bug: revise が 21916750 "FixedPrice item ended" を返す (= safe_failure 済) のに、
その後の in-cycle verify が 終了 listing に残る <Quantity>=1 を読み available=1 と誤判定
→ verified=False → 永久「未取下げ/滞留」spam。 357181571869 (2026-05-18 終了済 Qty1/Sold0)
が 12.5h 滞留 = 偽 fail-OPEN。 終了 listing は購入不可なので safe_failure は verify 通過扱いにする。
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


def test_ended_listing_revise_21916750_is_verified_safe(tmp_path, monkeypatch):
    """revise が ended (21916750) → verify が Qty1 残でも success=True/verified=True。"""
    csv_path = _write_single_csv(tmp_path, "357181571869")

    def fake_revise(item_id, qty, **kw):
        return {"success": False, "ack": "Failure", "error_code": "21916750",
                "error_message": "FixedPrice item ended."}

    # GetItem が呼ばれたら終了 listing (Quantity=1/Sold=0 が残存) を返す。
    # safe_failure 短絡が効いていれば GetItem 自体呼ばれないはず (= verify skip)。
    getitem_called = {"n": 0}

    def fake_call_trading(call, body, **kw):
        getitem_called["n"] += 1
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None,
                "raw_xml": "<Item><ListingStatus>Completed</ListingStatus>"
                           "<Quantity>1</Quantity><QuantitySold>0</QuantitySold></Item>"}

    monkeypatch.setattr(up, "revise_inventory_status", fake_revise)
    monkeypatch.setattr(up, "_call_trading", fake_call_trading)
    monkeypatch.setattr(up, "load_access_token", lambda: "tok")
    monkeypatch.setattr(up.time, "sleep", lambda *_a, **_k: None)

    res = up.upload_csv_via_trading_api(csv_path, dry_run=False)

    assert res["total"] == 1
    assert res["ok"] == 1 and res["ng"] == 0
    entry = res["results"][0]
    assert entry["success"] is True
    assert entry["verified"] is True
    assert entry["verify_msg"] == "safe_failure_21916750"
    # ended は safe 確定なので GetItem verify は呼ばれない (無駄 API 回避 + 偽 NG 撲滅)
    assert getitem_called["n"] == 0


def test_genuine_failure_still_flags_action_required(tmp_path, monkeypatch):
    """ended でない本物の qty>0 残存は従来どおり success=False (回帰防止)。"""
    csv_path = _write_single_csv(tmp_path, "111222333444")

    def fake_revise(item_id, qty, **kw):
        # ack=Success だが実際は反映されないケース (silent fail)
        return {"success": True, "ack": "Success", "error_code": None, "error_message": None}

    def fake_call_trading(call, body, **kw):
        # Active で qty=1 残存 = 取下げ未反映 = 本物の要対応
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None,
                "raw_xml": "<Item><ListingStatus>Active</ListingStatus>"
                           "<Quantity>1</Quantity><QuantitySold>0</QuantitySold></Item>"}

    monkeypatch.setattr(up, "revise_inventory_status", fake_revise)
    monkeypatch.setattr(up, "_call_trading", fake_call_trading)
    monkeypatch.setattr(up, "load_access_token", lambda: "tok")
    monkeypatch.setattr(up.time, "sleep", lambda *_a, **_k: None)

    res = up.upload_csv_via_trading_api(csv_path, dry_run=False)

    entry = res["results"][0]
    assert entry["success"] is False
    assert entry["verified"] is False
