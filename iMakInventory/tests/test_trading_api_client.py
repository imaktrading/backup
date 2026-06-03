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


def test_parse_variation_specifics():
    """RelationshipDetails 'Sizes=A|Color=B' → dict 解析."""
    from ebay_actions.trading_api_uploader import _parse_variation_specifics  # noqa: PLC0415
    out = _parse_variation_specifics("Sizes=US M(JP L)|Color=BL")
    assert out == {"Sizes": "US M(JP L)", "Color": "BL"}
    assert _parse_variation_specifics("") == {}


def test_parse_csv_rows_single(tmp_path):
    """3 col single listing CSV → kind=single."""
    from ebay_actions.trading_api_uploader import _parse_csv_rows  # noqa: PLC0415
    p = tmp_path / "single.csv"
    p.write_text(
        '"*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","*Quantity"\n'
        '"Revise","357008108111",0\n'
        '"Revise","358361388441",0\n',
        encoding="utf-8",
    )
    rows = _parse_csv_rows(p)
    assert len(rows) == 2
    assert all(r["kind"] == "single" for r in rows)
    assert [r["item_id"] for r in rows] == ["357008108111", "358361388441"]
    assert all(r["quantity"] == 0 for r in rows)


def test_is_transient_failure_dns():
    """DNS / ConnectionError 系 → retry 対象判定."""
    from ebay_actions.trading_api_uploader import upload_csv_via_trading_api  # noqa: PLC0415
    import inspect  # noqa: PLC0415
    src = inspect.getsource(upload_csv_via_trading_api)
    # _is_transient_failure ヘルパが 関数内に定義されてる
    assert "_is_transient_failure" in src
    assert "ConnectionError" in src
    assert "NameResolutionError" in src or "getaddrinfo" in src


def test_result_text_includes_success_and_transient_counts():
    """result_text format = 'Success N + Warning M + safe Failure F + action-needed Failure A + Transient T'."""
    from ebay_actions import trading_api_uploader  # noqa: PLC0415
    src = (Path(trading_api_uploader.__file__)).read_text(encoding="utf-8")
    assert "Success {success_count}" in src
    assert "Warning {warning_count}" in src
    assert "safe Failure {safe_failure_count}" in src
    assert "Transient {transient_failure}" in src


def test_parse_csv_rows_variation(tmp_path):
    """6 col variation CSV → 親行 (qty 無) skip、 子行 kind=variation."""
    from ebay_actions.trading_api_uploader import _parse_csv_rows  # noqa: PLC0415
    p = tmp_path / "var.csv"
    p.write_text(
        '"*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)","ItemID","Relationship","RelationshipDetails","*Quantity","*StartPrice"\n'
        '"Revise","358275199203","","Sizes=US M(JP L);US L(JP XL)|Color=BL;NV","",""\n'
        '"","","Variation","Sizes=US M(JP L)|Color=BL",1,"144.98"\n'
        '"","","Variation","Sizes=US L(JP XL)|Color=NV",0,"144.98"\n',
        encoding="utf-8",
    )
    rows = _parse_csv_rows(p)
    # 親行は qty 空欄なので skip、 子行 2 件のみ
    assert len(rows) == 2
    assert all(r["kind"] == "variation" for r in rows)
    assert all(r["item_id"] == "358275199203" for r in rows)
    assert rows[0]["specifics"] == {"Sizes": "US M(JP L)", "Color": "BL"}
    assert rows[0]["quantity"] == 1
    assert rows[0]["start_price"] == 144.98
    assert rows[1]["quantity"] == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
