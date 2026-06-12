"""catalog_io unit tests — fixture sqlite db で network/外部 dep 不要."""

import sqlite3
from pathlib import Path

import pytest

from dedupe import catalog_io

pytestmark = pytest.mark.offline


@pytest.fixture
def fixture_db(tmp_path):
    """Mini catalog DB を構築 (= products + ebay_filter_map)."""
    db = tmp_path / "catalog.sqlite"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE products (id INTEGER PRIMARY KEY, category TEXT, product_id TEXT)"
    )
    cur.execute(
        "CREATE TABLE ebay_filter_map "
        "(id INTEGER PRIMARY KEY, category TEXT, field TEXT, "
        "source_value TEXT, ebay_value TEXT)"
    )
    products = [
        (1, "one_piece_tcg", "OP06-022"),
        (2, "one_piece_tcg", "OP01-016"),
        (3, "gundam_tcg", "GD02-070"),
        (4, "gundam_tcg", "GD02-001"),
        (5, "pokemon_tcg", "S6A-001"),
        (6, "one_piece_tcg", "OP06-022_P"),  # variant suffix
        (7, "one_piece_tcg", ""),  # 空 product_id (= 除外想定)
        (8, "one_piece_tcg", None),  # null
        # Phase 1i v3: Pokemon Promo 公式形 (= Catalog SSOT で `001/SM-P` 形式)
        (9, "pokemon_tcg", "001/SM-P"),
        (10, "pokemon_tcg", "002/M-P"),
    ]
    cur.executemany("INSERT INTO products VALUES (?, ?, ?)", products)
    filter_rows = [
        (1, "one_piece_tcg", "set_code", "OP-06", "Wings of the Captain"),
        (2, "one_piece_tcg", "set_code", "OP-01", "Romance Dawn"),
        (3, "gundam_tcg", "set_code", "GD02", "Wings of Advance"),
        (4, "pokemon_tcg", "set_code", "S6a", "Eevee Heroes"),
        (5, "one_piece_tcg", "rarity", "SR", "Super Rare"),  # field != set_code → 除外
    ]
    cur.executemany(
        "INSERT INTO ebay_filter_map VALUES (?, ?, ?, ?, ?)", filter_rows
    )
    con.commit()
    con.close()
    return db


class TestOpenCatalog:
    def test_open_existing(self, fixture_db):
        con = catalog_io.open_catalog_readonly(fixture_db)
        assert isinstance(con, sqlite3.Connection)
        con.close()

    def test_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            catalog_io.open_catalog_readonly(tmp_path / "nope.sqlite")

    def test_readonly_write_fails(self, fixture_db):
        con = catalog_io.open_catalog_readonly(fixture_db)
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO products VALUES (99, 'x', 'XX-001')")
        con.close()


class TestLoadSetNameMap:
    def test_includes_only_set_code_field(self, fixture_db):
        con = catalog_io.open_catalog_readonly(fixture_db)
        m = catalog_io.load_set_name_map(con)
        con.close()
        assert m["Wings of the Captain"] == ("one_piece_tcg", "OP-06")
        assert m["Romance Dawn"] == ("one_piece_tcg", "OP-01")
        assert m["Wings of Advance"] == ("gundam_tcg", "GD02")
        assert m["Eevee Heroes"] == ("pokemon_tcg", "S6a")
        assert "Super Rare" not in m  # field='rarity' は除外


class TestLoadValidProductIds:
    def test_uppercases_and_excludes_empty(self, fixture_db):
        con = catalog_io.open_catalog_readonly(fixture_db)
        pids = catalog_io.load_valid_product_ids(con)
        con.close()
        assert "OP06-022" in pids
        assert "OP01-016" in pids
        assert "GD02-070" in pids
        assert "S6A-001" in pids
        assert "OP06-022_P" in pids
        assert "" not in pids


class TestReconstructCardId:
    @pytest.fixture
    def loaded(self, fixture_db):
        con = catalog_io.open_catalog_readonly(fixture_db)
        sm = catalog_io.load_set_name_map(con)
        pids = catalog_io.load_valid_product_ids(con)
        con.close()
        return sm, pids

    def test_full_form_verified(self, loaded):
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("OP06-022", "Wings of the Captain", sm, pids)
        assert cid == "OP06-022"
        assert "verified" in reason

    def test_full_form_unregistered(self, loaded):
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("ZZ99-999", "Unknown", sm, pids)
        assert cid == "ZZ99-999"
        assert "未登録" in reason

    def test_serial_plus_set_reconstructs(self, loaded):
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("022", "Wings of the Captain", sm, pids)
        # OP-06 → prefix=OP06、 zfill(3) → OP06-022
        assert cid == "OP06-022"
        assert "連番+Set" in reason

    def test_serial_plus_set_gundam(self, loaded):
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("070", "Wings of Advance", sm, pids)
        assert cid == "GD02-070"

    def test_serial_set_not_in_map(self, loaded):
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("042", "Goddess of Victory: NIKKE", sm, pids)
        assert cid is None
        assert "Set 未登録" in reason

    def test_serial_set_in_map_but_card_not_in_catalog(self, loaded):
        """Set 名 map あり、 prefix 取れる、 だが具体的 product_id は catalog 未登録."""
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("999", "Wings of the Captain", sm, pids)
        # candidate = OP06-999 → catalog 未登録 だが prefix だけ採用
        assert cid == "OP06-999"
        assert "未登録" in reason

    def test_no_card_number(self, loaded):
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("", "Wings of the Captain", sm, pids)
        assert cid is None

    def test_unknown_format(self, loaded):
        """`231/193` は Phase 1k v2 で 分子採用 → 連番経路 → Set 未登録なら None."""
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("231/193", "Some Set", sm, pids)
        assert cid is None
        # 5/27 以降: `Set 未登録` reason (= 数字/数字 を分子採用後、 Set hit なし)
        assert "Set 未登録" in reason or "format 不明" in reason

    def test_slash_form_verified(self, loaded):
        """Phase 1i v3: 公式 slash 形 `001/SM-P` を verify (= 正規化なし、 そのまま catalog で照合)."""
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("001/SM-P", "Sm Promo", sm, pids)
        assert cid == "001/SM-P"
        assert "公式 slash 形 verified" in reason

    def test_slash_form_uppercase_normalized(self, loaded):
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("002/m-p", "Japanese Promo", sm, pids)
        assert cid == "002/M-P"
        assert "公式 slash 形 verified" in reason

    def test_slash_form_unregistered(self, loaded):
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id("999/ZZ-P", "Unknown Promo", sm, pids)
        assert cid == "999/ZZ-P"
        assert "公式 slash 形 未登録" in reason

    def test_pokemon_official_num_over_num_format(self, loaded):
        """Phase 1k v2: `022/100` → 分子 `022` 採用 → Set 経由 reconstruct.

        出品くん 5/27 修正で Pokemon が公式 `番号/総数` 形式で書込開始。
        既存連番のみ logic に流すため preprocessing で `/` 削除。
        """
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id(
            "022/100", "Wings of the Captain", sm, pids
        )
        # fixture では Wings of the Captain → OP-06、 catalog products に OP06-022 登録あり
        assert cid == "OP06-022"
        assert "連番+Set verified" in reason

    def test_num_over_num_legacy_only_number_still_works(self, loaded):
        """後方互換: 連番のみ `022` も同じ Set で reconstruct (= 既存 cycle CSV)."""
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id(
            "022", "Wings of the Captain", sm, pids
        )
        assert cid == "OP06-022"
        assert "連番+Set verified" in reason

    def test_num_over_num_does_not_break_slash_form(self, loaded):
        """regression: `001/SM-P` 公式 slash 形 (連番/prefix) は touch されず既存 path."""
        sm, pids = loaded
        cid, reason = catalog_io.reconstruct_card_id(
            "001/SM-P", "Sm Promo", sm, pids
        )
        assert cid == "001/SM-P"
        assert "公式 slash 形 verified" in reason


class TestFindProductIdInText:
    """Phase 1k: catalog token verify (= 全 category 統合 fallback)."""

    @pytest.fixture
    def valid_pids(self):
        return frozenset({
            "OP08-106",
            "SV1V-086",
            "SV9-102",
            "S6A-001",
            "GD02-070",
            "DW-5600-1JF",
            "E420005-000",
            "FB02-049_FB08",
        })

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("PSA 10 Pokemon SV1V-086 Drowzee Japanese", "SV1V-086"),
            ("PSA 10 SV9-102 Articuno Wild Force", "SV9-102"),
            ("One Piece Card Game OP08-106 Nami Alt Art", "OP08-106"),
            ("Casio G-Shock DW-5600-1JF Black", "DW-5600-1JF"),
            ("Uniqlo UT E420005-000 Anime Tshirt", "E420005-000"),
            ("Gundam Card GD02-070 Char", "GD02-070"),
            ("Dragon Ball SCG FB02-049_FB08 reprint", "FB02-049_FB08"),
        ],
    )
    def test_hit(self, text, expected, valid_pids):
        hit = catalog_io.find_product_id_in_text(text, valid_pids)
        assert hit is not None
        assert hit[0] == expected

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "no tokens here",
            "PSA 10 Random title no id",
            "OP99-999 not in catalog",  # 形式 OK だが catalog 未登録 → None
            "12345678",  # 数字のみ (= Yu-Gi-Oh 想定 = token regex 区切り無で hit せず)
        ],
    )
    def test_miss(self, text, valid_pids):
        assert catalog_io.find_product_id_in_text(text, valid_pids) is None

    def test_longest_token_wins(self, valid_pids):
        """部分一致と完全一致が両方 valid_pids にある場合、 長い方優先."""
        pids = frozenset({"OP08", "OP08-106"})
        hit = catalog_io.find_product_id_in_text("test OP08-106 card", pids)
        assert hit[0] == "OP08-106"

    def test_empty_pids(self):
        assert catalog_io.find_product_id_in_text("OP08-106", frozenset()) is None
