"""price_revise.py の純関数テスト (Sheet API / 為替 API は touch しない).

実行: pytest c:/dev/iMak_revise/iMakRevise/tests/
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

THIS = Path(__file__).resolve().parent
PROJECT = THIS.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from revise.price_revise import (
    DEFAULT_THRESHOLD_PCT,
    HEADER_ROWS,
    MAX_JPY,
    MIN_JPY,
    REVISE_CSV_HEADER,
    ReviseCandidate,
    _is_sold,
    _is_valid_jpy,
    _to_float,
    compute_new_usd,
    detect_candidates,
    round_98,
    should_revise,
    write_revise_csv,
)


# ============================================================================
# helpers
# ============================================================================
def _row(item_id="", sold="", f="", n="", ah="", category="Tシャツ",
         url="https://example.com/x"):
    """商品管理シートの 1 行を構築. 主要列だけセット.
    A=URL [0], B=ItemID [1], D=売切 [3], F=¥ [5], M=フラグ [12],
    N=¥ [13], O=時刻 [14], R=カテゴリ [17], AH=前期N [33]

    default URL あり (= 新 logic で no_url skip されないように)。
    URL を明示空欄にしたいときは url="" を渡す。
    """
    row = [""] * 35
    row[0] = url
    row[1] = item_id
    row[3] = sold
    row[5] = f
    row[13] = n
    row[17] = category
    row[33] = ah
    return row


# ============================================================================
# round_98
# ============================================================================
class TestRound98:
    def test_above_10_floors_to_X98(self):
        assert round_98(54.67) == 54.98
        assert round_98(54.00) == 54.98
        assert round_98(54.99) == 54.98

    def test_below_10_round2(self):
        assert round_98(9.5) == 9.5
        assert round_98(7.123) == 7.12

    def test_boundary_10(self):
        # 10 ちょうどは round の挙動 = 10
        assert round_98(10.0) == 10.0


# ============================================================================
# _to_float
# ============================================================================
class TestToFloat:
    def test_pure(self):
        assert _to_float("1234") == 1234.0

    def test_with_yen_comma(self):
        assert _to_float("¥1,234") == 1234.0

    def test_empty(self):
        assert _to_float("") is None
        assert _to_float(None) is None

    def test_invalid(self):
        assert _to_float("abc") is None


# ============================================================================
# _is_sold / _is_valid_jpy
# ============================================================================
class TestIsSold:
    def test_circle(self):
        assert _is_sold("○") is True

    def test_true_str(self):
        assert _is_sold("TRUE") is True
        assert _is_sold("true") is True

    def test_empty(self):
        assert _is_sold("") is False
        assert _is_sold(" ") is False

    def test_other_value(self):
        assert _is_sold("yes_buy") is False


class TestIsValidJpy:
    def test_in_range(self):
        assert _is_valid_jpy(1000.0) is True
        assert _is_valid_jpy(MIN_JPY) is True
        assert _is_valid_jpy(MAX_JPY) is True

    def test_out_of_range(self):
        assert _is_valid_jpy(MIN_JPY - 1) is False
        assert _is_valid_jpy(MAX_JPY + 1) is False
        assert _is_valid_jpy(0) is False
        assert _is_valid_jpy(-100) is False

    def test_none(self):
        assert _is_valid_jpy(None) is False


# ============================================================================
# should_revise (新 logic 2026-05-22: 現状 vs V8 比較)
# 公式 sheet 対応 (URL filter 廃止 2026-05-22)
# ============================================================================
ITEM_ID = "358517889790"


class TestShouldRevise:
    def test_no_item_id(self):
        """ItemID 空 → no_item_id skip (= 旧 no_url 置換)"""
        ok, reason, _ = should_revise(
            item_id="", sold_flag="", n_jpy=1000, ah_jpy=900,
            current_usd=10, current_policy="DDP-A-P01",
            v7_usd=10, v7_policy="DDP-A-P01",
        )
        assert not ok and reason == "no_item_id"

    def test_sold(self):
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="○", n_jpy=1000, ah_jpy=900,
            current_usd=10, current_policy="DDP-A-P01",
            v7_usd=20, v7_policy="DDP-A-P02",
        )
        assert not ok and reason == "sold"

    def test_no_cost(self):
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=None, ah_jpy=900,
            current_usd=10, current_policy="DDP-A-P01",
            v7_usd=10, v7_policy="DDP-A-P01",
        )
        assert not ok and reason == "no_cost"

    def test_abnormal_delta(self):
        # AH=1000 → N=4000 (+300%) → abnormal
        ok, reason, extras = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=4000, ah_jpy=1000,
            current_usd=10, current_policy="DDP-A-P01",
            v7_usd=10, v7_policy="DDP-A-P01",
            abnormal_delta_threshold=200,
        )
        assert not ok and reason == "abnormal_delta"
        assert extras["is_abnormal"] is True
        assert extras["delta_pct"] == 300.0

    def test_no_snapshot(self):
        # current_usd/policy 両方 None
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=1000, ah_jpy=900,
            current_usd=None, current_policy=None,
            v7_usd=20, v7_policy="DDP-A-P02",
        )
        assert not ok and reason == "no_snapshot"

    def test_policy_change(self):
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=1000, ah_jpy=900,
            current_usd=20, current_policy="DDP-A-P01",
            v7_usd=20, v7_policy="DDP-A-P02",  # 異なる Policy
        )
        assert ok and reason == "policy_change"

    def test_price_diff(self):
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=1000, ah_jpy=900,
            current_usd=20, current_policy="DDP-A-P01",
            v7_usd=30, v7_policy="DDP-A-P01",  # 同 Policy, 異 USD
        )
        assert ok and reason == "price_diff"

    def test_aligned(self):
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=1000, ah_jpy=900,
            current_usd=20.0, current_policy="DDP-A-P1",  # 0埋め前
            v7_usd=20, v7_policy="DDP-A-P01",
        )
        assert not ok and reason == "aligned"

    def test_normalize_policy_works(self):
        """旧 'DDP-A-P9' と 新 'DDP-A-P09' は normalize 後 一致"""
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=1000, ah_jpy=None,
            current_usd=20, current_policy="DDP-A-P9",
            v7_usd=20, v7_policy="DDP-A-P09",
        )
        assert not ok and reason == "aligned"

    def test_legacy_policy_triggers_change(self):
        """'Free' or '100-200 Copy' などの legacy 名は DDP-* と不一致 → revise"""
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=1000, ah_jpy=None,
            current_usd=20, current_policy="Free",
            v7_usd=20, v7_policy="DDP-A-P02",
        )
        assert ok and reason == "policy_change"

    def test_abnormal_takes_priority_over_diff(self):
        """異常 delta が price_diff/policy_change より優先される"""
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=4000, ah_jpy=1000,  # +300% (異常)
            current_usd=10, current_policy="OLD",
            v7_usd=99, v7_policy="DDP-A-P10",  # diff あり
            abnormal_delta_threshold=200,
        )
        assert not ok and reason == "abnormal_delta"

    def test_official_sheet_no_url_still_eligible(self):
        """公式 sheet (URL 列なし) でも ItemID + N があれば eligible (= 2026-05-22 公式対応)"""
        ok, reason, _ = should_revise(
            item_id="358000000003", sold_flag="", n_jpy=2500, ah_jpy=None,
            current_usd=39.98, current_policy="Free",
            v7_usd=39.98, v7_policy="DDP-A-P04",  # Policy 不一致
        )
        assert ok and reason == "policy_change"

    def test_not_in_snapshot(self):
        """snapshot に ItemID なし → not_in_snapshot skip (= 取下げ済 listing 想定)"""
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=1000, ah_jpy=None,
            current_usd=None, current_policy=None,
            v7_usd=20, v7_policy="DDP-A-P02",
            in_snapshot=False,  # snapshot にない
        )
        assert not ok and reason == "not_in_snapshot"

    def test_out_of_stock(self):
        """Available quantity = 0 → out_of_stock skip (= revise 意味なし)"""
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=1000, ah_jpy=None,
            current_usd=20, current_policy="DDP-A-P01",
            v7_usd=30, v7_policy="DDP-A-P02",  # diff あるが在庫切れ
            in_snapshot=True,
            available_qty=0,
        )
        assert not ok and reason == "out_of_stock"

    def test_in_stock_qty_1_eligible(self):
        """qty=1 は normal (= in-stock)"""
        ok, reason, _ = should_revise(
            item_id=ITEM_ID, sold_flag="", n_jpy=1000, ah_jpy=None,
            current_usd=20, current_policy="DDP-A-P01",
            v7_usd=30, v7_policy="DDP-A-P01",
            in_snapshot=True,
            available_qty=1,
        )
        assert ok and reason == "price_diff"


# ============================================================================
# detect_candidates (新 logic: filter pass のみ収集)
# ============================================================================
class TestDetectCandidates:
    def test_pass_filter(self):
        """A有 / D空 / N有 → eligible"""
        rows = [_row(item_id="123", n="1100", ah="1000")]
        c = detect_candidates(rows)
        assert len(c) == 1
        assert c[0].basis == "pending"  # 後段で評価
        assert c[0].new_jpy == 1100
        assert c[0].url

    def test_no_url_still_eligible(self):
        """URL 空欄でも ItemID + N あれば eligible (= 公式 sheet 対応 2026-05-22)"""
        rows = [_row(item_id="123", n="1100", ah="1000", url="")]
        c = detect_candidates(rows)
        assert len(c) == 1
        assert c[0].item_id == "123"

    def test_sold_excluded(self):
        rows = [_row(item_id="123", sold="○", n="1100", ah="1000")]
        assert detect_candidates(rows) == []

    def test_no_cost_excluded(self):
        rows = [_row(item_id="123", n="", ah="1000")]
        assert detect_candidates(rows) == []

    def test_empty_item_id_excluded(self):
        rows = [_row(item_id="", n="1100", ah="1000")]
        assert detect_candidates(rows) == []

    def test_category_captured(self):
        rows = [_row(item_id="123", n="1100", ah="1000", category="フィギュア")]
        c = detect_candidates(rows)
        assert c[0].category == "フィギュア"

    def test_abnormal_tagged(self):
        """AH↔N delta > 200% → is_abnormal=True (filter は通る)"""
        rows = [_row(item_id="123", n="4000", ah="1000")]
        c = detect_candidates(rows, abnormal_delta_threshold=200)
        assert len(c) == 1
        assert c[0].is_abnormal is True
        assert c[0].delta_pct == pytest.approx(300.0)

    def test_negative_delta_eligible_but_not_abnormal(self):
        """値下げは eligible だが is_abnormal=False"""
        rows = [_row(item_id="123", n="800", ah="1000")]
        c = detect_candidates(rows)
        assert len(c) == 1
        assert c[0].is_abnormal is False
        assert c[0].delta_pct < 0


# ============================================================================
# compute_new_usd (V8 mock)
# ============================================================================
class TestComputeNewUsd:
    @staticmethod
    def _candidate(n_jpy, category="Tシャツ"):
        return ReviseCandidate(
            row_index=2, item_id="123", category=category,
            new_jpy=n_jpy, ah_jpy=None, f_jpy=None,
            delta_pct=10.0, basis="F", title="",
        )

    def test_v8_success(self):
        c = self._candidate(1000)
        # V8 mock: 通常成功
        v8_fn = lambda cost_jpy, median_usd, category, country, title: {
            "price": 36.98,
            "shipping_usd": 5.50,
            "shipping_profile_name": "DDP-A-P05",
            "buyer_total_usd": 42.48,
            "profit_jpy": 100,
        }
        compute_new_usd(c, v8_fn)
        assert c.new_usd == 36.98
        assert c.shipping_usd == 5.50
        assert c.shipping_profile_name == "DDP-A-P05"
        assert c.buyer_total_usd == 42.48

    def test_v8_value_error(self):
        c = self._candidate(1000)
        v8_fn = lambda **kwargs: (_ for _ in ()).throw(ValueError("Unknown category"))
        compute_new_usd(c, v8_fn)
        assert c.new_usd is None
        assert "V8 計算失敗" in c.skip_reason

    def test_v8_exception(self):
        c = self._candidate(1000)
        v8_fn = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("config not found"))
        compute_new_usd(c, v8_fn)
        assert c.new_usd is None
        assert "V8 例外" in c.skip_reason

    def test_v8_loss_detection(self):
        """赤字検出 (= 5/15 事故再発防止)"""
        c = self._candidate(1000)
        v8_fn = lambda cost_jpy, median_usd, category, country, title: {
            "price": 20.00, "profit_jpy": -500,  # 赤字
        }
        compute_new_usd(c, v8_fn)
        assert c.new_usd is None  # skip 扱い
        assert "赤字" in c.skip_reason


# ============================================================================
# write_revise_csv
# ============================================================================
class TestWriteReviseCsv:
    def test_write(self, tmp_path):
        revisable = [
            ReviseCandidate(
                row_index=2, item_id="357401200653", category="Tシャツ",
                new_jpy=1100, ah_jpy=1000, f_jpy=900,
                delta_pct=10.0, basis="AH", new_usd=36.98,
                shipping_profile_name="DDP-C-P04",
            ),
        ]
        path = write_revise_csv(revisable, output_dir=tmp_path)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            assert next(reader) == REVISE_CSV_HEADER
            # 6 列: Action / ItemID / ShippingProfileName / StartPrice / BestOfferAutoAcceptPrice / MinimumBestOfferPrice
            assert next(reader) == [
                "Revise", "357401200653", "DDP-C-P04", "36.98", "", "",
            ]

    def test_write_no_shipping_profile(self, tmp_path):
        """shipping_profile_name=None なら空文字 (= eBay 側 現行維持)."""
        revisable = [
            ReviseCandidate(
                row_index=2, item_id="111", category="X",
                new_jpy=1000, ah_jpy=None, f_jpy=None,
                delta_pct=10.0, basis="F", new_usd=36.98,
                shipping_profile_name=None,
            ),
        ]
        path = write_revise_csv(revisable, output_dir=tmp_path)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader)
            row = next(reader)
            assert row[2] == ""  # ShippingProfileName 空


# shipping_dict 廃止 (= V8 が Policy 送料を内部計算)


# ============================================================================
# multi-sheet (公式 adapter + source_sheet tag)
# ============================================================================
from revise.price_revise import (  # noqa: E402
    SHEETS, ALL_SHEET_KEYS, _normalize_official_row, write_diff_csv,
    write_abnormal_alert_log,
    COL_OFFICIAL_LISTING_ID, COL_OFFICIAL_COST, COL_OFFICIAL_TITLE,
    COL_OFFICIAL_CATEGORY, COL_CATEGORY,
)


class TestSheetsConstant:
    def test_three_sheets_defined(self):
        assert set(ALL_SHEET_KEYS) == {"HIGH", "LOW", "公式"}

    def test_high_low_share_schema(self):
        assert SHEETS["HIGH"]["schema"] == "high_low"
        assert SHEETS["LOW"]["schema"] == "high_low"

    def test_official_schema(self):
        assert SHEETS["公式"]["schema"] == "official"
        assert SHEETS["公式"]["tab"] == "SKU詳細"


class TestNormalizeOfficialRow:
    def test_minimum_row(self):
        # D=listing_id, J=cost のみ
        row = [""] * 10
        row[COL_OFFICIAL_LISTING_ID] = "358000000001"
        row[COL_OFFICIAL_COST] = "2500"
        out = _normalize_official_row(row)
        assert out[1] == "358000000001"   # ItemID
        assert out[13] == "2500"          # N
        # F / AH / R は空欄 → should_revise no_baseline で初回 skip
        assert out[5] == ""
        assert out[33] == ""
        assert out[17] == ""

    def test_with_title(self):
        row = [""] * 10
        row[COL_OFFICIAL_LISTING_ID] = "358000000002"
        row[COL_OFFICIAL_TITLE] = "UNIQLO UT Pokemon T-shirt"
        row[COL_OFFICIAL_COST] = "1990"
        out = _normalize_official_row(row)
        assert out[2] == "UNIQLO UT Pokemon T-shirt"

    def test_short_row(self):
        # 列が J まで届かない短い行
        out = _normalize_official_row(["", "", "", "358XXX"])
        assert out[1] == "358XXX"
        assert out[13] == ""  # cost なし

    def test_with_category(self):
        """P列 (= category) を読み取り COL_CATEGORY に転記 (2026-05-22)"""
        row = [""] * 16
        row[COL_OFFICIAL_LISTING_ID] = "358000000004"
        row[COL_OFFICIAL_TITLE] = "UNIQLO UT Manga Tshirt"
        row[COL_OFFICIAL_COST] = "1990"
        row[COL_OFFICIAL_CATEGORY] = "Tシャツ(UT)"
        out = _normalize_official_row(row)
        assert out[COL_CATEGORY] == "Tシャツ(UT)"

    def test_without_category_empty(self):
        """P列なし行 → category 空欄、V8 fallback で skip 想定"""
        row = [""] * 10  # P列まで届かない
        row[COL_OFFICIAL_LISTING_ID] = "358000000005"
        row[COL_OFFICIAL_COST] = "1500"
        out = _normalize_official_row(row)
        assert out[COL_CATEGORY] == ""

    def test_category_uniqlo_non_ut(self):
        row = [""] * 16
        row[COL_OFFICIAL_LISTING_ID] = "358000000006"
        row[COL_OFFICIAL_COST] = "3990"
        row[COL_OFFICIAL_CATEGORY] = "ユニクロ(非UT)"
        out = _normalize_official_row(row)
        assert out[COL_CATEGORY] == "ユニクロ(非UT)"

    def test_category_sanrio_stationery(self):
        row = [""] * 16
        row[COL_OFFICIAL_LISTING_ID] = "358000000007"
        row[COL_OFFICIAL_COST] = "550"
        row[COL_OFFICIAL_CATEGORY] = "サンリオ文具"
        out = _normalize_official_row(row)
        assert out[COL_CATEGORY] == "サンリオ文具"


class TestDetectCandidatesSourceSheet:
    def test_source_sheet_tagged(self):
        from revise.price_revise import detect_candidates
        rows = [_row(item_id="123", n="1100", ah="1000")]
        c = detect_candidates(rows, source_sheet="LOW")
        assert len(c) == 1
        assert c[0].source_sheet == "LOW"

    def test_default_high(self):
        from revise.price_revise import detect_candidates
        rows = [_row(item_id="123", n="1100", ah="1000")]
        c = detect_candidates(rows)
        assert c[0].source_sheet == "HIGH"


class TestOfficialSchema:
    """公式 sheet (URL/AH/F/R なし) は ItemID + N があれば eligible (= URL filter 廃止 2026-05-22).

    後段の should_revise で 現Policy ≠ V8Policy → revise 判定。
    R 列 (= category) 空欄なら V8 計算で v8_calc_failed skip (= fail-closed)。
    """
    def test_official_row_passes_filter(self):
        from revise.price_revise import detect_candidates
        # 公式 row: D=listing_id, E=title, J=cost
        row = _normalize_official_row([""] * 3 + ["358000000003", "UNIQLO Tshirt"]
                                       + [""] * 4 + ["2500"])
        c = detect_candidates([row], source_sheet="公式")
        # 新 logic: URL 空欄でも eligible
        assert len(c) == 1
        assert c[0].item_id == "358000000003"
        assert c[0].new_jpy == 2500
        assert c[0].source_sheet == "公式"

    def test_official_no_item_id_excluded(self):
        """公式 sheet でも ItemID 空欄なら skip"""
        from revise.price_revise import detect_candidates
        row = _normalize_official_row([""] * 9 + ["2500"])  # D空、J=2500
        c = detect_candidates([row], source_sheet="公式")
        assert len(c) == 0


class TestWriteDiffCsvMultiSheet:
    def test_sheet_column_first(self, tmp_path):
        revisable = [
            ReviseCandidate(
                row_index=2, item_id="111", category="Tシャツ",
                new_jpy=1100, ah_jpy=1000, f_jpy=900,
                delta_pct=10.0, basis="AH", new_usd=36.98,
                source_sheet="LOW",
                shipping_usd=5.5, shipping_profile_name="DDP-A-P05",
                buyer_total_usd=42.48, profit_jpy=100,
            ),
        ]
        path = write_diff_csv(revisable, mode="normal", output_dir=tmp_path)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header[0] == "sheet"
            row = next(reader)
            assert row[0] == "LOW"
            assert row[1] == "111"


# ============================================================================
# 異常 delta 検出 (= 新 logic は detect_candidates が is_abnormal タグするだけ)
# 既存 G-shock 実 reference のみ残す
# ============================================================================
class TestAbnormalDeltaDetection:
    def test_g_shock_reference_case(self):
        """実 5/21 検出例: AH=¥16,000 → N=¥363,000 (delta=+2169%)"""
        rows = [_row(item_id="358369265225", n="363000", ah="16000", category="G-shock")]
        c = detect_candidates(rows, abnormal_delta_threshold=200)
        assert len(c) == 1
        assert c[0].is_abnormal is True
        assert c[0].delta_pct > 2000

    def test_boundary_at_threshold(self):
        """ちょうど閾値 +200% → is_abnormal=False (> なので)"""
        rows = [_row(item_id="111", n="3000", ah="1000")]
        c = detect_candidates(rows, abnormal_delta_threshold=200)
        assert c[0].is_abnormal is False


class TestWriteAbnormalAlertLog:
    def test_empty_returns_none(self, tmp_path):
        assert write_abnormal_alert_log([], output_dir=tmp_path) is None

    def test_writes_log(self, tmp_path):
        abnormal = [
            ReviseCandidate(
                row_index=5, item_id="358369265225", category="G-shock",
                new_jpy=363000, ah_jpy=16000, f_jpy=None,
                delta_pct=2169.0, basis="AH", source_sheet="LOW",
                is_abnormal=True,
                skip_reason="ABNORMAL_DELTA (+2169%)",
            ),
        ]
        path = write_abnormal_alert_log(abnormal, output_dir=tmp_path)
        assert path is not None
        content = path.read_text(encoding="utf-8")
        assert "358369265225" in content
        assert "G-shock" in content
        assert "ABNORMAL_DELTA" in content
        assert "16,000" in content
        assert "363,000" in content


class TestWriteDiffCsvWithAbnormal:
    def test_abnormal_appears_with_flag(self, tmp_path):
        revisable = []
        abnormal = [
            ReviseCandidate(
                row_index=5, item_id="358369265225", category="G-shock",
                new_jpy=363000, ah_jpy=16000, f_jpy=None,
                delta_pct=2169.0, basis="AH", source_sheet="LOW",
                is_abnormal=True,
                skip_reason="ABNORMAL_DELTA (+2169%)",
            ),
        ]
        path = write_diff_csv(revisable, mode="normal", output_dir=tmp_path,
                              abnormal=abnormal)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert "異常検出" in header
            row = next(reader)
            anomaly_col_idx = header.index("異常検出")
            assert "ABNORMAL_DELTA" in row[anomaly_col_idx]


# ============================================================================
# control_panel.parse_summary_line + extract_sheet_id (回帰)
# ============================================================================
class TestControlPanelParseSummary:
    @staticmethod
    def _parse(line):
        sys.path.insert(0, str(PROJECT))
        from control_panel import parse_summary_line
        summary = {
            "total_rows": "-", "init_targets": "-",
            "revise_candidates": "-", "revisable": "-", "cap_exceeded": False,
        }
        updated = parse_summary_line(line, summary)
        return summary, updated

    def test_total_rows(self):
        s, ok = self._parse("[revise] 全行数: 925 (header 除く)")
        assert ok and s["total_rows"] == 925

    def test_init_targets(self):
        s, ok = self._parse("[revise] F 初期化対象 (F+AH 両空欄 + N 値あり): 159 件")
        assert ok and s["init_targets"] == 159

    def test_cap_exceeded(self):
        s, ok = self._parse("[revise] [WARN] revise 上限 50 件超過 -> 上位のみ処理")
        assert ok and s["cap_exceeded"] is True


class TestExtractSheetId:
    @staticmethod
    def _extract(value):
        sys.path.insert(0, str(PROJECT))
        from control_panel import extract_sheet_id
        return extract_sheet_id(value)

    def test_url(self):
        url = "https://docs.google.com/spreadsheets/d/19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk/edit?gid=0"
        assert self._extract(url) == "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"

    def test_id_only(self):
        sid = "1RbGaiQxhYDd7s8nqT0jHeh7sQ6FJNCVnVxkEJLFmz9s"
        assert self._extract(sid) == sid

    def test_invalid(self):
        assert self._extract("abc") is None


# ============================================================================
# best_offer (新 Phase)

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
