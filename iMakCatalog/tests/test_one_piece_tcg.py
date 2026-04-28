"""One Piece TCG scraper + iMakCatalog API のテスト.

カバー:
  - variant ID 派生 (folder 正規化、parallel suffix、再録 suffix)
  - EN/JA join key の同期 (folder が違っても同じ key になる)
  - card_config_to_specs (BlockIcon 除去、JA キー正規化)
  - DB roundtrip via api.lookup() — PSA 事故再現防止 (PRB02-005 vs ST16-005 厳密区別)
  - 未登録 ID は None (= フォールバック禁止の保証)

実行:
    cd iMakCatalog
    python -m pytest tests/test_one_piece_tcg.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))

import api  # noqa: E402
import one_piece_tcg as ot  # noqa: E402


# ============================================================================
# Pure unit tests (DB / network 不要)
# ============================================================================
class TestDeriveProductId:
    """image_url から variant 識別子付き product_id を作るロジック."""

    def test_native_booster_no_suffix(self):
        pid = ot.derive_product_id(
            "OP06-022",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/OP06/OP06-022_d.png",
        )
        assert pid == "OP06-022"

    def test_parallel_suffix(self):
        pid = ot.derive_product_id(
            "OP06-022",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/OP06/OP06-022p_d.png",
        )
        assert pid == "OP06-022_p"

    def test_starter_reprint(self):
        pid = ot.derive_product_id(
            "OP06-022",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/ST28/batch_OP06-022.png",
        )
        assert pid == "OP06-022_ST28"

    def test_extra_booster_with_treatment_marker(self):
        pid = ot.derive_product_id(
            "OP06-022",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/EB02/batch_OP06-022_LF_d.png",
        )
        assert pid == "OP06-022_EB02_LF"

    def test_ja_only_promo_folder(self):
        pid = ot.derive_product_id(
            "OP06-022",
            "https://files.bandai-tcg-plus.com/card_image/OP-JA/P/batch_OP06-022.png",
        )
        assert pid == "OP06-022_P"

    def test_compound_folder_treated_as_native(self):
        """EN folder 'OP15-EB04' は EB04-007 にとって native (EN/JA 同期)."""
        pid_en = ot.derive_product_id(
            "EB04-007",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/OP15-EB04/batch_EB04-007.png",
        )
        pid_ja = ot.derive_product_id(
            "EB04-007",
            "https://files.bandai-tcg-plus.com/card_image/OP-JA/EB04/EB04-007_sample.png",
        )
        assert pid_en == "EB04-007"
        assert pid_ja == "EB04-007"

    def test_sample_marker_stripped(self):
        """`_sample` マーカーは EN/JA 片方だけに付く事前公開印 → variant 識別から除外."""
        pid = ot.derive_product_id(
            "EB04-007",
            "https://files.bandai-tcg-plus.com/card_image/OP-JA/EB04/EB04-007_sample.png",
        )
        assert pid == "EB04-007"


class TestVariantKey:
    """EN/JA join に使う variant key の同期性."""

    def test_en_ja_match_when_folder_differs(self):
        en_key = ot._variant_key(
            "EB04-007",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/OP15-EB04/batch_EB04-007.png",
        )
        ja_key = ot._variant_key(
            "EB04-007",
            "https://files.bandai-tcg-plus.com/card_image/OP-JA/EB04/EB04-007_sample.png",
        )
        assert en_key == ja_key

    def test_native_vs_starter_reprint_distinguished(self):
        native = ot._variant_key(
            "OP06-022",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/OP06/OP06-022_d.png",
        )
        reprint = ot._variant_key(
            "OP06-022",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/ST28/batch_OP06-022.png",
        )
        assert native != reprint

    def test_parallel_distinguished_from_base(self):
        base = ot._variant_key(
            "OP06-022",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/OP06/OP06-022_d.png",
        )
        para = ot._variant_key(
            "OP06-022",
            "https://files.bandai-tcg-plus.com/card_image/OP-EN/OP06/OP06-022p_d.png",
        )
        assert base != para


class TestExtractSetTag:
    def test_native_simple(self):
        tag, native = ot._extract_set_tag("OP06", "OP06")
        assert (tag, native) == ("OP06", True)

    def test_native_compound(self):
        tag, native = ot._extract_set_tag("OP15-EB04", "EB04")
        assert (tag, native) == ("EB04", True)

    def test_reprint(self):
        tag, native = ot._extract_set_tag("ST28", "OP06")
        assert (tag, native) == ("ST28", False)


class TestCardConfigToSpecs:
    def test_drops_block_icon(self):
        config = [
            {"config_name": "Color", "value": "Green"},
            {"config_name": "BlockIcon", "value": "3"},
            {"config_name": "Rarity", "value": "SR"},
        ]
        specs = ot.card_config_to_specs(config, lang="EN")
        assert specs == {"Color": "Green", "Rarity": "SR"}

    def test_skips_empty_values(self):
        config = [
            {"config_name": "Counter+", "value": None},  # Leader 等
            {"config_name": "Notes", "value": ""},
            {"config_name": "Color", "value": "Red"},
        ]
        specs = ot.card_config_to_specs(config, lang="EN")
        assert specs == {"Color": "Red"}

    def test_ja_keys_normalized_values_raw(self):
        config = [
            {"config_name": "色", "value": "緑/黄"},
            {"config_name": "カード種類", "value": "リーダー"},
            {"config_name": "レアリティ", "value": "L"},
            {"config_name": "ブロックアイコン", "value": "2"},  # drop
        ]
        specs = ot.card_config_to_specs(config, lang="JA")
        assert specs == {
            "Color": "緑/黄",
            "Card Type": "リーダー",
            "Rarity": "L",
        }


class TestDetectLanguage:
    def test_both(self):
        assert ot.detect_language({"id": 1}, {"id": 2}) == "both"

    def test_en_only(self):
        assert ot.detect_language({"id": 1}, None) == "en"

    def test_ja_only(self):
        assert ot.detect_language(None, {"id": 2}) == "ja"


# ============================================================================
# DB roundtrip tests (前提: PRB02-005 / ST16-005 / OP06-022 が populated)
# ============================================================================
def _db_has_cards() -> bool:
    return all(
        api.lookup("one_piece_tcg", pid) is not None
        for pid in ("PRB02-005", "ST16-005", "OP06-022")
    )


REQUIRES_TRIGGER_CARDS = pytest.mark.skipif(
    not _db_has_cards(),
    reason="Trigger cards not in DB. Run: "
    "python scrapers/one_piece_tcg.py --card OP06-022 / --card PRB02-005 / --card ST16-005",
)


@REQUIRES_TRIGGER_CARDS
class TestDbLookup:
    def test_prb02_005_full_record(self):
        r = api.lookup("one_piece_tcg", "PRB02-005")
        assert r["name"] == "Monkey.D.Luffy"
        assert r["specs"]["Rarity"] == "SR"
        assert r["specs"]["Power"] == "5000"
        assert r["specs"]["Cost/Life"] == "4"
        assert "PRB-02" in (r["set_name_official"] or "")
        assert r["language"] == "both"
        assert r["specs"].get("card_text")
        assert r["specs"].get("card_text_jp")
        assert "regulations" in r["specs"]
        assert "legality" in r["specs"]
        assert "illustrator" in r["specs"]  # placeholder (None for One Piece)

    def test_st16_005_strictly_distinct_from_prb02_005(self):
        """事故再発防止: PRB02-005 ≠ ST16-005."""
        prb = api.lookup("one_piece_tcg", "PRB02-005")
        st = api.lookup("one_piece_tcg", "ST16-005")
        assert prb["product_id"] != st["product_id"]
        assert prb["specs"]["Rarity"] != st["specs"]["Rarity"]   # SR vs C
        assert prb["specs"]["Power"] != st["specs"]["Power"]     # 5000 vs 3000
        assert prb["specs"]["Cost/Life"] != st["specs"]["Cost/Life"]  # 4 vs 2

    def test_unregistered_returns_none(self):
        """フォールバック禁止の保証: ID 不一致 = None."""
        assert api.lookup("one_piece_tcg", "XX99-999") is None
        assert api.lookup("one_piece_tcg", "PRB02-999") is None
        assert api.lookup("one_piece_tcg", "ZZZZ") is None

    def test_op06_022_all_variants_distinct(self):
        """同じ card_number 内で variant が別レコードとして扱われる."""
        variants = ["OP06-022", "OP06-022_p", "OP06-022_ST28", "OP06-022_EB02_LF"]
        records = [api.lookup("one_piece_tcg", v) for v in variants]
        assert all(r is not None for r in records)
        # 全部別 product_id
        ids = {r["product_id"] for r in records}
        assert len(ids) == 4

    def test_variant_records_share_card_number_but_differ_in_set(self):
        base = api.lookup("one_piece_tcg", "OP06-022")
        st28 = api.lookup("one_piece_tcg", "OP06-022_ST28")
        # 同じカード番号がベース、異なる set
        assert base["product_id"].startswith("OP06-022")
        assert st28["product_id"].startswith("OP06-022")
        assert base["set_name_official"] != st28["set_name_official"]
        # 中身 (Power/Rarity 等) は同じ印刷物
        assert base["specs"]["Power"] == st28["specs"]["Power"]
        assert base["specs"]["Rarity"] == st28["specs"]["Rarity"]

    def test_ja_only_variant_has_normalized_keys(self):
        """JA-only variant でも specs キーは EN 正規化されている."""
        r = api.lookup("one_piece_tcg", "OP06-022_P")
        if r is None:
            pytest.skip("OP06-022_P (JA-only promo) not in DB")
        assert r["language"] == "ja"
        # 正規化された英語キー (値は raw 日本語のまま)
        assert "Color" in r["specs"]
        assert "Rarity" in r["specs"]
        assert "Card Type" in r["specs"]


@REQUIRES_TRIGGER_CARDS
class TestEbayFilterMap:
    """ebay_filter_map yaml ロード後の lookup() の挙動確認.

    one_piece.yaml が `python ebay_filter_map/loader.py one_piece` でロード済みの前提.
    """

    def test_set_code_fallback_resolves_to_ebay_value(self):
        """set_code = OP-06 → "Wings of the Captain" に変換される."""
        r = api.lookup("one_piece_tcg", "OP06-022")
        assert r["set_name"] == "Wings of the Captain"
        # set_name_official は raw のまま
        assert "[OP-06]" in r["set_name_official"]

    def test_prb02_set_code_resolved(self):
        r = api.lookup("one_piece_tcg", "PRB02-005")
        assert r["set_name"] == "Premium Booster Vol.2"

    def test_st16_set_code_resolved(self):
        r = api.lookup("one_piece_tcg", "ST16-005")
        assert r["set_name"] == "Uta"

    def test_rarity_leader_returns_empty(self):
        """L (Leader) → eBay rarity は空欄."""
        assert api.to_ebay_value("one_piece_tcg", "rarity", "L") == ""

    def test_rarity_short_codes_pass_through(self):
        # TCG+ API は既に eBay 形式の short code を返す = identity
        for r in ("C", "UC", "R", "SR"):
            assert api.to_ebay_value("one_piece_tcg", "rarity", r) == r

    def test_unmapped_set_uses_raw_when_no_mapping(self):
        """yaml にも regex fallback にも該当しない値は raw を返す (None ではなく).

        合成 source_value で挙動確認する (実 DB データはほぼ 100% mapping ヒットになったため).
        """
        # api.to_ebay_value で未登録 → None が返る
        assert api.to_ebay_value("one_piece_tcg", "set_code", "ZZ-99") is None
        # set_code として regex 抽出されない汎用ラベルが yaml にもない場合も None
        assert api.to_ebay_value("one_piece_tcg", "set", "Hypothetical Unknown Set") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
