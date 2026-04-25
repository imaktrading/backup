#!/usr/bin/env python3
"""Step 4 本番（実用最小形）: TCG CSV 凍結ゴールデンテスト.

PSA cert -> CSV 完全再生成テストは外部API凍結フィクスチャが必要なため次回。
本テストは「過去に生成された正常CSV」を fixture として凍結し、
- 必須列が揃っているか
- 正規化が冪等か
- eBay File Exchange 形式の構造が崩れていないか
を検証する。

将来追加予定:
- frozen PSA cert response (JSON)
- frozen Bandai TCG+ response (JSON)
- frozen 3AI deliberation result
- 上記から CSV 再生成 → byte-level 比較
"""
from __future__ import annotations
import csv
import io
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tests.helpers.normalizer import normalize_csv

try:
    import pytest
    _HAS_PYTEST = True
except ImportError:
    _HAS_PYTEST = False


FIXTURE_PATH = _REPO / "tests" / "golden" / "fixtures" / "tcg_csv_sample_3rows.csv"

# eBay File Exchange 必須列 (TCG)
REQUIRED_COLUMNS = [
    "*Title",
    "*Category",
    "*StartPrice",
    "ConditionID",
    "*Description",
    "*Format",
    "*Duration",
    "*Quantity",
    "*Location",
    "ShippingProfileName",
    "ReturnProfileName",
    "PaymentProfileName",
    "CustomLabel",
    "PicURL",
]


def _load_fixture():
    assert FIXTURE_PATH.exists(), f"Fixture missing: {FIXTURE_PATH}"
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_fixture_has_data_rows():
    """fixture にヘッダ + 1行以上のデータがあること"""
    text = _load_fixture()
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) >= 2, f"fixture must have header + at least 1 data row, got {len(rows)}"


def test_fixture_has_required_ebay_columns():
    """eBay File Exchange 必須列が全部存在すること"""
    text = _load_fixture()
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    assert not missing, f"Missing required columns: {missing}"


def test_action_column_format():
    """*Action 列が eBay 規定の SiteID/Country/Currency/Version/CC を含むこと"""
    text = _load_fixture()
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    action_col = next((c for c in header if c.startswith("*Action(")), None)
    assert action_col is not None, "Missing *Action column"
    for required in ["SiteID=US", "Country=JP", "Currency=USD", "CC=UTF-8"]:
        assert required in action_col, f"*Action column missing: {required}"


def test_normalize_idempotent_on_real_csv():
    """正規化を実 CSV に2回適用しても結果が変わらない"""
    text = _load_fixture()
    once = normalize_csv(text)
    twice = normalize_csv(once)
    assert once == twice, "normalize_csv must be idempotent"


def test_no_jp_chars_in_action_or_format():
    """Action / Format / Duration 等のシステム列に和文字混入がないこと
    (cp932 文字化け事故の検出: 値レベルで日本語が混じったら NG)"""
    text = _load_fixture()
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    system_cols = [c for c in header if c.startswith("*") and c not in ("*Title", "*Description")]
    sys_idx = [header.index(c) for c in system_cols]
    for row in rows[1:]:
        for i in sys_idx:
            if i >= len(row):
                continue
            val = row[i]
            for ch in val:
                assert ord(ch) < 0x3000, (
                    f"System column {header[i]!r} contains Japanese char {ch!r}: '{val[:50]}'"
                )


def test_required_columns_have_values():
    """必須列の値が空でないこと（少なくとも1行はチェック）"""
    text = _load_fixture()
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    if len(rows) < 2:
        return
    first_data = rows[1]
    must_have = ["*Title", "*Category", "*StartPrice", "CustomLabel"]
    for col in must_have:
        idx = header.index(col)
        assert first_data[idx].strip(), f"Column {col!r} empty in first data row"


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("fixture has data rows", test_fixture_has_data_rows),
        ("required ebay columns", test_fixture_has_required_ebay_columns),
        ("Action column format", test_action_column_format),
        ("normalize idempotent on real CSV", test_normalize_idempotent_on_real_csv),
        ("no JP chars in system columns", test_no_jp_chars_in_action_or_format),
        ("required columns have values", test_required_columns_have_values),
    ]
    fails = 0
    for name, fn in cases:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {name}\n      {e}")
            fails += 1
        except Exception as e:
            print(f"  ✗ ERROR: {name}\n      {type(e).__name__}: {e}")
            fails += 1
    print()
    if fails == 0:
        print(f"✅ All {len(cases)} TCG CSV golden tests passed.")
    else:
        print(f"❌ {fails}/{len(cases)} failed.")
        sys.exit(1)
