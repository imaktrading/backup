"""upload_csv_via_form 改造後の Status 分類ロジックの regression test (2026-05-08).

旧 popup 監視 + 履歴 refresh ロジックを CSV DL + Status パースに置換。
ErrorCode 別に Failure を「safe (= 安全、通知不要)」と「action_needed
(= 写真要件等、ユーザー手動対応)」に分類する _classify_result_csv の検証。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_csv(rows: list[dict]) -> str:
    """テスト用 CSV テキスト生成 (eBay 結果 CSV 形式)."""
    import csv as csv_module
    import io
    headers = ["Line Number", "Action", "Status", "ErrorCode", "ErrorMessage",
               "WarningCode", "WarningMessage", "Code", "Message", "ItemID"]
    buf = io.StringIO()
    w = csv_module.DictWriter(buf, fieldnames=headers)
    w.writeheader()
    for r in rows:
        full = {h: "" for h in headers}
        full.update(r)
        w.writerow(full)
    return buf.getvalue()


def test_all_warning_no_failure():
    """全 Warning なら success 判定 OK (= action_needed=0)."""
    from ebay_actions.sell_feed_uploader import _classify_result_csv
    csv_text = _make_csv([
        {"Status": "Warning", "ItemID": "1"},
        {"Status": "Warning", "ItemID": "2"},
    ])
    result = _classify_result_csv(csv_text)
    assert result["warning"] == 2
    assert result["safe_failure"] == 0
    assert result["action_needed_failure"] == 0
    assert result["total"] == 2
    assert result["failure_details"] == []


def test_ended_listing_is_safe():
    """ErrorCode 291 (ended listing) は safe Failure 扱い (= 通知不要)."""
    from ebay_actions.sell_feed_uploader import _classify_result_csv
    csv_text = _make_csv([
        {"Status": "Failure", "ErrorCode": "291",
         "ErrorMessage": "Error - You are not allowed to revise ended listings.",
         "ItemID": "1"},
    ])
    result = _classify_result_csv(csv_text)
    assert result["warning"] == 0
    assert result["safe_failure"] == 1
    assert result["action_needed_failure"] == 0
    assert len(result["failure_details"]) == 1
    assert result["failure_details"][0]["safe"] is True
    assert result["failure_details"][0]["error_code"] == "291"


def test_deleted_listing_is_safe():
    """ErrorCode 17 (deleted) も safe Failure."""
    from ebay_actions.sell_feed_uploader import _classify_result_csv
    csv_text = _make_csv([
        {"Status": "Failure", "ErrorCode": "17",
         "ErrorMessage": "listing has been deleted", "ItemID": "1"},
    ])
    result = _classify_result_csv(csv_text)
    assert result["safe_failure"] == 1
    assert result["action_needed_failure"] == 0


def test_photo_requirement_is_action_needed():
    """ErrorCode 21919136 (写真 500px 要件) は action_needed Failure (= 通知発火)."""
    from ebay_actions.sell_feed_uploader import _classify_result_csv
    csv_text = _make_csv([
        {"Status": "Failure", "ErrorCode": "21919136",
         "ErrorMessage": "Buyers love large photos...", "ItemID": "1"},
    ])
    result = _classify_result_csv(csv_text)
    assert result["safe_failure"] == 0
    assert result["action_needed_failure"] == 1
    assert result["failure_details"][0]["safe"] is False


def test_invalid_itemid_is_action_needed():
    """ErrorCode 37 (invalid ItemID) も action_needed."""
    from ebay_actions.sell_feed_uploader import _classify_result_csv
    csv_text = _make_csv([
        {"Status": "Failure", "ErrorCode": "37",
         "ErrorMessage": "Input data invalid", "ItemID": "1"},
    ])
    result = _classify_result_csv(csv_text)
    assert result["action_needed_failure"] == 1


def test_mixed_warning_and_failures():
    """Warning + ended + 写真要件 の混在を正しく分類."""
    from ebay_actions.sell_feed_uploader import _classify_result_csv
    csv_text = _make_csv([
        {"Status": "Warning", "ItemID": "1"},
        {"Status": "Warning", "ItemID": "2"},
        {"Status": "Failure", "ErrorCode": "291", "ItemID": "3"},  # safe
        {"Status": "Failure", "ErrorCode": "17", "ItemID": "4"},   # safe
        {"Status": "Failure", "ErrorCode": "21919136", "ItemID": "5"},  # action_needed
        {"Status": "Failure", "ErrorCode": "37", "ItemID": "6"},   # action_needed
    ])
    result = _classify_result_csv(csv_text)
    assert result["warning"] == 2
    assert result["safe_failure"] == 2
    assert result["action_needed_failure"] == 2
    assert result["total"] == 6
    assert len(result["failure_details"]) == 4


def test_empty_errorcode_treated_as_action_needed():
    """ErrorCode が空欄の Failure は action_needed (= 安全側に倒さない、不明 = 通知)."""
    from ebay_actions.sell_feed_uploader import _classify_result_csv
    csv_text = _make_csv([
        {"Status": "Failure", "ErrorCode": "", "ItemID": "1"},
    ])
    result = _classify_result_csv(csv_text)
    assert result["safe_failure"] == 0
    assert result["action_needed_failure"] == 1


def test_empty_csv():
    """0 行の CSV は全 0 を返す (= 例外吹かない)."""
    from ebay_actions.sell_feed_uploader import _classify_result_csv
    csv_text = _make_csv([])  # header のみ
    result = _classify_result_csv(csv_text)
    assert result["warning"] == 0
    assert result["safe_failure"] == 0
    assert result["action_needed_failure"] == 0
    assert result["total"] == 0


def test_constants_match_design():
    """改造で設定した定数が想定値と合致 (regression 防止)."""
    from ebay_actions.sell_feed_uploader import (
        UPLOAD_RETRY_MAX, RESULT_WAIT_SEC, SAFE_FAILURE_ERROR_CODES,
    )
    assert UPLOAD_RETRY_MAX == 1, "1 cycle 1 Submit (= 重複 upload 防止)"
    assert RESULT_WAIT_SEC == 30, "Submit 後の eBay 結果生成待ち"
    assert "291" in SAFE_FAILURE_ERROR_CODES, "ended listing は safe"
    assert "17" in SAFE_FAILURE_ERROR_CODES, "deleted listing は safe"
    # 写真要件 / invalid ItemID は安全扱いしない
    assert "21919136" not in SAFE_FAILURE_ERROR_CODES
    assert "37" not in SAFE_FAILURE_ERROR_CODES


def test_old_popup_constants_removed():
    """旧 popup 監視関連の定数が削除されていること (= 旧コード依存検出)."""
    import ebay_actions.sell_feed_uploader as sfu
    assert not hasattr(sfu, "POPUP_MONITOR_TIMEOUT_SEC"), "popup 監視は廃止"
    assert not hasattr(sfu, "POPUP_POLL_INTERVAL"), "popup 監視は廃止"
    assert not hasattr(sfu, "HISTORY_REFRESH_MAX"), "履歴 refresh は廃止"
    assert not hasattr(sfu, "HISTORY_REFRESH_SLEEP_SEC"), "履歴 refresh は廃止"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
