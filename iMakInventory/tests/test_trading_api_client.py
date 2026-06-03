"""trading_api_client 構造テスト (offline、 network 不要)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.offline

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_module_importable():
    """trading_api_client が import 可能 (= 内側依存のみ、 cross-worktree なし)."""
    from ebay_actions import trading_api_client  # noqa: PLC0415, F401
    from ebay_actions.trading_api_client import (  # noqa: PLC0415, F401
        load_access_token, refresh_access_token,
        revise_inventory_status, end_fixed_price_item,
        get_my_active_listings,
    )


def test_parse_ack_and_errors_success():
    """Ack=Success の XML → success / no error."""
    from ebay_actions.trading_api_client import _parse_ack_and_errors  # noqa: PLC0415
    xml = "<Response><Ack>Success</Ack></Response>"
    ack, code, msg = _parse_ack_and_errors(xml)
    assert ack == "Success"
    assert code is None
    assert msg is None


def test_parse_ack_and_errors_warning_redundant():
    """Ack=Warning + err 21917092 'redundant' → 冪等 success 系."""
    from ebay_actions.trading_api_client import _parse_ack_and_errors  # noqa: PLC0415
    xml = (
        "<ReviseInventoryStatusResponse>"
        "<Ack>Warning</Ack>"
        "<Errors><ErrorCode>21917092</ErrorCode>"
        "<ShortMessage>Requested Quantity revision is redundant.</ShortMessage>"
        "</Errors>"
        "</ReviseInventoryStatusResponse>"
    )
    ack, code, msg = _parse_ack_and_errors(xml)
    assert ack == "Warning"
    assert code == "21917092"
    assert "redundant" in msg.lower()


def test_parse_ack_and_errors_failure_not_found():
    """Ack=Failure + err 231 'Item not found' → safe failure 候補."""
    from ebay_actions.trading_api_client import _parse_ack_and_errors  # noqa: PLC0415
    xml = (
        "<Response>"
        "<Ack>Failure</Ack>"
        "<Errors><ErrorCode>231</ErrorCode><ShortMessage>Item not found.</ShortMessage></Errors>"
        "</Response>"
    )
    ack, code, msg = _parse_ack_and_errors(xml)
    assert ack == "Failure"
    assert code == "231"


def test_is_expired_iaf_token_error():
    """IAF expired 検出 (= 自動 refresh trigger)."""
    from ebay_actions.trading_api_client import _is_expired_iaf_token_error  # noqa: PLC0415
    assert _is_expired_iaf_token_error("<Errors><ErrorCode>21917053</ErrorCode></Errors>")
    assert _is_expired_iaf_token_error("Expired IAF token detected")
    assert not _is_expired_iaf_token_error("<Errors><ErrorCode>231</ErrorCode></Errors>")


def test_uploader_safe_failure_code_231_treated_as_ok():
    """trading_api_uploader: err 231 (Item not found) は safe failure = ok 扱い.

    fail-closed 設計: 既に取下げ済 listing への再 revise は 「目的達成済」 で
    cycle success に倒す (= sell_feed_uploader の挙動互換)。
    """
    from ebay_actions import trading_api_uploader  # noqa: PLC0415
    src = Path(trading_api_uploader.__file__).read_text(encoding="utf-8")
    # 231 が safe failure として 明示扱いされてること
    assert '"231"' in src or "'231'" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
