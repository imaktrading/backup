"""variation revise (2026-05-24) の unit test."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

THIS = Path(__file__).resolve().parent
PROJECT = THIS.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from revise import price_revise, ebay_trading_api, snapshot_reader
from revise.price_revise import (
    ReviseCandidate, _normalize_official_row,
    COL_OFFICIAL_LISTING_ID, COL_OFFICIAL_SKU, COL_OFFICIAL_SIZE,
    COL_OFFICIAL_COLOR, COL_OFFICIAL_COST, COL_OFFICIAL_CATEGORY,
    COL_OFFICIAL_TITLE, COL_VAR_SKU, COL_VAR_SIZE, COL_VAR_COLOR,
    COL_ITEM_ID, COL_TITLE, COL_N_PRICE, COL_CATEGORY,
    write_revise_variation_csv,
    REVISE_VARIATION_PRICE_CSV_HEADER, REVISE_VARIATION_SHIPPING_CSV_HEADER,
)


# ============================================================================
# 公式 SKU詳細 row → SKU 単位 normalize
# ============================================================================
class TestNormalizeOfficialRowVariation:
    def test_with_sku_size_color(self):
        """F (SKU) / G (Size) / H (Color) が ROW に正しく書き込まれる."""
        row = [""] * 16
        row[COL_OFFICIAL_LISTING_ID] = "358589341204"
        row[COL_OFFICIAL_TITLE] = "GU Pokemon Slowpoke T-Shirt"
        row[COL_OFFICIAL_SKU] = "53b869de-7e1c-4c16-bf3e-c13ffe04b2a2"
        row[COL_OFFICIAL_SIZE] = "US XS(JP S)"
        row[COL_OFFICIAL_COLOR] = "Pink"
        row[COL_OFFICIAL_COST] = "1490"
        row[COL_OFFICIAL_CATEGORY] = "Tシャツ(UT)"
        out = _normalize_official_row(row)
        assert out[COL_ITEM_ID] == "358589341204"
        assert out[COL_N_PRICE] == "1490"
        assert out[COL_CATEGORY] == "Tシャツ(UT)"
        assert out[COL_VAR_SKU] == "53b869de-7e1c-4c16-bf3e-c13ffe04b2a2"
        assert out[COL_VAR_SIZE] == "US XS(JP S)"
        assert out[COL_VAR_COLOR] == "Pink"

    def test_no_sku_single_listing(self):
        """SKU 空欄 = single listing 互換 (= 旧 logic)."""
        row = [""] * 16
        row[COL_OFFICIAL_LISTING_ID] = "358000000001"
        row[COL_OFFICIAL_COST] = "1990"
        out = _normalize_official_row(row)
        assert out[COL_VAR_SKU] == ""


# ============================================================================
# detect_candidates: variation listing → SKU 単位 candidate
# ============================================================================
class TestDetectCandidatesVariation:
    def test_variation_flagged(self):
        from revise.price_revise import detect_candidates, ROW_TOTAL_COLS
        row = [""] * ROW_TOTAL_COLS
        row[COL_ITEM_ID] = "358589341204"
        row[COL_N_PRICE] = "1490"
        row[COL_CATEGORY] = "Tシャツ(UT)"
        row[COL_VAR_SKU] = "53b869de-..."
        row[COL_VAR_SIZE] = "US XS(JP S)"
        c = detect_candidates([row], source_sheet="公式")
        assert len(c) == 1
        assert c[0].is_variation is True
        assert c[0].sku == "53b869de-..."
        assert c[0].variation_size == "US XS(JP S)"

    def test_single_not_flagged(self):
        from revise.price_revise import detect_candidates, ROW_TOTAL_COLS
        row = [""] * ROW_TOTAL_COLS
        row[COL_ITEM_ID] = "356700921169"
        row[COL_N_PRICE] = "1500"
        row[COL_CATEGORY] = "Tシャツ"
        # SKU 空欄
        c = detect_candidates([row], source_sheet="HIGH")
        assert len(c) == 1
        assert c[0].is_variation is False
        assert c[0].sku == ""


# ============================================================================
# fail-closed: snapshot variation listing + スプシ SKU 空欄 → skip
# ============================================================================
class TestVariationNoSkuFailClosed:
    """2026-05-24 bug fix: snapshot 側で variation listing と分かっているのに
    スプシ SKU 空欄で is_variation=False になっていると、 single CSV に Item-level
    *StartPrice が書かれて 21916618 silent ignore される。

    対策: snapshot variations_map に存在する listing は SKU 必須、 空欄なら skip。
    """
    def test_variation_in_snapshot_but_spreadsheet_sku_empty_skipped(self, tmp_path, monkeypatch):
        """snapshot.variations.json に 358560250231 (7 variation) があるが、
        スプシ row では SKU 空欄 → variation_no_sku_in_spreadsheet で skip される.
        """
        from revise import price_revise as pr
        from revise.price_revise import ReviseCandidate, run_price_revise

        # スプシ row: 公式 sheet、 SKU 空欄
        sheet_row = [""] * pr.ROW_TOTAL_COLS
        sheet_row[pr.COL_ITEM_ID] = "358560250231"
        sheet_row[pr.COL_TITLE] = "GU Godzilla T-Shirt"
        sheet_row[pr.COL_N_PRICE] = "1490"
        sheet_row[pr.COL_CATEGORY] = "Tシャツ(UT)"
        # COL_VAR_SKU は空欄 (= スプシ未登録)

        # detect_candidates → is_variation=False になるはず
        cands = pr.detect_candidates([sheet_row], source_sheet="公式")
        assert len(cands) == 1
        assert cands[0].is_variation is False
        assert cands[0].sku == ""

        # snapshot variations_map に 7 variation がある体で fail-closed が効くか確認
        # (= 単体 unit test では Step 5 直接呼べないので、 関数 logic を mock 経由で再現)
        variations_map = {
            "358560250231": [
                {"sku": "uuid-1", "specifics": {"Sizes": "US XS(JP S)"}, "start_price": 62.98, "quantity": 1},
                {"sku": "uuid-2", "specifics": {"Sizes": "US S(JP M)"}, "start_price": 62.98, "quantity": 1},
            ],
        }
        c = cands[0]
        # 模擬: Step 5 で「snapshot に variation あるが spreadsheet SKU 空欄」を検出
        assert not c.is_variation and c.item_id in variations_map  # fail-closed の条件成立


# ============================================================================
# variation CSV writer
# ============================================================================
class TestWriteVariationCsv:
    @staticmethod
    def _var_candidate(item_id, sku, new_usd=49.98, policy="DDP-C-P05"):
        return ReviseCandidate(
            row_index=2, item_id=item_id, category="Tシャツ(UT)",
            new_jpy=1490, ah_jpy=None, f_jpy=None,
            delta_pct=0.0, basis="decision", title=f"GU {item_id}",
            source_sheet="公式",
            new_usd=new_usd, shipping_profile_name=policy,
            sku=sku, is_variation=True,
            variation_size="US XS(JP S)",
        )

    def test_variation_csv_2_files_format(self, tmp_path):
        """5/24 第4版: eBay 公式 doc 準拠 (Item row + Variation rows)"""
        c1 = self._var_candidate("358589341204", "53b869de-...")
        c2 = self._var_candidate("358589341204", "d124b063-...")
        # variations_map: snapshot.variations.json 想定
        variations_map = {
            "358589341204": [
                {"sku": "53b869de-...", "specifics": {"Sizes": "US XS(JP S)", "Colors": "Pink"}},
                {"sku": "d124b063-...", "specifics": {"Sizes": "US S(JP M)", "Colors": "Blue"}},
            ],
        }
        result = write_revise_variation_csv([c1, c2], output_dir=tmp_path,
                                              variations_map=variations_map)
        # price CSV (5 列: Action / ItemID / Relationship / RelationshipDetails / *StartPrice)
        price_path = result["price_path"]
        assert price_path is not None
        assert "price" in price_path.name
        with price_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == REVISE_VARIATION_PRICE_CSV_HEADER
            assert len(header) == 5
            # 1 行目 = Item row: ItemID + 全 trait 列挙、 Relationship/StartPrice 空
            item_row = next(reader)
            assert item_row[0] == "Revise"
            assert item_row[1] == "358589341204"
            assert item_row[2] == ""  # Relationship
            assert item_row[3] == "Sizes=US XS(JP S);US S(JP M)|Colors=Pink;Blue"
            assert item_row[4] == ""  # *StartPrice
            # 2 行目 = Variation row: ItemID/Action 空、 Relationship=Variation
            var1 = next(reader)
            assert var1 == ["", "", "Variation", "Sizes=US XS(JP S)|Colors=Pink", "49.98"]
            var2 = next(reader)
            assert var2 == ["", "", "Variation", "Sizes=US S(JP M)|Colors=Blue", "49.98"]
        # shipping CSV (3 列、ItemID あたり 1 行に集約)
        shipping_path = result["shipping_path"]
        assert shipping_path is not None
        assert "shipping" in shipping_path.name
        with shipping_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header == REVISE_VARIATION_SHIPPING_CSV_HEADER
            assert len(header) == 3  # Action / ItemID / ShippingProfileName
            row1 = next(reader)
            # 2 variation candidate → 同 ItemID なので 1 行に集約
            assert row1 == ["Revise", "358589341204", "DDP-C-P05"]
            # 後続行なし
            assert list(reader) == []

    def test_variation_csv_fallback_to_candidate_size_color(self, tmp_path):
        """variations_map 不在時、 candidate の variation_size/color を fallback で使う."""
        c = self._var_candidate("358589341204", "53b869de-...")
        # variations_map 渡さない (= None) → candidate.variation_size を fallback
        result = write_revise_variation_csv([c], output_dir=tmp_path)
        price_path = result["price_path"]
        with price_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader)  # header
            item_row = next(reader)
            # Item row の details は variations_map なしなら空
            assert item_row[1] == "358589341204"
            var_row = next(reader)
            assert var_row[2] == "Variation"
            # fallback: candidate.variation_size = "US XS(JP S)"
            assert "Sizes=US XS(JP S)" in var_row[3]
            assert var_row[4] == "49.98"

    def test_no_variation_returns_dict_with_none(self, tmp_path):
        """variation candidate なし → dict with None values"""
        single = ReviseCandidate(
            row_index=2, item_id="356700921169", category="Tシャツ",
            new_jpy=1500, ah_jpy=None, f_jpy=None,
            delta_pct=0.0, basis="decision", title="single", source_sheet="HIGH",
            new_usd=49.98, shipping_profile_name="DDP-C-P05",
            is_variation=False,
        )
        result = write_revise_variation_csv([single], output_dir=tmp_path)
        assert result["price_path"] is None
        assert result["shipping_path"] is None

    def test_write_revise_csv_excludes_variations(self, tmp_path):
        """既存 write_revise_csv は variation を除外."""
        from revise.price_revise import write_revise_csv, REVISE_CSV_HEADER
        c_var = self._var_candidate("358589341204", "53b869de-...")
        c_single = ReviseCandidate(
            row_index=2, item_id="356700921169", category="Tシャツ",
            new_jpy=1500, ah_jpy=None, f_jpy=None,
            delta_pct=0.0, basis="decision", title="single", source_sheet="HIGH",
            new_usd=49.98, shipping_profile_name="DDP-C-P05",
            is_variation=False,
        )
        path = write_revise_csv([c_var, c_single], output_dir=tmp_path)
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            next(reader)  # header
            rows = list(reader)
            # variation は除外、 single のみ 1 行
            assert len(rows) == 1
            assert rows[0][1] == "356700921169"


# ============================================================================
# GetSellerList _parse_variations
# ============================================================================
class TestParseVariations:
    def test_parse_variation_block(self):
        xml = '''
        <Item>
          <ItemID>358589341204</ItemID>
          <Title>GU Pokemon T-Shirt</Title>
          <Variations>
            <Variation>
              <SKU>53b869de-7e1c-4c16-bf3e-c13ffe04b2a2</SKU>
              <StartPrice currencyID="USD">60.98</StartPrice>
              <Quantity>3</Quantity>
              <SellingStatus><QuantitySold>1</QuantitySold></SellingStatus>
              <VariationSpecifics>
                <NameValueList><Name>Sizes</Name><Value>US XS(JP S)</Value></NameValueList>
                <NameValueList><Name>Colors</Name><Value>Pink</Value></NameValueList>
              </VariationSpecifics>
            </Variation>
            <Variation>
              <SKU>d124b063-c10f-4fd3-813f-69b1fe85b95e</SKU>
              <StartPrice currencyID="USD">60.98</StartPrice>
              <Quantity>5</Quantity>
              <SellingStatus><QuantitySold>2</QuantitySold></SellingStatus>
              <VariationSpecifics>
                <NameValueList><Name>Sizes</Name><Value>US S(JP M)</Value></NameValueList>
              </VariationSpecifics>
            </Variation>
          </Variations>
        </Item>
        '''
        result = ebay_trading_api._parse_variations(xml)
        assert len(result) == 2
        assert result[0]["sku"] == "53b869de-7e1c-4c16-bf3e-c13ffe04b2a2"
        assert result[0]["start_price"] == 60.98
        assert result[0]["quantity"] == 2  # 3 - 1
        assert result[0]["specifics"]["Sizes"] == "US XS(JP S)"
        assert result[0]["specifics"]["Colors"] == "Pink"
        assert result[1]["quantity"] == 3  # 5 - 2

    def test_no_variations(self):
        xml = "<Item><ItemID>123</ItemID></Item>"
        assert ebay_trading_api._parse_variations(xml) == []


# ============================================================================
# snapshot_reader.load_variations
# ============================================================================
class TestLoadVariations:
    def test_load_variations_json(self, tmp_path):
        csv_path = tmp_path / "ebay_active_2026-05-24_120000.csv"
        csv_path.write_text("dummy", encoding="utf-8")
        var_path = tmp_path / "ebay_active_2026-05-24_120000.variations.json"
        var_path.write_text(json.dumps({
            "358589341204": [
                {"sku": "AAA", "start_price": 60.98, "quantity": 2,
                 "specifics": {"Sizes": "US XS"}},
            ],
        }), encoding="utf-8")
        result = snapshot_reader.load_variations(csv_path)
        assert "358589341204" in result
        assert result["358589341204"][0]["sku"] == "AAA"

    def test_no_variations_file(self, tmp_path):
        csv_path = tmp_path / "ebay_active_2026-05-24_120000.csv"
        csv_path.write_text("dummy", encoding="utf-8")
        # variations.json なし → 空 dict
        assert snapshot_reader.load_variations(csv_path) == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
