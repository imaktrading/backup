"""csv_write_keys unit tests (offline, mock ws)."""

import csv
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dedupe import csv_write_keys
from dedupe.checker import extract_priority_key2

pytestmark = pytest.mark.offline


def _make_csv(path: Path, rows: list, fieldnames: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        w.writerows(rows)


CSV_FIELDS = [
    "*Title",
    "C:Card Number",
    "C:Features",
    "C:Speciality",
    "CDA:Certification Number - (ID: 27503)",
]


class TestExtractCertAndKeys:
    def test_with_cert_card_variant(self):
        row = {
            "*Title": "PSA 10 One Piece OP04-039 Rebecca Alternate Art",
            "C:Card Number": "OP04-039",
            "C:Features": "Alternative Art",
            "CDA:Certification Number - (ID: 27503)": "149657853",
        }
        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2
        )
        assert cert == "149657853"
        assert k1 == "OP04-039"
        assert t1 == "card"
        assert k2 == "alt"

    def test_no_cert(self):
        row = {
            "*Title": "PSA 10 OP05-060",
            "C:Card Number": "OP05-060",
            "CDA:Certification Number - (ID: 27503)": "",
        }
        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2
        )
        assert cert == ""
        assert k1 == "OP05-060"

    def test_card_number_fallback_when_title_misses(self):
        row = {
            "*Title": "Random title with no card_id",
            "C:Card Number": "OP09-061",
            "CDA:Certification Number - (ID: 27503)": "97120564",
        }
        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2
        )
        assert k1 == "OP09-061"

    def test_don_fallback_via_lookup_fn(self):
        """Phase 1j: DON カード = 通常 logic で取れない + title に DON 含む → lookup_don fallback."""
        row = {
            "*Title": "PSA 10 One Piece TCG Don!! Card Alternate Art OP15 Adventure Island",
            "C:Card Number": "",
            "CDA:Certification Number - (ID: 27503)": "156219827",
        }
        calls = []

        def fake_lookup_don(brand, subject):
            calls.append((brand, subject))
            return {"product_id": "DON-OP15-002"}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2, lookup_don_fn=fake_lookup_don
        )
        assert cert == "156219827"
        assert k1 == "DON-OP15-002"
        assert t1 == "card"
        assert k2 == ""
        assert len(calls) == 1

    def test_don_fallback_returns_none_keeps_k1_empty(self):
        """lookup_don が None → KEY1 空維持 (= fail-closed)."""
        row = {
            "*Title": "Don!! Card unknown variant",
            "C:Card Number": "",
            "CDA:Certification Number - (ID: 27503)": "999",
        }

        def fake_lookup_don(brand, subject):
            return None

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2, lookup_don_fn=fake_lookup_don
        )
        assert k1 is None

    def test_don_fallback_skipped_when_title_has_no_don(self):
        """title に DON 含まない → lookup_don 呼ばない."""
        row = {
            "*Title": "Normal PSA 10 card title",
            "C:Card Number": "",
        }
        calls = []

        def fake_lookup_don(brand, subject):
            calls.append((brand, subject))
            return {"product_id": "X"}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2, lookup_don_fn=fake_lookup_don
        )
        assert calls == []  # 呼ばれない
        assert k1 is None

    def test_don_fallback_skipped_when_k1_already_extracted(self):
        """通常 logic で k1 取れる場合は lookup_don 呼ばない."""
        row = {
            "*Title": "PSA 10 Don!! Card OP15-001 normal extraction",
            "C:Card Number": "OP15-001",
        }
        calls = []

        def fake_lookup_don(brand, subject):
            calls.append((brand, subject))
            return {"product_id": "X"}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2, lookup_don_fn=fake_lookup_don
        )
        assert calls == []
        assert k1 == "OP15-001"

    def test_don_psa_brand_subject_columns_no_longer_read(self):
        """Phase 1q (= 5/28 体系再設計): C:PSA Brand / C:PSA Subject 列は読込まれない (= 撤回確認).

        新 logic は cert → iMakeBayAPI cache 経由で brand/subject 取得。
        CSV に C:PSA Brand/Subject 列があっても **採用されない**。
        title-only で DON keyword 検出 + lookup_don 呼出 (= cert 経路は cache miss なら fallback)。
        """
        row = {
            "*Title": "PSA 10 DON title alternate art",
            "C:Card Number": "",
            "C:PSA Brand": "ONE PIECE JAPANESE OP15-ADVENTURE ON KAMI'S ISLAND",
            "C:PSA Subject": "DON!! CARD ALTERNATE ART GOLD",
            "CDA:Certification Number - (ID: 27503)": "9999_no_cache_hit",
        }
        calls = []

        def fake_lookup_don(brand, subject):
            calls.append((brand, subject))
            return {"product_id": "DON-OP15-002"}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2, lookup_don_fn=fake_lookup_don
        )
        # title に "DON" 含むので lookup_don 起動 (title-only fallback)
        # = brand/subject = title (cache miss のため)、 C:PSA Brand/Subject 列値は **無視**
        assert k1 == "DON-OP15-002"
        assert len(calls) == 1
        # 撤回確認: C:PSA Brand 値 "OP15-ADVENTURE" は brand に渡されない (= cache miss で空)
        assert "ADVENTURE" not in calls[0][0]  # title 経由なので含まれず
        assert "ADVENTURE" not in calls[0][1]

    def test_yugioh_lookup_skipped_when_existing_regex_hits(self):
        """Phase 1l: 既存 Yu-Gi-Oh regex で title から取れる場合は lookup_yugioh 呼ばない."""
        row = {
            "*Title": "PSA 10 Yu-Gi-Oh! Blue-Eyes White Dragon LB-JP001",
            "C:Card Number": "LB-JP001",
            "C:PSA Brand": "YU-GI-OH! JAPANESE LB-01 LEGEND OF BLUE EYES",
            "C:PSA Subject": "BLUE-EYES WHITE DRAGON",
            "CDA:Certification Number - (ID: 27503)": "111",
        }
        calls = []

        def fake_lookup_yugioh(brand, card_number, subject):
            calls.append((brand, card_number, subject))
            return {"product_id": "89631139"}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row,
            extract_priority_key2,
            lookup_yugioh_fn=fake_lookup_yugioh,
        )
        # 既存 regex で `LB-JP001` 取れる → lookup_yugioh fallback skip
        assert k1 == "LB-JP001"
        assert len(calls) == 0

    def test_yugioh_lookup_not_triggered_without_cache_brand_subject(self):
        """Phase 1q: C:PSA Brand/Subject 列読込撤回 → cache miss なら brand/subject 空 → YGO lookup skip."""
        row = {
            "*Title": "PSA 10 Yu-Gi-Oh Konami Card",
            "C:Card Number": "",
            "C:PSA Brand": "YU-GI-OH! JAPANESE",
            "C:PSA Subject": "BLUE-EYES WHITE DRAGON",
            "CDA:Certification Number - (ID: 27503)": "no_cache",
        }
        calls = []

        def fake_lookup_yugioh(brand, card_number, subject):
            calls.append((brand, card_number, subject))
            return {"product_id": "89631139"}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row,
            extract_priority_key2,
            lookup_yugioh_fn=fake_lookup_yugioh,
        )
        # 撤回確認: C:PSA Brand/Subject 列読込しない、 cache miss で brand/subject 空 → YGO 呼出 skip
        assert len(calls) == 0
        assert k1 is None

    def test_yugioh_fallback_skipped_without_psa_columns(self):
        """C:PSA Brand / Subject 列無 + 既存 logic で取れない → lookup_yugioh 呼ばない."""
        row = {
            "*Title": "PSA 10 Yu-Gi-Oh Konami Card no psa columns",
            "C:Card Number": "",
        }
        calls = []

        def fake_lookup_yugioh(brand, card_number, subject):
            calls.append((brand, card_number, subject))
            return {"product_id": "X"}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2, lookup_yugioh_fn=fake_lookup_yugioh
        )
        # psa_brand/psa_subject 空 → YGO fallback 起動せず
        assert len(calls) == 0
        assert k1 is None

    def test_yugioh_fallback_skipped_when_not_ygo_marker(self):
        """title/brand に YGO marker 無 → lookup_yugioh 呼ばない."""
        row = {
            "*Title": "PSA 10 Pokemon Card Pikachu",
            "C:Card Number": "",
            "C:PSA Brand": "POKEMON JAPANESE",
            "C:PSA Subject": "PIKACHU",
        }
        calls = []

        def fake_lookup_yugioh(brand, card_number, subject):
            calls.append((brand, card_number, subject))
            return None

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2, lookup_yugioh_fn=fake_lookup_yugioh
        )
        # YGO marker 無 → lookup_yugioh 呼ばれない
        assert len(calls) == 0


class TestVariantMetaSSoT:
    """Phase 1n: catalog variant_meta 経由 KEY2 SSOT 化."""

    def test_variant_meta_used_when_catalog_hit(self):
        """catalog hit + valid variant_code → k2 が catalog 公式値で上書き."""
        row = {
            "*Title": "PSA 10 OP02-120 Uta Secret Alternate Art",
            "C:Card Number": "OP02-120",
            "C:PSA Subject": "UTA SECRET ALTERNATE ART",
        }

        def fake_alias(subject):
            # subject に 'SECRET' 含む → SAR
            return "SAR" if "SECRET" in subject.upper() else None

        def fake_meta(pid, variant_code, category):
            if variant_code == "SAR":
                return {"features": "Special Art Rare", "rarity_ebay": "Special"}
            return None

        def fake_category(pid):
            return "one_piece_tcg"

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row,
            extract_priority_key2,
            extract_variant_alias_fn=fake_alias,
            get_variant_meta_fn=fake_meta,
            get_category_fn=fake_category,
        )
        assert k1 == "OP02-120"
        # title parse は 'sec' (= Secret) を返すが、 catalog SSOT で 'SAR' に上書き
        assert k2 == "SAR"

    def test_variant_meta_fallback_to_title_parse_when_not_in_catalog(self):
        """catalog NULL → 既存 title parse 値 keep."""
        row = {
            "*Title": "PSA 10 OP02-120 Uta Secret Alternate Art",
            "C:Card Number": "OP02-120",
        }

        def fake_alias(subject):
            return None  # catalog 表記揺れ吸収できず

        def fake_meta(pid, variant_code, category):
            return None

        def fake_category(pid):
            return "one_piece_tcg"

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row,
            extract_priority_key2,
            extract_variant_alias_fn=fake_alias,
            get_variant_meta_fn=fake_meta,
            get_category_fn=fake_category,
        )
        assert k1 == "OP02-120"
        # title parse の "sec" が k2 のまま (= catalog hit せず fallback)
        assert k2 == "sec"

    def test_variant_meta_skipped_when_fns_not_provided(self):
        """関数引数 None → catalog 経路 skip、 既存 logic 維持."""
        row = {
            "*Title": "PSA 10 OP02-120 Uta Secret Alternate Art",
            "C:Card Number": "OP02-120",
        }
        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2,
            # extract_variant_alias_fn 等を渡さない
        )
        assert k1 == "OP02-120"
        assert k2 == "sec"  # title parse のまま


class TestPhase1oImageHashFallback:
    """Phase 1o (= 5/28): 画像 hash 最終 fallback."""

    def test_image_hash_fallback_when_variant_unknown(self):
        """既存 fallback で k2 取れず + 画像 URL あり + catalog variants + identify hit → k2 確定."""
        row = {
            "*Title": "PSA 10 OP06-022 Yamato",  # variant keyword 無
            "C:Card Number": "OP06-022",
            "PicURL": "http://example.com/img.jpg",
        }
        catalog_calls = []
        image_calls = []

        def fake_get_variants(pid, category):
            catalog_calls.append((pid, category))
            return {"AR": {"image_phash": "abc"}, "SAR": {"image_phash": "def"}}

        def fake_identify(image_url, variants, threshold=10):
            image_calls.append((image_url, sorted(variants.keys())))
            return "SAR"

        def fake_category(pid):
            return "one_piece_tcg"

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row,
            extract_priority_key2,
            get_category_fn=fake_category,
            get_catalog_variants_fn=fake_get_variants,
            identify_variant_by_image_fn=fake_identify,
        )
        assert k1 == "OP06-022"
        assert k2 == "SAR"
        assert len(catalog_calls) == 1
        assert len(image_calls) == 1

    def test_image_hash_skipped_when_k2_already_set(self):
        """既存 logic で k2 取得済 (= title parse) → 画像 hash skip (= ROI 最大化)."""
        row = {
            "*Title": "PSA 10 OP06-022 Yamato Alt Art",  # 'alt' title parse hit
            "C:Card Number": "OP06-022",
            "PicURL": "http://example.com/img.jpg",
        }
        image_calls = []

        def fake_identify(image_url, variants, threshold=10):
            image_calls.append(image_url)
            return "SAR"

        def fake_get_variants(pid, category):
            return {"AR": {"image_phash": "x"}}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row,
            extract_priority_key2,
            get_category_fn=lambda pid: "one_piece_tcg",
            get_catalog_variants_fn=fake_get_variants,
            identify_variant_by_image_fn=fake_identify,
        )
        assert k2 == "alt"  # title parse 値 keep
        assert len(image_calls) == 0  # skip 確認

    def test_image_hash_skipped_when_no_image_url(self):
        """*PicURL / PicURL 両方空 → 画像 hash skip."""
        row = {
            "*Title": "PSA 10 OP06-022 Yamato",
            "C:Card Number": "OP06-022",
            # 画像 URL 列無し
        }
        image_calls = []

        def fake_identify(image_url, variants, threshold=10):
            image_calls.append(image_url)
            return "SAR"

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row,
            extract_priority_key2,
            get_category_fn=lambda pid: "one_piece_tcg",
            get_catalog_variants_fn=lambda pid, cat: {"AR": {"image_phash": "x"}},
            identify_variant_by_image_fn=fake_identify,
        )
        assert k2 == ""
        assert len(image_calls) == 0

    def test_image_hash_skipped_when_catalog_variants_null(self):
        """catalog variants None → 画像 hash skip."""
        row = {
            "*Title": "PSA 10 OP06-022 Yamato",
            "C:Card Number": "OP06-022",
            "PicURL": "http://example.com/img.jpg",
        }
        image_calls = []

        def fake_identify(image_url, variants, threshold=10):
            image_calls.append(image_url)
            return "SAR"

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row,
            extract_priority_key2,
            get_category_fn=lambda pid: "one_piece_tcg",
            get_catalog_variants_fn=lambda pid, cat: None,  # variants 不在
            identify_variant_by_image_fn=fake_identify,
        )
        assert k2 == ""
        assert len(image_calls) == 0

    def test_image_hash_fail_closed_when_identify_returns_none(self):
        """identify_variant_by_image が None (= tie / 閾値超 / fetch fail) → k2 空のまま."""
        row = {
            "*Title": "PSA 10 OP06-022 Yamato",
            "C:Card Number": "OP06-022",
            "PicURL": "http://example.com/img.jpg",
        }

        def fake_identify(image_url, variants, threshold=10):
            return None  # fail-closed

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row,
            extract_priority_key2,
            get_category_fn=lambda pid: "one_piece_tcg",
            get_catalog_variants_fn=lambda pid, cat: {"AR": {"image_phash": "x"}},
            identify_variant_by_image_fn=fake_identify,
        )
        assert k1 == "OP06-022"
        assert k2 == ""  # fail-closed


class TestPhase1pInternalKeyColumns:
    """Phase 1p (= 5/28 C): INTERNAL:KEY1/KEY2 列 SSOT 単一決定経路."""

    def test_dedup_uses_cache_for_brand_subject_when_present(self, monkeypatch):
        """Phase 1q: cert → iMakeBayAPI cache hit → brand/subject 取得 → DON lookup 起動."""
        from dedupe import iMakeBayAPI_psa_io

        def fake_get_cached(cert):
            if cert == "156219827":
                return {
                    "Brand": "ONE PIECE JAPANESE OP15-ADVENTURE ON KAMI'S ISLAND",
                    "Subject": "DON!! CARD ALTERNATE ART GOLD",
                }
            return None

        monkeypatch.setattr(iMakeBayAPI_psa_io, "get_cached_psa", fake_get_cached)

        row = {
            "*Title": "PSA 10 DON Card",
            "C:Card Number": "",
            "CDA:Certification Number - (ID: 27503)": "156219827",
        }
        calls = []

        def fake_lookup_don(brand, subject):
            calls.append((brand, subject))
            return {"product_id": "DON-OP15-002"}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2, lookup_don_fn=fake_lookup_don
        )
        assert k1 == "DON-OP15-002"
        assert len(calls) == 1
        # cache 経由の brand/subject が渡る (= title 経由ではない)
        assert "OP15-ADVENTURE" in calls[0][0]
        assert "DON!! CARD ALTERNATE" in calls[0][1]

    def test_dedup_falls_back_to_title_when_cache_miss(self, monkeypatch):
        """Phase 1q: cache miss → brand/subject 空 → title-only fallback (= 既存通り)."""
        from dedupe import iMakeBayAPI_psa_io

        monkeypatch.setattr(
            iMakeBayAPI_psa_io, "get_cached_psa", lambda cert: None
        )

        row = {
            "*Title": "PSA 10 DON Alternate Art Card",
            "C:Card Number": "",
            "CDA:Certification Number - (ID: 27503)": "miss_cert",
        }
        calls = []

        def fake_lookup_don(brand, subject):
            calls.append((brand, subject))
            return {"product_id": "DON-X-001"}

        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2, lookup_don_fn=fake_lookup_don
        )
        # title に DON 含むので title-only fallback で呼出
        assert k1 == "DON-X-001"
        # cache miss なので brand=subject=title (= 既存 fallback)
        assert calls[0][0] == row["*Title"]

    def test_csv_internal_key_columns_no_longer_used(self):
        """Phase 1q (= 5/28 体系再設計): INTERNAL:KEY1/KEY2 列読込撤回確認.

        旧 logic では出品くん値そのまま採用していたが、 CSV にリスティング無関係列を
        持たない方針で撤回。 重複くんは既存 logic (= title parse) で再算出する。
        """
        row = {
            "*Title": "PSA 10 OP06-022 Yamato",
            "C:Card Number": "OP06-022",
            "INTERNAL:KEY1": "OP06-022_P_LF",  # 値あっても採用されない
            "INTERNAL:KEY2": "SAR",
        }
        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2,
        )
        # 撤回確認: INTERNAL:KEY1 値 "OP06-022_P_LF" は採用されず、 既存 logic で "OP06-022" を返す
        assert k1 == "OP06-022"
        assert k1 != "OP06-022_P_LF"

    def test_csv_internal_key1_empty_falls_through_to_existing_logic(self):
        """INTERNAL:KEY1 値空 → 既存 logic で再算出 (= 後方互換)."""
        row = {
            "*Title": "PSA 10 OP06-022 Yamato",
            "C:Card Number": "OP06-022",
            "INTERNAL:KEY1": "",
            "INTERNAL:KEY2": "",
        }
        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2,
        )
        assert k1 == "OP06-022"  # title 経由 既存 logic

    def test_csv_internal_key_column_absent_falls_through(self):
        """INTERNAL 列なし (= 古い CSV) → 既存 logic 経路、 後方互換."""
        row = {
            "*Title": "PSA 10 OP06-022 Yamato",
            "C:Card Number": "OP06-022",
        }
        cert, k1, t1, k2 = csv_write_keys.extract_cert_and_keys_from_csv_row(
            row, extract_priority_key2,
        )
        assert k1 == "OP06-022"


class TestBuildCertToRowIndex:
    def test_tcg_only(self):
        values = [
            ["URL", "itemID", "title", "...", "...", "...", "...", "...", "Title",
             "Desc", "x", "x", "x", "x", "x", "x", "x", "TCG"],   # row 1 header
            ["url1", "iid1", "t1", "", "", "", "", "", "149657853",
             "", "", "", "", "", "", "", "", "TCG"],              # row 2 TCG with cert
            ["url2", "iid2", "t2", "", "", "", "", "", "Cowes T-shirt",
             "", "", "", "", "", "", "", "", "Tシャツ"],          # row 3 非TCG
            ["url3", "iid3", "t3", "", "", "", "", "", "150213978",
             "", "", "", "", "", "", "", "", "TCG"],              # row 4 TCG with cert
            ["url4", "iid4", "t4", "", "", "", "", "", "",
             "", "", "", "", "", "", "", "", "TCG"],              # row 5 TCG cert 空
        ]
        cert_map = csv_write_keys.build_cert_to_row_index(
            values, category_col=18, cert_col=9, tcg_category_value="TCG"
        )
        assert cert_map == {"149657853": 2, "150213978": 4}

    def test_empty_values(self):
        assert csv_write_keys.build_cert_to_row_index([], 18, 9) == {}


def _make_mock_ws(values):
    ws = MagicMock()
    ws.get_all_values.return_value = values
    ws.batch_update = MagicMock()
    return ws


class TestWriteKeysToHigh:
    @pytest.fixture
    def mock_ws_values(self):
        # row 1 = header, row 2-4 = data, R=18, I=9, AI=35, AJ=36
        header = ["URL", "itemID", "title"] + [""] * 5 + ["Title", "Desc"] + [""] * 7 + ["TCG"] + [""] * 16 + ["KEY1", "KEY2"]
        # padding to col 36
        while len(header) < 36:
            header.append("")
        # row 2: TCG, cert=149657853, KEY1=item:m999 (URL), KEY2 空 → upgrade & KEY2 書込
        row2 = ["url1", "iid1", "Old Title"] + [""] * 5 + ["149657853", ""] + [""] * 7 + ["TCG"] + [""] * 16 + ["item:m999", ""]
        # row 3: 非TCG = skip 対象、 cert 形式の数字あるが対象外
        row3 = ["url2", "iid2", "Shirt"] + [""] * 5 + ["Cowes T-shirt", ""] + [""] * 7 + ["Tシャツ"] + [""] * 16 + ["item:m888", ""]
        # row 4: TCG, cert=150213978, KEY1 既に card_id 値あり → skip
        row4 = ["url3", "iid3", "card title"] + [""] * 5 + ["150213978", ""] + [""] * 7 + ["TCG"] + [""] * 16 + ["EB03-053", ""]
        # row 5: TCG, cert=新しい, KEY1 空 → 新規書込
        row5 = ["url4", "iid4", "new card"] + [""] * 5 + ["999999999", ""] + [""] * 7 + ["TCG"] + [""] * 16 + ["", ""]

        # rows がちょうど 36 col になるよう padding
        def _pad(r):
            while len(r) < 36:
                r.append("")
            return r[:36]

        return [_pad(header), _pad(row2), _pad(row3), _pad(row4), _pad(row5)]

    def test_full_flow(self, tmp_path, mock_ws_values):
        ws = _make_mock_ws(mock_ws_values)
        csv_path = tmp_path / "test.csv"
        _make_csv(
            csv_path,
            rows=[
                {
                    "*Title": "PSA 10 OP05-060 Luffy Alt Art",
                    "C:Card Number": "OP05-060",
                    "C:Features": "Alternative Art",
                    "C:Speciality": "",
                    "CDA:Certification Number - (ID: 27503)": "149657853",
                },
                {
                    "*Title": "PSA 10 EB03-053 Nami",
                    "C:Card Number": "EB03-053",
                    "C:Features": "",
                    "C:Speciality": "",
                    "CDA:Certification Number - (ID: 27503)": "150213978",
                },
                {
                    "*Title": "PSA 10 OP99-001 NewCard",
                    "C:Card Number": "OP99-001",
                    "C:Features": "",
                    "C:Speciality": "",
                    "CDA:Certification Number - (ID: 27503)": "999999999",
                },
                {
                    "*Title": "No cert row",
                    "C:Card Number": "OP12-100",
                    "C:Features": "",
                    "C:Speciality": "",
                    "CDA:Certification Number - (ID: 27503)": "",
                },
                {
                    "*Title": "Unmatched cert row",
                    "C:Card Number": "OP13-200",
                    "C:Features": "",
                    "C:Speciality": "",
                    "CDA:Certification Number - (ID: 27503)": "111111111",
                },
            ],
            fieldnames=CSV_FIELDS,
        )

        result = csv_write_keys.write_keys_to_high(
            ws=ws,
            csv_path=csv_path,
            priority_extractor2=extract_priority_key2,
            key1_col=35,
            key2_col=36,
            cert_col=9,
            category_col=18,
            tcg_category_value="TCG",
            dry_run=True,
        )

        assert result["csv_rows"] == 5
        assert result["csv_with_cert"] == 4  # 1 件 cert 空
        assert result["high_tcg_rows"] == 3  # row 2 / 4 / 5 (= 3 件、 row 3 は 非TCG)
        assert result["matched"] == 3  # row 2 / 4 / 5
        assert result["skipped_no_cert"] == 1
        assert result["skipped_cert_unmatched"] == 1
        # row 2: URL KEY → card_id upgrade + variant 書込 = +1 +1
        # row 4: 既存 card_id KEY1 → skip。 KEY2 空 + variant 空 → no-op
        # row 5: KEY1 空 → 新規書込 +1。 KEY2 空 + variant 空 → no-op
        assert result["written_key1"] == 2  # row 2 upgrade + row 5 新規
        assert result["written_key2"] == 1  # row 2 alt
        assert result["skipped_existing_key1"] == 1  # row 4
        # dry_run=True なので batch_update 呼ばれない
        ws.batch_update.assert_not_called()

    def test_dry_run_no_write(self, tmp_path, mock_ws_values):
        ws = _make_mock_ws(mock_ws_values)
        csv_path = tmp_path / "test.csv"
        _make_csv(csv_path, rows=[], fieldnames=CSV_FIELDS)
        result = csv_write_keys.write_keys_to_high(
            ws=ws,
            csv_path=csv_path,
            priority_extractor2=extract_priority_key2,
            key1_col=35,
            key2_col=36,
            cert_col=9,
            category_col=18,
            dry_run=True,
        )
        assert result["csv_rows"] == 0
        ws.batch_update.assert_not_called()

    def test_missing_csv_raises(self, tmp_path, mock_ws_values):
        ws = _make_mock_ws(mock_ws_values)
        with pytest.raises(FileNotFoundError):
            csv_write_keys.write_keys_to_high(
                ws=ws,
                csv_path=tmp_path / "nope.csv",
                priority_extractor2=extract_priority_key2,
                key1_col=35,
                key2_col=36,
                cert_col=9,
                category_col=18,
            )
