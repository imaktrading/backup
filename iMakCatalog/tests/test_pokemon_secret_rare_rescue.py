"""_pokemon_secret_rare_rescue の単体テスト (network 非依存).

窓口GO: 2026-08-10 card_images_leader_back_and_pokemon_missing_response.md §Q2 案C.
match_target / parse_target / known_cardid_range / upsert_image を network 抜きで検証.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import pokemon_secret_rare_rescue as R  # noqa: E402


class TestParseTarget:
    def test_simple(self):
        assert R.parse_target("SM11-112") == ("SM11", "112")

    def test_with_dash_in_set(self):
        # 現状の pokemon product_id には SM- 型 promo が存在するが、その場合 rsplit で
        # ハイフン最後で分割される仕様なので promo は例外的に扱われる (実運用 target は SMxx-nnn)
        assert R.parse_target("SV-P-291") == ("SV-P", "291")

    def test_missing_dash(self):
        assert R.parse_target("SM11") is None

    def test_empty(self):
        assert R.parse_target("") is None
        assert R.parse_target("-abc") is None
        assert R.parse_target("abc-") is None


class TestMatchTarget:
    def test_exact_match(self):
        detail = {"set_code": "SM11", "card_number_text": "112/094"}
        assert R.match_target(detail, "SM11", "112") is True

    def test_leading_zero_matches(self):
        detail = {"set_code": "SM9a", "card_number_text": "067/055"}
        assert R.match_target(detail, "SM9a", "067") is True
        # 0-strip 側でも一致
        assert R.match_target(detail, "SM9a", "67") is True

    def test_set_code_mismatch_rejected(self):
        # SM11 と SM11a は別 set → 混同禁止 (fail-closed)
        detail = {"set_code": "SM11a", "card_number_text": "112/094"}
        assert R.match_target(detail, "SM11", "112") is False

    def test_card_number_mismatch_rejected(self):
        detail = {"set_code": "SM11", "card_number_text": "094/094"}
        assert R.match_target(detail, "SM11", "112") is False

    def test_missing_fields(self):
        assert R.match_target({}, "SM11", "112") is False
        assert R.match_target({"set_code": "SM11"}, "SM11", "112") is False
        assert R.match_target({"card_number_text": "112/094"}, "SM11", "112") is False

    def test_promo_form_rejected_for_regular_target(self):
        # promo 番号 "047/S-P" は printed = "047" だが set_code は SMP 等になる
        detail = {"set_code": "SMP", "card_number_text": "047/S-P"}
        assert R.match_target(detail, "SM11", "047") is False


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """テスト専用の空 DB を作って api._DB_PATH を差し替える."""
    db_path = tmp_path / "test_products.sqlite"
    schema_path = ROOT / "db" / "schema.sql"
    conn = sqlite3.connect(str(db_path))
    with open(schema_path, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    monkeypatch.setattr(api, "_DB_PATH", db_path)
    yield db_path


class TestKnownCardIDRange:
    def test_range_derived_from_source_url(self, isolated_db):
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        # 3 records with source_url
        cur.executescript("""
        INSERT INTO products (category, product_id, name, specs, source, source_url,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-001', 'a', '{}', 'pokemon_card_jp',
                'https://www.pokemon-card.com/card-search/details.php/card/36748',
                '2026-08-10', '2026-08-10');
        INSERT INTO products (category, product_id, name, specs, source, source_url,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-050', 'b', '{}', 'pokemon_card_jp',
                'https://www.pokemon-card.com/card-search/details.php/card/36850',
                '2026-08-10', '2026-08-10');
        INSERT INTO products (category, product_id, name, specs, source, source_url,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-106', 'c', '{}', 'pokemon_card_jp',
                'https://www.pokemon-card.com/card-search/details.php/card/36986',
                '2026-08-10', '2026-08-10');
        """)
        conn.commit()
        assert R.known_cardid_range(cur, "SM11") == (36748, 36986)
        conn.close()

    def test_no_pokemon_card_jp_source_returns_none(self, isolated_db):
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        # bulbapedia のみ (pokemon_card_jp source なし)
        cur.execute("""
        INSERT INTO products (category, product_id, name, specs, source, source_url,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-112', 'a', '{}', 'bulbapedia_confirmed',
                'https://bulbapedia.bulbagarden.net/wiki/foo',
                '2026-08-10', '2026-08-10');
        """)
        conn.commit()
        assert R.known_cardid_range(cur, "SM11") is None
        conn.close()

    def test_unknown_set_returns_none(self, isolated_db):
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        assert R.known_cardid_range(cur, "NONE") is None
        conn.close()


class TestUpsertImage:
    def test_upsert_writes_image_to_existing_record(self, isolated_db):
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO products (category, product_id, name, specs, source, images,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-112', 'a', '{}', 'bulbapedia_confirmed', '[]',
                '2026-08-10', '2026-08-10');
        """)
        conn.commit()
        img = "https://www.pokemon-card.com/assets/images/card_images/large/SM11/036999_P_TEST.jpg"
        ok = R.upsert_image(cur, conn, "SM11-112", img, dry_run=False)
        assert ok is True
        row = cur.execute(
            "SELECT images FROM products WHERE product_id='SM11-112'"
        ).fetchone()
        assert json.loads(row[0]) == [img]
        conn.close()

    def test_upsert_dry_run_does_not_write(self, isolated_db):
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO products (category, product_id, name, specs, source, images,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-112', 'a', '{}', 'bulbapedia_confirmed', '[]',
                '2026-08-10', '2026-08-10');
        """)
        conn.commit()
        img = "https://example.com/x.jpg"
        ok = R.upsert_image(cur, conn, "SM11-112", img, dry_run=True)
        assert ok is True
        row = cur.execute(
            "SELECT images FROM products WHERE product_id='SM11-112'"
        ).fetchone()
        # dry-run: 変更されない
        assert row[0] == "[]"
        conn.close()

    def test_upsert_missing_target_returns_false(self, isolated_db):
        # fail-closed: 対象 record が居ない場合は新規作成しない
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        ok = R.upsert_image(cur, conn, "NOT-EXISTS", "https://example.com/x.jpg",
                             dry_run=False)
        assert ok is False
        # DB に何も入っていない
        count = cur.execute(
            "SELECT count(*) FROM products WHERE product_id='NOT-EXISTS'"
        ).fetchone()[0]
        assert count == 0
        conn.close()

    def test_upsert_idempotent_when_image_already_present(self, isolated_db):
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        img = "https://example.com/x.jpg"
        cur.execute("""
        INSERT INTO products (category, product_id, name, specs, source, images,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-112', 'a', '{}', 'bulbapedia_confirmed', ?,
                '2026-08-10', '2026-08-10');
        """, (json.dumps([img], ensure_ascii=False),))
        conn.commit()
        ok = R.upsert_image(cur, conn, "SM11-112", img, dry_run=False)
        assert ok is True  # 既に登録済 → no-op で True 返却
        conn.close()


class TestRescueFlow:
    """rescue() の全体フローを network mock で検証."""

    def test_rescue_finds_and_upserts(self, isolated_db, monkeypatch):
        # DB に target を用意 (source_url 付き既知 range + images 空 の target)
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        cur.executescript("""
        INSERT INTO products (category, product_id, name, specs, source, source_url,
                              images, created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-001', 'a', '{}', 'pokemon_card_jp',
                'https://www.pokemon-card.com/card-search/details.php/card/36748',
                '["https://x/1.jpg"]', '2026-08-10', '2026-08-10');
        INSERT INTO products (category, product_id, name, specs, source, source_url,
                              images, created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-106', 'c', '{}', 'pokemon_card_jp',
                'https://www.pokemon-card.com/card-search/details.php/card/36986',
                '["https://x/2.jpg"]', '2026-08-10', '2026-08-10');
        INSERT INTO products (category, product_id, name, specs, source, images,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-112', 'HR', '{}', 'bulbapedia_confirmed', '[]',
                '2026-08-10', '2026-08-10');
        """)
        conn.commit()
        conn.close()

        # get_detail を mock: cardID=36990 で target 一致するように
        def fake_get_detail(cid):
            if int(cid) == 36990:
                return {
                    "set_code": "SM11",
                    "card_number_text": "112/094",
                    "name": "カイリューGX",
                    "image_url": "https://www.pokemon-card.com/large/SM11/036990.jpg",
                }
            # 他 cardID は SMP 等の別セット (mismatch)
            return {"set_code": "SMP", "card_number_text": "371/SM-P"}
        monkeypatch.setattr(R.pt, "get_detail", fake_get_detail)

        result = R.rescue(["SM11-112"], window=100, dry_run=False, verbose=False)
        assert "SM11-112" in result["rescued"]

        # DB に image_url が入ったことを確認
        conn = sqlite3.connect(str(isolated_db))
        row = conn.execute(
            "SELECT images FROM products WHERE product_id='SM11-112'"
        ).fetchone()
        conn.close()
        assert json.loads(row[0]) == [
            "https://www.pokemon-card.com/large/SM11/036990.jpg"
        ]

    def test_rescue_reports_not_found(self, isolated_db, monkeypatch):
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        cur.executescript("""
        INSERT INTO products (category, product_id, name, specs, source, source_url,
                              images, created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-001', 'a', '{}', 'pokemon_card_jp',
                'https://www.pokemon-card.com/card-search/details.php/card/36748',
                '["https://x/1.jpg"]', '2026-08-10', '2026-08-10');
        INSERT INTO products (category, product_id, name, specs, source, images,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-112', 'HR', '{}', 'bulbapedia_confirmed', '[]',
                '2026-08-10', '2026-08-10');
        """)
        conn.commit()
        conn.close()

        # get_detail 全 cardID で mismatch (対象 range 内どこにも SM11-112 が居ない)
        def fake_get_detail(cid):
            return {"set_code": "SMP", "card_number_text": "999/SM-P"}
        monkeypatch.setattr(R.pt, "get_detail", fake_get_detail)

        result = R.rescue(["SM11-112"], window=30, dry_run=False, verbose=False)
        assert "SM11-112" in result["not_found"]

    def test_rescue_skips_target_with_existing_images(self, isolated_db, monkeypatch):
        conn = sqlite3.connect(str(isolated_db))
        cur = conn.cursor()
        cur.executescript("""
        INSERT INTO products (category, product_id, name, specs, source, images,
                              created_at, updated_at)
        VALUES ('pokemon_tcg', 'SM11-050', 'b', '{}', 'pokemon_card_jp',
                '["https://x/already.jpg"]', '2026-08-10', '2026-08-10');
        """)
        conn.commit()
        conn.close()
        # network shouldn't be called
        call_count = {"n": 0}
        def fake_get_detail(cid):
            call_count["n"] += 1
            return None
        monkeypatch.setattr(R.pt, "get_detail", fake_get_detail)
        result = R.rescue(["SM11-050"], window=50, dry_run=False, verbose=False)
        assert "SM11-050" in result["skipped"]
        assert call_count["n"] == 0  # ネットワーク呼ばれない

    def test_rescue_skips_target_missing_from_db(self, isolated_db, monkeypatch):
        # DB に record が無い target → fail-closed で skip (勝手に upsert しない)
        def fake_get_detail(cid):
            return None
        monkeypatch.setattr(R.pt, "get_detail", fake_get_detail)
        result = R.rescue(["NOT-INDB-999"], window=50, dry_run=False, verbose=False)
        assert "NOT-INDB-999" in result["skipped"]
