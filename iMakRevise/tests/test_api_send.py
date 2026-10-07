"""API 送信 (send_plan / verify_sample) と run_daily の Chrome への戻り. eBay には送らない."""
from pathlib import Path
from types import SimpleNamespace

from revise.api_revise import ApiPlan, PriceChange, ShippingChange, send_plan, verify_sample

OK = "<ReviseInventoryStatusResponse><Ack>Success</Ack></ReviseInventoryStatusResponse>"
NG = "<R><Ack>Failure</Ack><LongMessage>bad</LongMessage></R>"


def _plan():
    return ApiPlan(prices=[PriceChange(str(i), 10.0 + i) for i in range(5)],
                   shippings=[ShippingChange("9", "DDP-A-P10", "123")])


def test_all_success_counts_calls():
    calls = []
    r = send_plan(_plan(), call_fn=lambda n, x: calls.append(n) or OK, sleep_fn=lambda s: None)
    assert r == {"calls": 3, "failed": []}  # 値段 4+1 件 → 2呼出 + 送料1
    assert calls == ["ReviseInventoryStatus", "ReviseInventoryStatus", "ReviseFixedPriceItem"]


def test_failure_retried_once_then_reported():
    seq = iter([NG, OK, NG, NG, OK])
    r = send_plan(_plan(), call_fn=lambda n, x: next(seq), sleep_fn=lambda s: None)
    assert len(r["failed"]) == 1 and r["failed"][0]["errors"] == ["bad"]


def test_exception_is_failure_not_crash():
    def boom(n, x):
        raise TimeoutError("t")
    r = send_plan(_plan(), call_fn=boom, sleep_fn=lambda s: None)
    assert len(r["failed"]) == 3


def test_verify_sample_detects_mismatch():
    plan = _plan()
    got = {"0": 10.0, "1": 99.0}
    bad = verify_sample(plan, get_fn=lambda i: {"current_price_usd": got.get(i, float(i) + 10)}, n=3)
    assert bad == [("1", 11.0, 99.0)]


def test_run_daily_falls_back_to_chrome_when_api_fails(monkeypatch, tmp_path):
    import revise.run_daily as rd
    csv = tmp_path / "revise_combined_20261002_043000.csv"
    csv.write_text("x", encoding="utf-8")
    result = SimpleNamespace(csv_path=str(csv), var_price_path=None, var_shipping_path=None,
                             revisable=[], abnormal=[], skipped=[])
    monkeypatch.setattr("revise.price_revise.run_price_revise", lambda **kw: result)
    monkeypatch.setattr(rd, "_upload_mode", lambda: "api")
    monkeypatch.setattr(rd, "_upload_via_api", lambda r, t: None)  # API 失敗
    chrome = []
    monkeypatch.setattr(rd, "_upload_one", lambda p, l, dry_run: chrome.append(Path(p).name) or
                        {"label": l, "csv": Path(p).name, "success": True, "attempts": 1, "error": None})
    monkeypatch.setattr(rd, "_send_summary", lambda *a, **k: 0)
    monkeypatch.setattr(rd, "_log", lambda line: None)
    assert rd.run_daily(dry_run=False) == 0
    assert chrome == [csv.name]


def test_run_daily_uses_api_and_skips_chrome(monkeypatch, tmp_path):
    import revise.run_daily as rd
    csv = tmp_path / "revise_combined_20261002_043000.csv"
    csv.write_text("x", encoding="utf-8")
    result = SimpleNamespace(csv_path=str(csv), var_price_path=None, var_shipping_path=None,
                             revisable=[], abnormal=[], skipped=[])
    monkeypatch.setattr("revise.price_revise.run_price_revise", lambda **kw: result)
    monkeypatch.setattr(rd, "_upload_mode", lambda: "api")
    monkeypatch.setattr(rd, "_upload_via_api", lambda r, t: [{"label": "single (API)", "csv": csv.name,
                                                             "success": True, "attempts": 1, "error": None}])
    monkeypatch.setattr(rd, "_upload_one", lambda *a, **k: (_ for _ in ()).throw(AssertionError("chrome used")))
    monkeypatch.setattr(rd, "_send_summary", lambda *a, **k: 0)
    monkeypatch.setattr(rd, "_log", lambda line: None)
    assert rd.run_daily(dry_run=False) == 0


def test_price_moves_written_all_rows_both_directions(tmp_path):
    import json
    import revise.run_daily as rd
    C = lambda i, cur, new, sheet="HIGH": SimpleNamespace(item_id=i, source_sheet=sheet, category="TCG",
                                                         current_usd=cur, new_usd=new, title="t")
    result = SimpleNamespace(revisable=[C(f"u{i}", 10.0, 11.0 + i) for i in range(12)]
                             + [C("down", 492.98, 200.98, "LOW"), C("same", 50.0, 50.0)])
    out = tmp_path / "m.json"
    rd._write_price_moves(result, [{"success": True}], out=out)
    d = json.loads(out.read_text(encoding="utf-8"))
    ids = [x["item_id"] for x in d["items"]]
    assert len(ids) == 13 and ids[0] == "down" and "same" not in ids
    assert d["items"][0]["diff_usd"] == -292.0 and d["items"][0]["sheet"] == "LOW" and d["sent_ok"] is True


def test_snapshot_reader_returns_shipping_profile(tmp_path):
    from revise.snapshot_reader import load_snapshot
    p = tmp_path / "ebay_active_2026-10-07_043309.csv"
    p.write_text("Item number,Title,Currency,Current price,Listing site,Available quantity,Shipping profile name\n"
                 "111,t,USD,10.98,US,1,DDP-A-P09\n222,t,USD,5.98,US,1,\n", encoding="utf-8")
    m = load_snapshot(p)
    assert m["111"]["shipping_profile_name"] == "DDP-A-P09" and m["222"]["shipping_profile_name"] is None


def test_restock_hold_row_is_skipped_and_reported():
    from revise.price_revise import COL_FLG_Q, COL_ITEM_ID, COL_N_PRICE, detect_candidates
    def row(item, q=""):
        r = [""] * 40
        r[COL_ITEM_ID] = item
        r[COL_N_PRICE] = "5000"
        r[COL_FLG_Q] = q
        return r
    held = []
    cands = detect_candidates([row("A"), row("B", "補充保留"), row("C", "x 補充保留 y")], hold_out=held)
    assert [c.item_id for c in cands] == ["A"] and held == ["B", "C"]
