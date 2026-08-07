"""復活 (qty=1) upload の失敗注入 test (2026-08-07 revive_qty1_impl 完了条件 1).

依頼書 完了条件 1 「失敗注入テスト: revise が失敗した時に「未復活=要対応」として
明示され、silent drop しないこと。 1件でも漏れたらレポートを「⚠️要対応」にする」。

_verify_qty_gt_zero が verify NG (qty=0 のまま or API 失敗) を返した時、
upload_csv_via_trading_api の結果が success=False として反映されること。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ebay_actions import trading_api_uploader as TAU  # noqa: E402


def _write_revive_csv(tmp_path: Path, item_id: str = "IID_TEST") -> Path:
    """qty=1 の単行 CSV を tmp に書く (FileExchange 形式)。"""
    p = tmp_path / "revive_test.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        w.writerow(TAU._parse_csv_rows.__doc__.splitlines()[0:0] or [
            "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
            "ItemID", "*Quantity",
        ])
        w.writerow(["Revise", item_id, "1"])
    return p


def test_revive_upload_verify_failure_marks_success_false(monkeypatch, tmp_path):
    """revive の verify が qty=0 のまま → success=False (silent drop 禁止)。"""
    csv_path = _write_revive_csv(tmp_path, "IID_REVIVE_FAIL")

    # token load を skip (ダミーを返す)
    monkeypatch.setattr(TAU, "load_access_token", lambda: "DUMMY_TOKEN")

    # revise_inventory_status: ack=Success を返す (revise 自体は成功)
    def _fake_revise(iid, qty, access_token=None):
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None}
    monkeypatch.setattr(TAU, "revise_inventory_status", _fake_revise)

    # _call_trading (GetItem): available=0 (= qty=0 のまま) を返す
    #   → _verify_qty_gt_zero は verified=False, observed_qty=0 を返す
    fake_xml = "<Quantity>1</Quantity><QuantitySold>1</QuantitySold>"
    monkeypatch.setattr(TAU, "_call_trading",
                        lambda op, body, access_token=None, raw_xml_cap=None: {
                            "success": True, "ack": "Success",
                            "error_code": None, "raw_xml": fake_xml,
                        })
    # in-cycle retry を待たせない (test 高速化)
    monkeypatch.setattr(TAU, "INCYCLE_RETRY_INTERVALS_SEC", [0.0, 0.0, 0.0])
    monkeypatch.setattr(TAU.time, "sleep", lambda s: None)

    result = TAU.upload_csv_via_trading_api(csv_path, dry_run=False, pacing_sec=0)

    # ★ success=False で計上され (silent drop 禁止)、 ng=1 になること
    assert result["success"] is False, "revive verify NG が silent drop された (要対応化されず)"
    assert result["total"] == 1
    assert result["ng"] == 1
    assert result["ok"] == 0
    # results entry に verified=False が乗っていること (要対応判定のための入力)
    entry = result["results"][0]
    assert entry["success"] is False
    assert entry.get("verified") is False
    assert entry.get("verify_qty") == 0


def test_revive_upload_verify_success_marks_success_true(monkeypatch, tmp_path):
    """revive の verify で available>0 が返れば success=True (通常 path)。"""
    csv_path = _write_revive_csv(tmp_path, "IID_REVIVE_OK")

    monkeypatch.setattr(TAU, "load_access_token", lambda: "DUMMY_TOKEN")

    def _fake_revise(iid, qty, access_token=None):
        return {"success": True, "ack": "Success", "error_code": None,
                "error_message": None}
    monkeypatch.setattr(TAU, "revise_inventory_status", _fake_revise)

    # GetItem: Quantity=1 sold=0 → available=1 (>0) = revive 成功
    fake_xml = "<Quantity>1</Quantity><QuantitySold>0</QuantitySold>"
    monkeypatch.setattr(TAU, "_call_trading",
                        lambda op, body, access_token=None, raw_xml_cap=None: {
                            "success": True, "ack": "Success",
                            "error_code": None, "raw_xml": fake_xml,
                        })
    monkeypatch.setattr(TAU, "INCYCLE_RETRY_INTERVALS_SEC", [0.0, 0.0, 0.0])
    monkeypatch.setattr(TAU.time, "sleep", lambda s: None)

    result = TAU.upload_csv_via_trading_api(csv_path, dry_run=False, pacing_sec=0)
    assert result["success"] is True
    assert result["ok"] == 1
    assert result["ng"] == 0
    entry = result["results"][0]
    assert entry["verified"] is True
    assert entry.get("verify_qty") == 1


def test_revive_upload_revise_api_failure_marks_success_false(monkeypatch, tmp_path):
    """revise 自体が失敗 (Failure) → success=False。"""
    csv_path = _write_revive_csv(tmp_path, "IID_REVISE_FAIL")

    monkeypatch.setattr(TAU, "load_access_token", lambda: "DUMMY_TOKEN")

    def _fake_revise(iid, qty, access_token=None):
        return {"success": False, "ack": "Failure",
                "error_code": "12345", "error_message": "Something broke"}
    monkeypatch.setattr(TAU, "revise_inventory_status", _fake_revise)

    monkeypatch.setattr(TAU, "INCYCLE_RETRY_INTERVALS_SEC", [0.0, 0.0, 0.0])
    monkeypatch.setattr(TAU.time, "sleep", lambda s: None)

    result = TAU.upload_csv_via_trading_api(csv_path, dry_run=False, pacing_sec=0)
    assert result["success"] is False
    assert result["ng"] == 1
    entry = result["results"][0]
    assert entry["success"] is False
    assert entry["ack"] == "Failure"
