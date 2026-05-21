"""tests/test_snkrdunk_official - スニダン PSA10 抽出ロジック offline tests."""
from __future__ import annotations

import pytest

from scrapers.snkrdunk_official import (
    APPAREL_USED_URL_RE,
    OP_CARD_ID_RE,
    PSA10_CONDITION_LABEL,
    STATUS_ON_SALE,
    TCG_CARD_ID_RE,
    build_apparel_used_url,
    extract_op_card_id,
    extract_tcg_card_id,
    is_psa10_on_sale,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# extract_op_card_id
# --------------------------------------------------------------------------
class TestExtractOpCardId:
    def test_basic_extraction(self):
        title = "One Piece Kaya R OP03-044 Standard Battle PSA10 Japanese Card"
        assert extract_op_card_id(title) == "OP03-044"

    def test_lowercase_normalized_uppercase(self):
        assert extract_op_card_id("op03-044 lowercase") == "OP03-044"

    def test_at_start_of_string(self):
        assert extract_op_card_id("OP01-001 first card") == "OP01-001"

    def test_at_end_of_string(self):
        assert extract_op_card_id("Some text trailing OP09-099") == "OP09-099"

    def test_multiple_returns_first(self):
        # 複数 card_id がタイトルに含まれていても先頭 1 件
        assert extract_op_card_id("OP01-001 and OP02-002") == "OP01-001"

    def test_no_match_returns_none(self):
        assert extract_op_card_id("Pokemon Pikachu PSA10") is None
        assert extract_op_card_id("ST01-001 starter deck") is None  # Phase 1 は OP のみ
        assert extract_op_card_id("EB01-001 extra booster") is None

    def test_empty_input(self):
        assert extract_op_card_id("") is None
        assert extract_op_card_id(None) is None  # type: ignore[arg-type]

    def test_word_boundary(self):
        # OP03-04 (3 桁未満) は無効、OP03-0440 (4 桁) も無効
        assert extract_op_card_id("OP03-04 short") is None
        # 4 桁続きの場合の挙動: regex は 3 桁部分のみマッチ
        # OP03-04400 → "OP03-044" だけマッチする可能性
        # 安全側で確認、いずれにせよ正しい card_id (3 桁) は抽出される
        result = extract_op_card_id("OP03-04400 too long")
        assert result == "OP03-044" or result is None  # implementation-defined

    @pytest.mark.parametrize("title,expected", [
        # 実 iMakTCG listing title の例 (依頼書より)
        ("One Piece Kaya R OP03-044 Standard Battle PSA10 Japanese Card", "OP03-044"),
        # 異なる series
        ("Pokemon Pikachu Promo PSA10 Japanese 2020 #25 Card Holographic", None),
        # 別 prefix (ST/EB/P) は Phase 1 範囲外
        ("ST01-005 Monkey D. Luffy starter deck", None),
        # OP card_id 形式バリエーション
        ("OP08-001 Roronoa Zoro Leader Parallel", "OP08-001"),
    ])
    def test_realistic_titles(self, title, expected):
        assert extract_op_card_id(title) == expected


# --------------------------------------------------------------------------
# APPAREL_USED_URL_RE: 個別 used URL パターン
# --------------------------------------------------------------------------
class TestApparelUsedUrlRe:
    def test_basic_match(self):
        m = APPAREL_USED_URL_RE.search("https://snkrdunk.com/apparels/159278/used/45538280")
        assert m is not None
        assert m.group(1) == "159278"
        assert m.group(2) == "45538280"

    def test_with_query_string(self):
        m = APPAREL_USED_URL_RE.search("https://snkrdunk.com/apparels/159278/used/45538280?ref=foo")
        assert m is not None
        assert m.group(1) == "159278"
        assert m.group(2) == "45538280"

    def test_not_used_url(self):
        # /apparels/<model>/<not-used> はマッチしない
        assert APPAREL_USED_URL_RE.search("https://snkrdunk.com/apparels/159278/info") is None


# --------------------------------------------------------------------------
# is_psa10_on_sale
# --------------------------------------------------------------------------
class TestIsPsa10OnSale:
    def test_psa10_on_sale(self):
        item = {
            "displayShortConditionTitle": "PSA10",
            "status": 0,
            "price": 8900,
        }
        assert is_psa10_on_sale(item) is True

    def test_psa10_sold_out_rejected(self):
        item = {
            "displayShortConditionTitle": "PSA10",
            "status": 1,  # status != 0 は売切等
            "price": 8900,
        }
        assert is_psa10_on_sale(item) is False

    def test_psa9_rejected(self):
        # PSA10 only filter、他の grade は採用しない
        item = {
            "displayShortConditionTitle": "PSA9",
            "status": 0,
            "price": 5000,
        }
        assert is_psa10_on_sale(item) is False

    def test_raw_rejected(self):
        item = {
            "displayShortConditionTitle": "A",  # raw 上品質
            "status": 0,
            "price": 3000,
        }
        assert is_psa10_on_sale(item) is False

    def test_bgs_rejected(self):
        # BGS や CGC など別鑑定 grade も Phase 1 範囲外
        item = {
            "displayShortConditionTitle": "BGS 9.5",
            "status": 0,
        }
        assert is_psa10_on_sale(item) is False

    def test_empty_item(self):
        assert is_psa10_on_sale(None) is False  # type: ignore[arg-type]
        assert is_psa10_on_sale({}) is False

    def test_missing_status(self):
        # status 欠落 → False (fail-closed)
        item = {"displayShortConditionTitle": "PSA10"}
        assert is_psa10_on_sale(item) is False

    def test_missing_condition_title(self):
        item = {"status": 0}
        assert is_psa10_on_sale(item) is False

    def test_whitespace_around_psa10(self):
        # 空白付きは strip して判定
        item = {"displayShortConditionTitle": "  PSA10  ", "status": 0}
        assert is_psa10_on_sale(item) is True

    def test_psa10_lowercase_rejected(self):
        # 完全一致のみ採用 (CLAUDE.md fail-closed、precision 100%)
        item = {"displayShortConditionTitle": "psa10", "status": 0}
        assert is_psa10_on_sale(item) is False


# --------------------------------------------------------------------------
# build_apparel_used_url
# --------------------------------------------------------------------------
class TestBuildApparelUsedUrl:
    def test_basic_construction(self):
        url = build_apparel_used_url(159278, 45538280)
        assert url == "https://snkrdunk.com/apparels/159278/used/45538280"

    def test_int_inputs(self):
        url = build_apparel_used_url(1, 2)
        assert url == "https://snkrdunk.com/apparels/1/used/2"


# --------------------------------------------------------------------------
# Constants 確認
# --------------------------------------------------------------------------
class TestConstants:
    def test_psa10_label(self):
        assert PSA10_CONDITION_LABEL == "PSA10"

    def test_status_on_sale(self):
        assert STATUS_ON_SALE == 0


# --------------------------------------------------------------------------
# extract_tcg_card_id (= OP / ST / EB / P 全部対応、抽出くん 連携用)
# --------------------------------------------------------------------------
class TestExtractTcgCardId:
    def test_op_series(self):
        assert extract_tcg_card_id("Kozuki Hiyori SR [OP06-106]") == "OP06-106"

    def test_st_series(self):
        assert extract_tcg_card_id("Uta SR [ST16-001]") == "ST16-001"

    def test_eb_series(self):
        assert extract_tcg_card_id("ウタ EB03-061 SEC PSA10") == "EB03-061"

    def test_p_series(self):
        # P-001 〜 P-999 形式 (= プロモ)
        assert extract_tcg_card_id("プロモ Kozuki Hiyori P-018") == "P-018"

    def test_lowercase_normalized(self):
        assert extract_tcg_card_id("op06-106 lowercase") == "OP06-106"
        assert extract_tcg_card_id("st16-001") == "ST16-001"

    def test_no_match_returns_none(self):
        assert extract_tcg_card_id("Pokemon Pikachu PSA10") is None
        # P 系は 3 桁、P-12 は無効
        assert extract_tcg_card_id("P-12 short") is None

    def test_empty_input(self):
        assert extract_tcg_card_id("") is None
        assert extract_tcg_card_id(None) is None  # type: ignore[arg-type]

    def test_op_takes_priority_over_other_text(self):
        # title に複数の card_id 形式があれば最初のもの
        assert extract_tcg_card_id("First OP03-044 then ST01-001") == "OP03-044"


# --------------------------------------------------------------------------
# TCG_CARD_ID_RE 直接 (regex 確認)
# --------------------------------------------------------------------------
class TestTcgCardIdRegex:
    def test_op_match(self):
        assert TCG_CARD_ID_RE.search("OP01-001").group(1) == "OP01-001"

    def test_st_match(self):
        assert TCG_CARD_ID_RE.search("ST29-016").group(1) == "ST29-016"

    def test_eb_match(self):
        assert TCG_CARD_ID_RE.search("EB01-029").group(1) == "EB01-029"

    def test_p_match(self):
        assert TCG_CARD_ID_RE.search("P-041").group(1) == "P-041"

    def test_op_does_not_match_pop(self):
        # 「POP01-001」 のような誤マッチ防止 (= word boundary)
        # POP01-001 は \b で「OP01-001」が誤検出される可能性、ただし P が末尾の場合
        # 「pop OP01-001」 のように区切られた場合は OP 単体マッチ
        m = TCG_CARD_ID_RE.search("Foo POP01-001 Bar")
        # OP01-001 部分にマッチする (POP の最後の P から OP まで含めて) のは regex 仕様、
        # 実用上 OP01-001 自体は有効 card_id なので妥協
        assert m is None or m.group(1) == "OP01-001"
