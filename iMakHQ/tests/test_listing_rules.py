#!/usr/bin/env python3
"""iMak Trading Japan - Listing Rules 回帰テスト

過去の失敗事例 + 成功例を fixtures_listing.json から読込み、
listing_common.audit_csv_row が正しく判定するか自動検証。

実行:
  pytest iMakHQ/tests/test_listing_rules.py
  または
  python iMakHQ/tests/test_listing_rules.py  (pytest無し環境)
"""
import json
import sys
import os

# プロジェクト相対パス: iMakHQ/tests/ から iMakeBayAPI/ へ
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'iMakeBayAPI')))
from listing_common import audit_csv_row, gate_row_or_hold
from listing_validator import _is_promo_dual_citizenship

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    _HAS_PYTEST = False


def load_fixtures():
    path = os.path.join(os.path.dirname(__file__), 'fixtures_listing.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


fixtures = load_fixtures()


def _check_success(case):
    """正常系: error が出ないこと"""
    violations = audit_csv_row(
        case["row"],
        category=case.get("category"),
        mercari_state=case.get("mercari_state", ""),
    )
    errors = [v for v in violations if v[2] == "error"]
    assert len(errors) == 0, f"Failed on '{case['name']}': {errors}"


def _check_failure(case):
    """異常系: 期待フィールドで error が出ること"""
    violations = audit_csv_row(
        case["row"],
        category=case.get("category"),
        mercari_state=case.get("mercari_state", ""),
    )
    errors = [v for v in violations if v[2] == "error"]
    assert len(errors) > 0, f"Should have failed on '{case['name']}' but passed."
    error_fields = [v[0] for v in errors]
    assert case["expected_error_field"] in error_fields, \
        f"Expected error in '{case['expected_error_field']}', but got errors in {error_fields}"


def _check_price_case(case):
    """価格検証系: price_status/median_usd を渡した時の audit_csv_row 挙動を検証。

    必須項目は fixtures 側で満たしているため、error=0 or ALERT由来errorのみが期待値。
    「ALERT 由来で止まったか」を message 内容（"pricing_engine ALERT"）で厳密に判定する。
    """
    kwargs = {
        "category": case.get("category"),
        "mercari_state": case.get("mercari_state", ""),
    }
    # price_status / median_usd は CASE-D（後方互換）では渡さない
    if "price_status" in case:
        kwargs["price_status"] = case["price_status"]
    if "median_usd" in case:
        kwargs["median_usd"] = case["median_usd"]

    violations = audit_csv_row(case["row"], **kwargs)
    errors = [v for v in violations if v[2] == "error"]
    alert_errors = [v for v in errors if "pricing_engine ALERT" in v[1]]

    if case.get("expect_error"):
        assert len(errors) > 0, \
            f"'{case['name']}' should have errors but got none."
        assert "*StartPrice" in [v[0] for v in errors], \
            f"'{case['name']}' error field must be *StartPrice, got {[v[0] for v in errors]}"
        if case.get("expect_alert_message"):
            assert len(alert_errors) > 0, \
                f"'{case['name']}' error must originate from pricing_engine ALERT, got messages: {[v[1] for v in errors]}"
    else:
        # ALERT 由来 error だけは必ず 0 件（必須項目欠落等の別要因の error は fixtures 設計上出ない）
        assert len(alert_errors) == 0, \
            f"'{case['name']}' should NOT contain ALERT errors but got: {alert_errors}"
        assert len(errors) == 0, \
            f"'{case['name']}' should have no errors but got: {errors}"


def _check_gate_blocks_alert():
    """物理ゲート検証: gate_row_or_hold が ALERT 由来 error を受けて allowed=False を返すこと。

    CASE-B 相当の行を直接渡し、戻り値タプル (allowed, violations) が仕様通りか検証。
    """
    bad_row = {
        "*Title": "Shimano 22 Stella C3000XG Spinning Reel Pre-owned Japan",
        "*Category": 261030,
        "*StartPrice": 700.0,
        "ConditionID": 3000,
        "ConditionDescription": "Excellent condition. Very minor signs of use if any. Please review all photos for details.",
        "C:Brand": "Shimano",
        "CustomLabel": "GATE-BLOCK-TEST",
    }
    allowed, violations = gate_row_or_hold(
        bad_row,
        category="reel",
        sku="GATE-BLOCK-TEST",
        price_status="ALERT",
        median_usd=500,
    )
    assert allowed is False, "gate_row_or_hold must block when enabled category receives ALERT"
    assert any(v[2] == "error" and "pricing_engine ALERT" in v[1] for v in violations), \
        f"violations must contain ALERT-origin error, got: {violations}"


def _check_promo_dual_citizenship(case):
    """プロモ二重国籍判定: ケース1/2 が許容、非TCGブランドは遮断されること。

    `_is_promo_dual_citizenship` は許容時に case 種別を含む理由文字列、
    非該当時に空文字を返す。expect_case で文字列内容まで検証する。
    """
    reason = _is_promo_dual_citizenship(case["title"], case["psa_brand"])
    matched = bool(reason)
    assert matched is case["expect_match"], (
        f"'{case['name']}': expected match={case['expect_match']}, got {matched} "
        f"(reason={reason!r})"
    )
    if case["expect_match"]:
        expect_case = case.get("expect_case")
        assert expect_case and expect_case in reason, (
            f"'{case['name']}': expected case label '{expect_case}' in reason, "
            f"got {reason!r}"
        )


def _check_gate_allows_go():
    """物理ゲート検証(対照): GO の時は allowed=True"""
    good_row = {
        "*Title": "Shimano 22 Stella C3000XG Spinning Reel Pre-owned Japan",
        "*Category": 261030,
        "*StartPrice": 550.0,
        "ConditionID": 3000,
        "ConditionDescription": "Excellent condition. Very minor signs of use if any. Please review all photos for details.",
        "C:Brand": "Shimano",
        "CustomLabel": "GATE-PASS-TEST",
    }
    allowed, violations = gate_row_or_hold(
        good_row,
        category="reel",
        sku="GATE-PASS-TEST",
        price_status="GO",
        median_usd=500,
    )
    assert allowed is True, f"gate_row_or_hold must allow GO status, violations={violations}"


# pytest 用
if _HAS_PYTEST:
    @pytest.mark.parametrize("case", fixtures["SUCCESS_CASES"], ids=lambda c: c["name"])
    def test_audit_success_cases(case):
        _check_success(case)

    @pytest.mark.parametrize("case", fixtures["FAILURE_CASES"], ids=lambda c: c["name"])
    def test_audit_failure_cases(case):
        _check_failure(case)

    @pytest.mark.parametrize("case", fixtures.get("PRICE_VALIDATION_CASES", []), ids=lambda c: c["name"])
    def test_price_validation_logic(case):
        _check_price_case(case)

    def test_gate_physical_blocking_by_alert():
        _check_gate_blocks_alert()

    def test_gate_allows_go_status():
        _check_gate_allows_go()

    @pytest.mark.parametrize(
        "case",
        fixtures.get("PROMO_DUAL_CITIZENSHIP_CASES", []),
        ids=lambda c: c["name"],
    )
    def test_promo_dual_citizenship_cases(case):
        _check_promo_dual_citizenship(case)


# 標準スクリプト実行（pytest 無し環境向け）
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    price_cases = fixtures.get("PRICE_VALIDATION_CASES", [])
    promo_cases = fixtures.get("PROMO_DUAL_CITIZENSHIP_CASES", [])
    print(f"Running fixture tests ({len(fixtures['SUCCESS_CASES'])} success + "
          f"{len(fixtures['FAILURE_CASES'])} failure + {len(price_cases)} price + "
          f"{len(promo_cases)} promo + 2 gate cases)...\n")
    failed = 0
    for case in fixtures["SUCCESS_CASES"]:
        try:
            _check_success(case)
            print(f"  ✓ SUCCESS: {case['name']}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {case['name']} - {e}")
            failed += 1
    for case in fixtures["FAILURE_CASES"]:
        try:
            _check_failure(case)
            print(f"  ✓ FAILURE detected as expected: {case['name']}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {case['name']} - {e}")
            failed += 1
    for case in price_cases:
        try:
            _check_price_case(case)
            print(f"  ✓ PRICE: {case['name']}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {case['name']} - {e}")
            failed += 1
    for gate_name, gate_fn in [
        ("gate_physical_blocking_by_alert", _check_gate_blocks_alert),
        ("gate_allows_go_status", _check_gate_allows_go),
    ]:
        try:
            gate_fn()
            print(f"  ✓ GATE: {gate_name}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {gate_name} - {e}")
            failed += 1
    for case in promo_cases:
        try:
            _check_promo_dual_citizenship(case)
            print(f"  ✓ PROMO: {case['name']}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {case['name']} - {e}")
            failed += 1
    print()
    if failed == 0:
        print("✅ All fixture tests passed (Level 4 Reproducibility achieved).")
        sys.exit(0)
    else:
        print(f"❌ {failed} test(s) failed.")
        sys.exit(1)
