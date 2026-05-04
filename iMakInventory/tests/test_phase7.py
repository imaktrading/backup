"""Phase 7 unit test (precheck + audit + listing_verifier).

Selenium / network を呼ぶ部分はスキップ、helpers のみ pytest 化。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# 7a: pytest precheck 関連
# ============================================================================
def test_run_cycle_has_precheck_phase():
    """run_cycle._phase_pytest_precheck 関数が存在する."""
    import run_cycle
    assert hasattr(run_cycle, "_phase_pytest_precheck")
    assert callable(run_cycle._phase_pytest_precheck)


def test_pytest_ini_has_offline_marker():
    """pytest.ini に offline / live marker が登録されている."""
    pytest_ini = ROOT / "pytest.ini"
    assert pytest_ini.exists()
    content = pytest_ini.read_text(encoding="utf-8")
    assert "offline:" in content
    assert "live:" in content


# ============================================================================
# 7d': audit
# ============================================================================
def test_audit_imports():
    """audit module が import 可能."""
    import audit
    assert callable(audit.sample_and_append)
    assert callable(audit.collect_in_stock_from_log)
    assert callable(audit.find_latest_listings_log)
    assert audit.AUDIT_TAB_NAME == "audit"
    assert "cycle_ts" in audit.AUDIT_HEADERS


def test_audit_collect_in_stock_from_log(tmp_path):
    """jsonl を読んで in_stock のみ抽出."""
    from audit import collect_in_stock_from_log
    log = tmp_path / "listings_TEST_20260430.jsonl"
    rows = [
        # in_stock 2 件
        {"row_index": 1, "item_id": "111", "is_sold": False, "url": "u1",
         "title": "t1", "supplier": "mercari", "raw_status": "ON_SALE", "error": None},
        {"row_index": 2, "item_id": "222", "is_sold": False, "url": "u2",
         "title": "t2", "supplier": "amazon", "raw_status": "in_stock", "error": None},
        # sold 1 件 (除外)
        {"row_index": 3, "item_id": "333", "is_sold": True, "url": "u3",
         "title": "t3", "supplier": "mercari", "raw_status": "SOLD_OUT", "error": None},
        # error 1 件 (除外)
        {"row_index": 4, "item_id": "444", "is_sold": None, "url": "u4",
         "title": "t4", "supplier": "amazon", "raw_status": "", "error": "fail"},
    ]
    with open(log, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    items = collect_in_stock_from_log(log)
    assert len(items) == 2
    assert {i["item_id"] for i in items} == {"111", "222"}


def test_audit_find_latest_listings_log(tmp_path):
    """find_latest_listings_log が最新 mtime ファイルを返す."""
    from audit import find_latest_listings_log
    # 古い + 新しい
    old = tmp_path / "listings_TEST_20260101_120000.jsonl"
    new = tmp_path / "listings_TEST_20260430_120000.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    time.sleep(0.05)
    new.write_text("{}\n", encoding="utf-8")
    # 別ラベル (除外されるべき)
    other = tmp_path / "listings_OTHER_20260430_120000.jsonl"
    other.write_text("{}\n", encoding="utf-8")

    found = find_latest_listings_log(tmp_path, "TEST")
    assert found == new
    found_other = find_latest_listings_log(tmp_path, "NOTEXIST")
    assert found_other is None


# ============================================================================
# 7d'-fix (2026-05-04): append_rows 不具合 → 明示 update への置換 regression test
# ============================================================================
def test_audit_explicit_update_used_not_append_rows(tmp_path, monkeypatch):
    """sample_and_append が ws.update (range 指定) を呼び、append_rows は呼ばない.

    背景: append_rows は初回 add_worksheet(rows=100) の空セル領域と相性悪く、
    API 200 OK でも実書込されない症状で 12 cycle 分の audit データが消失。
    確実な ws.update(range=...) 方式に置換した (audit.py 2026-05-04)。
    """
    from unittest.mock import MagicMock
    import audit

    # 入力 listings ログ作成 (in_stock 2 件)
    log = tmp_path / "listings_TEST_20260504.jsonl"
    with open(log, "w", encoding="utf-8") as f:
        for i in (1, 2):
            f.write(json.dumps({
                "row_index": i, "item_id": f"id{i}", "is_sold": False,
                "url": f"u{i}", "title": "", "supplier": "mercari",
                "raw_status": "ON_SALE", "error": None,
            }) + "\n")

    # ws モック: 既存 audit に header + 5 行データ (= 5/2 5:30 cycle 分相当)
    ws = MagicMock()
    ws.id = 999
    ws.row_count = 100
    ws.title = "audit"
    existing = [audit.AUDIT_HEADERS]
    existing += [["2026-05-02 5:30", str(i), f"old{i}", f"u{i}", "IN_STOCK", "", ""]
                 for i in range(1, 6)]
    ws.get_all_values = MagicMock(return_value=existing)

    sh = MagicMock()
    sh.worksheets = MagicMock(return_value=[ws])
    monkeypatch.setattr(audit, "open_sheet_by_id", lambda sid: sh)

    res = audit.sample_and_append(
        sheet_id="dummy", sheet_label="TEST",
        decision_log_dir=tmp_path, cycle_ts="2026-05-04 9:30",
        n=2, seed=42,
    )

    # append_rows は呼ばれない (修正で update に置換)
    ws.append_rows.assert_not_called()
    # update は呼ばれる
    assert ws.update.called, "ws.update が呼ばれていない"

    # update の range は header 直後ではなく「実データ最終行+1」から
    # 既存 6 行 (header + 5 行) の次 → row 7-8 に書込
    call_kwargs = ws.update.call_args.kwargs
    range_name = call_kwargs.get("range_name")
    assert range_name == "A7:G8", f"想定 A7:G8、実際 {range_name}"

    assert res["sampled"] == 2
    assert res["appended"] == 2
    assert res["error"] is None


def test_audit_handles_empty_existing_tab(tmp_path, monkeypatch):
    """既存 audit タブが header のみ (= 初回) でも正しく row 2 から書込."""
    from unittest.mock import MagicMock
    import audit

    log = tmp_path / "listings_TEST_20260504.jsonl"
    with open(log, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "row_index": 1, "item_id": "id1", "is_sold": False,
            "url": "u1", "title": "", "supplier": "mercari",
            "raw_status": "ON_SALE", "error": None,
        }) + "\n")

    ws = MagicMock()
    ws.id = 999
    ws.row_count = 100
    ws.title = "audit"
    # header のみ存在
    ws.get_all_values = MagicMock(return_value=[audit.AUDIT_HEADERS])

    sh = MagicMock()
    sh.worksheets = MagicMock(return_value=[ws])
    monkeypatch.setattr(audit, "open_sheet_by_id", lambda sid: sh)

    res = audit.sample_and_append(
        sheet_id="dummy", sheet_label="TEST",
        decision_log_dir=tmp_path, cycle_ts="2026-05-04 9:30",
        n=1, seed=42,
    )

    range_name = ws.update.call_args.kwargs.get("range_name")
    assert range_name == "A2:G2", f"header 直後 = A2:G2 想定、実際 {range_name}"
    assert res["appended"] == 1


def test_audit_expands_rows_when_exceeded(tmp_path, monkeypatch):
    """row_count 不足時に add_rows で拡張する (将来の安全側)."""
    from unittest.mock import MagicMock
    import audit

    log = tmp_path / "listings_TEST_20260504.jsonl"
    with open(log, "w", encoding="utf-8") as f:
        for i in range(10):
            f.write(json.dumps({
                "row_index": i, "item_id": f"id{i}", "is_sold": False,
                "url": f"u{i}", "title": "", "supplier": "mercari",
                "raw_status": "ON_SALE", "error": None,
            }) + "\n")

    ws = MagicMock()
    ws.id = 999
    ws.row_count = 5  # わざと不足させる
    ws.title = "audit"
    # header + 4 行 = 既存 5 行
    existing = [audit.AUDIT_HEADERS] + [["x"]*7 for _ in range(4)]
    ws.get_all_values = MagicMock(return_value=existing)

    sh = MagicMock()
    sh.worksheets = MagicMock(return_value=[ws])
    monkeypatch.setattr(audit, "open_sheet_by_id", lambda sid: sh)

    res = audit.sample_and_append(
        sheet_id="dummy", sheet_label="TEST",
        decision_log_dir=tmp_path, cycle_ts="2026-05-04 9:30",
        n=5, seed=42,
    )

    # add_rows 呼出済 (row 6-10 に書く必要、row_count=5 だから不足)
    ws.add_rows.assert_called_once()
    assert res["appended"] == 5


# ============================================================================
# 7e: listing_verifier
# ============================================================================
def test_listing_verifier_imports():
    """ebay_actions.listing_verifier が import 可能."""
    from ebay_actions import listing_verifier
    assert callable(listing_verifier.verify_listings)
    assert callable(listing_verifier.get_last_uploaded_item_ids)
    assert callable(listing_verifier._detect_qty_state)
    assert callable(listing_verifier.mark_verified)


def test_listing_verifier_detect_qty_state():
    """HTML パターン → qty 状態 判定."""
    from ebay_actions.listing_verifier import _detect_qty_state
    # ended
    state, hint = _detect_qty_state("foo This listing has ended bar")
    assert state == "ended"
    # qty zero (Out of stock)
    state, hint = _detect_qty_state("Out of stock!")
    assert state == "qty_zero"
    # 在庫切れ JP
    state, hint = _detect_qty_state("商品は在庫切れです")
    assert state == "qty_zero"
    # availability 数字 (qty 5)
    state, hint = _detect_qty_state("12 available; ship now")
    assert state == "qty_positive"
    assert "5" not in hint  # 12 だから
    # availability 数字 (qty 0)
    state, hint = _detect_qty_state("0 in stock")
    assert state == "qty_zero"
    # unknown
    state, hint = _detect_qty_state("random text")
    assert state == "unknown"


def test_detect_qty_state_limited_stock_alone_is_unknown():
    """regression: 'Limited stock' 単独マッチで qty_positive 判定しない (false positive 防止).

    eBay UI の無関係箇所 (sidebar / search / promo) に "Limited stock" 文字列が
    出ても、数値 availability も Add to cart button id も無ければ "unknown"。
    """
    from ebay_actions.listing_verifier import _detect_qty_state
    # 旧バグ再現 HTML: Limited stock 文字列はあるが具体的な qty 数値なし
    html = """
    <html><body>
      <div class="promo">Limited stock available on selected items</div>
      <div class="other">More items from this seller</div>
    </body></html>
    """
    state, hint = _detect_qty_state(html)
    assert state == "unknown", f"expected unknown but got {state} ({hint})"


def test_detect_qty_state_only_left_alone_is_unknown():
    """regression: "Only ... left" 単独マッチでも qty_positive にしない (数値必須)."""
    from ebay_actions.listing_verifier import _detect_qty_state
    # "Only" と "left" の両方が出るが、数値が結合してない
    html = "Only premium sellers can offer this; few items left in similar listings"
    state, hint = _detect_qty_state(html)
    assert state == "unknown"


def test_detect_qty_state_only_n_left_with_number_is_positive():
    """'Only 3 left' のように数値が伴うパターンは qty_positive 維持."""
    from ebay_actions.listing_verifier import _detect_qty_state
    state, hint = _detect_qty_state("Only 3 left in stock")
    assert state == "qty_positive"
    assert "3" in hint


def test_detect_qty_state_priority_ended_over_anything():
    """ended は最優先 (Out of stock 等が同時にあっても ended)."""
    from ebay_actions.listing_verifier import _detect_qty_state
    state, hint = _detect_qty_state(
        "This listing has ended. Out of stock. 5 available."
    )
    assert state == "ended"


def test_detect_qty_state_cart_button_signal():
    """Add to cart button id が active listing の構造シグナル."""
    from ebay_actions.listing_verifier import _detect_qty_state
    html = '<button id="atcRedesignId_btn">Add to cart</button>'
    state, hint = _detect_qty_state(html)
    assert state == "qty_positive"
    assert "cart" in hint.lower()


def test_listing_verifier_state_persistence(tmp_path, monkeypatch):
    """mark_verified → get_already_verified の roundtrip."""
    from ebay_actions import listing_verifier as lv
    fake_state = tmp_path / "verify_state.json"
    monkeypatch.setattr(lv, "VERIFY_STATE_FILE", fake_state)
    assert lv.get_already_verified() == set()
    lv.mark_verified(["A", "B"])
    assert lv.get_already_verified() == {"A", "B"}
    lv.mark_verified(["C"])
    assert lv.get_already_verified() == {"A", "B", "C"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
