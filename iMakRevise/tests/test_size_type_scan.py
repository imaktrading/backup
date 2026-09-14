"""size_type_scan.py の unit test (2026-09-14 窓口 実装GO対応)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

THIS = Path(__file__).resolve().parent
PROJECT = THIS.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from revise import ebay_trading_api, price_revise, size_type_scan  # noqa: E402


def fake_size_type_for(size: str) -> str:
    """本元 listing_common.size_type_for のテスト用スタブ (3XL以上/52+/Tall表記のみ Big & Tall)."""
    s = (size or "").strip().upper().replace(" ", "")
    big = {"3XL", "4XL", "5XL", "52", "54", "MT", "XLT"}
    return "Big & Tall" if s in big else "Regular"


# ============================================================================
# judge_item (純関数)
# ============================================================================
class TestJudgeItem:
    def test_3xl_stuck_on_regular_is_problem(self):
        p = size_type_scan.judge_item("3XL", "Regular", fake_size_type_for)
        assert p == {"size": "3XL", "current_size_type": "Regular", "expected_size_type": "Big & Tall"}

    def test_3xl_already_big_and_tall_is_ok(self):
        assert size_type_scan.judge_item("3XL", "Big & Tall", fake_size_type_for) is None

    def test_2xl_regular_is_ok(self):
        assert size_type_scan.judge_item("2XL", "Regular", fake_size_type_for) is None

    def test_tall_suffix_stuck_on_regular_is_problem(self):
        p = size_type_scan.judge_item("XLT", "Regular", fake_size_type_for)
        assert p["expected_size_type"] == "Big & Tall"

    def test_missing_size_is_not_judged(self):
        assert size_type_scan.judge_item(None, "Regular", fake_size_type_for) is None
        assert size_type_scan.judge_item("", "Regular", fake_size_type_for) is None

    def test_missing_size_type_is_not_judged(self):
        assert size_type_scan.judge_item("3XL", None, fake_size_type_for) is None
        assert size_type_scan.judge_item("3XL", "", fake_size_type_for) is None

    def test_reverse_mismatch_also_flagged(self):
        """Big & Tall が付いているが本来 Regular で良いサイズ (逆方向の食い違いも検出)."""
        p = size_type_scan.judge_item("M", "Big & Tall", fake_size_type_for)
        assert p == {"size": "M", "current_size_type": "Big & Tall", "expected_size_type": "Regular"}


# ============================================================================
# collect_target_rows: R列カテゴリ + itemID フィルタ
# ============================================================================
class TestCollectTargetRows:
    def _row(self, item_id="", category="", title=""):
        row = [""] * (price_revise.COL_CATEGORY + 1)
        row[price_revise.COL_ITEM_ID] = item_id
        row[price_revise.COL_CATEGORY] = category
        row[price_revise.COL_TITLE] = title
        return row

    def test_filters_to_tshirt_and_outdoor_jacket_only(self, monkeypatch):
        rows_by_sheet = {
            "HIGH": ([], [
                self._row("111", "Tシャツ", "T1"),
                self._row("222", "アウトドア・ジャケット", "J1"),
                self._row("333", "G-shock", "G1"),  # 対象外カテゴリ
                self._row("", "Tシャツ", "T-noid"),  # itemID 空 → 除外
            ], None, "high_low"),
            "LOW": ([], [
                self._row("444", "Tシャツ", "T2"),
            ], None, "high_low"),
        }
        monkeypatch.setattr(price_revise, "load_sheet_rows", lambda key: rows_by_sheet[key])
        targets = size_type_scan.collect_target_rows(sheet_keys=("HIGH", "LOW"))
        ids = sorted(t["item_id"] for t in targets)
        assert ids == ["111", "222", "444"]

    def test_non_high_low_schema_skipped(self, monkeypatch):
        monkeypatch.setattr(price_revise, "load_sheet_rows",
                             lambda key: ([], [self._row("999", "Tシャツ")], None, "official"))
        targets = size_type_scan.collect_target_rows(sheet_keys=("HIGH",))
        assert targets == []


# ============================================================================
# _parse_item_specifics: Variations 内 VariationSpecifics を混同しない
# ============================================================================
class TestParseItemSpecifics:
    def test_extracts_department_size_sizetype(self):
        xml = """
        <Item>
          <ItemSpecifics>
            <NameValueList><Name>Department</Name><Value>Unisex Adults</Value></NameValueList>
            <NameValueList><Name>Size</Name><Value>3XL</Value></NameValueList>
            <NameValueList><Name>Size Type</Name><Value>Regular</Value></NameValueList>
          </ItemSpecifics>
        </Item>
        """
        specifics = ebay_trading_api._parse_item_specifics(xml)
        assert specifics == {"Department": "Unisex Adults", "Size": "3XL", "Size Type": "Regular"}

    def test_variation_specifics_not_confused_with_item_specifics(self):
        xml = """
        <Item>
          <ItemSpecifics>
            <NameValueList><Name>Department</Name><Value>Men</Value></NameValueList>
          </ItemSpecifics>
          <Variations>
            <Variation>
              <VariationSpecifics>
                <NameValueList><Name>Size</Name><Value>M</Value></NameValueList>
              </VariationSpecifics>
            </Variation>
          </Variations>
        </Item>
        """
        specifics = ebay_trading_api._parse_item_specifics(xml)
        assert specifics == {"Department": "Men"}

    def test_no_item_specifics_returns_empty(self):
        assert ebay_trading_api._parse_item_specifics("<Item></Item>") == {}


# ============================================================================
# get_item_specifics: requests.post をモック
# ============================================================================
class TestGetItemSpecifics:
    def test_success_parses_three_fields(self, monkeypatch):
        import requests

        class FakeResponse:
            status_code = 200
            text = """
            <GetItemResponse>
              <Item>
                <ItemSpecifics>
                  <NameValueList><Name>Department</Name><Value>Unisex Adults</Value></NameValueList>
                  <NameValueList><Name>Size</Name><Value>3XL</Value></NameValueList>
                  <NameValueList><Name>Size Type</Name><Value>Regular</Value></NameValueList>
                </ItemSpecifics>
              </Item>
            </GetItemResponse>
            """

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())
        result = ebay_trading_api.get_item_specifics("358000000001", access_token="dummy")
        assert result == {
            "department": "Unisex Adults",
            "size": "3XL",
            "size_type": "Regular",
            "error": None,
        }

    def test_http_error_returns_error_field(self, monkeypatch):
        import requests

        class FakeResponse:
            status_code = 500
            text = ""

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())
        result = ebay_trading_api.get_item_specifics("358000000001", access_token="dummy")
        assert result["error"] == "HTTP 500"
        assert result["size"] is None
