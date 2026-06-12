"""G-shock resolver_io 配線 test (= 2026-06-12 修正 B/C).

依頼書: 2026-06-12_gshock_resolver_io_BUILD_greenlight.md
依頼根拠: G-shock CSV 全件 unresolved → 物理除外の真因 = dispatch / signal 配線漏れ.

検証対象:
1. G-shock title → extract_gshock_model で型番抽出 → category="gshock" + signals["model"]
2. TCG title は従来通り (= G-shock 誤検出なし)
3. 型番抽出失敗 title → category="" + signals["model"]="" (= fail-closed)
4. resolve_csv_row / resolve_sheet_row 両経路で同等動作
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dedupe import resolver_io

pytestmark = pytest.mark.offline


# ============================================================================
# C: _guess_category G-shock 検出
# ============================================================================

class TestGuessCategoryGshock:
    def test_dw_5600rl_jf_returns_gshock(self):
        """DW-5600RL-1JF → gshock."""
        cat = resolver_io._guess_category(title="CASIO G-Shock DW-5600RL-1JF Mens Watch")
        assert cat == "gshock"

    def test_mtg_b4000_1a_returns_gshock(self):
        """MTG-B4000-1A → gshock."""
        cat = resolver_io._guess_category(title="CASIO G-Shock MTG-B4000-1A Watch")
        assert cat == "gshock"

    def test_ga_v01ske_6a_returns_gshock(self):
        """GA-V01SKE-6A → gshock."""
        cat = resolver_io._guess_category(title="CASIO G-Shock GA-V01SKE-6A Transparent Pack")
        assert cat == "gshock"

    def test_tcg_one_piece_not_gshock(self):
        """TCG (= ONE PIECE) title → one_piece_tcg、 G-shock 誤検出なし."""
        cat = resolver_io._guess_category(
            title="ONE PIECE OP10-049 Sabo Promo",
            brand="ONE PIECE JAPANESE PROMOS",
        )
        assert cat == "one_piece_tcg"

    def test_tcg_pokemon_not_gshock(self):
        """Pokemon title → pokemon_tcg、 G-shock 誤検出なし (= prefix 衝突しない設計)."""
        cat = resolver_io._guess_category(
            title="PSA10 Pokemon #076/096 Copperajah Vmax",
            brand="POKEMON JAPANESE SWORD & SHIELD",
        )
        assert cat == "pokemon_tcg"

    def test_no_gshock_token_returns_empty(self):
        """G-shock 型番もない title → "" (fail-closed)."""
        cat = resolver_io._guess_category(title="random watch with no model number")
        assert cat == ""

    def test_empty_title_returns_empty(self):
        """空 title → "" (fail-closed)."""
        cat = resolver_io._guess_category(title="")
        assert cat == ""


# ============================================================================
# B: resolve_csv_row signals["model"] セット
# ============================================================================

class TestResolveCsvRowGshockSignals:
    def test_gshock_csv_row_sets_model_and_category(self):
        """G-shock CSV row → context.signals["model"] + category="gshock" で resolve 呼出."""
        captured = {}

        def fake_resolve(ctx):
            captured.update(ctx)
            return "DW-5600RL-1JF"

        row = {
            "*Title": "CASIO G-Shock DW-5600RL-1JF Mens Digital Watch Black Resin",
            "C:Card Number": "",
            "*PicURL": "",
            "CDA:Certification Number - (ID: 27503)": "",
        }
        with patch("dedupe.resolver_io.resolve", side_effect=fake_resolve):
            result = resolver_io.resolve_csv_row(row, purpose="dedup")

        assert result == "DW-5600RL-1JF"
        assert captured["category"] == "gshock"
        assert captured["signals"]["model"] == "DW-5600RL-1JF"

    def test_tcg_csv_row_model_empty(self):
        """TCG CSV row (cert あり) → category=TCG、 signals["model"]="" (= G-shock 型番なし)."""
        captured = {}

        def fake_resolve(ctx):
            captured.update(ctx)
            return "OP10-049_p1"

        row = {
            "*Title": "PSA 10 One Piece Premium Card Collection - BS Vol.4 OP10-049 Sabo",
            "C:Card Number": "049",
            "CDA:Certification Number - (ID: 27503)": "146614864",
        }
        # PSA cache mock (= Sabo)
        with patch(
            "dedupe.iMakeBayAPI_psa_io.get_cached_psa",
            return_value={
                "Brand": "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-",
                "Subject": "SABO",
                "CardNumber": "049",
            },
        ), patch("dedupe.resolver_io.resolve", side_effect=fake_resolve):
            result = resolver_io.resolve_csv_row(row, purpose="dedup")

        assert result == "OP10-049_p1"
        assert captured["category"] == "one_piece_tcg"
        assert captured["signals"]["model"] == ""  # TCG title から G-shock 型番抽出不能

    def test_unresolvable_csv_row_model_empty(self):
        """型番抽出不能 title → signals["model"]="" + category="" (= fail-closed)."""
        captured = {}

        def fake_resolve(ctx):
            captured.update(ctx)
            return ""

        row = {"*Title": "Random listing with no identifiable model"}
        with patch("dedupe.resolver_io.resolve", side_effect=fake_resolve):
            result = resolver_io.resolve_csv_row(row, purpose="dedup")

        assert result == ""
        assert captured["category"] == ""
        assert captured["signals"]["model"] == ""


# ============================================================================
# B: resolve_sheet_row signals["model"] セット (= HIGH/LOW 既存 row 評価用)
# ============================================================================

class TestResolveSheetRowGshockSignals:
    def test_gshock_sheet_row_sets_model_and_category(self):
        """G-shock スプシ row → context.signals["model"] + category="gshock"."""
        captured = {}

        def fake_resolve(ctx):
            captured.update(ctx)
            return "GA-2100-1A1JF"

        with patch("dedupe.resolver_io.resolve", side_effect=fake_resolve):
            result = resolver_io.resolve_sheet_row(
                title="CASIO G-Shock GA-2100-1A1JF Casioak",
                purpose="dedup",
            )

        assert result == "GA-2100-1A1JF"
        assert captured["category"] == "gshock"
        assert captured["signals"]["model"] == "GA-2100-1A1JF"

    def test_tcg_sheet_row_model_empty(self):
        """TCG スプシ row → signals["model"]=""、 G-shock 誤検出なし."""
        captured = {}

        def fake_resolve(ctx):
            captured.update(ctx)
            return ""

        with patch("dedupe.resolver_io.resolve", side_effect=fake_resolve):
            resolver_io.resolve_sheet_row(
                title="PSA10 ナミ OP01-016 プレミアム",
                purpose="dedup",
            )

        # one_piece_tcg category だが G-shock 型番なし
        assert captured["signals"]["model"] == ""


# ============================================================================
# 統合: 6/12 CSV 10 件相当 シナリオ (= dry-run verify 同等)
# ============================================================================

class TestGshockCsvScenarioIntegration:
    """6/12 実機 CSV の 10 件 (= gshock_upload_20260612_125722.csv) に該当する title で
    型番抽出 + category=gshock になることを統合 verify."""

    GSHOCK_CSV_TITLES = [
        ("CASIO G-Shock DW-5600RL-1JF Mens Digital Watch Black Resin", "DW-5600RL-1JF"),
        ("CASIO G-Shock MTG-B4000-1A Mens Watch Black Sport 200M Water", "MTG-B4000-1A"),
        ("CASIO G-Shock DW-H5600-2 Mens Watch Blue Sport 200M Water Re", "DW-H5600-2"),
        ("CASIO G-Shock GM-2100M-1A Metal Covered Mens Analog & Digital", "GM-2100M-1A"),
        ("CASIO G-Shock GA-B010-1A1 Mens Watch Black Sport 200M Water", "GA-B010-1A1"),
        ("CASIO G-Shock GWG-B1000MG-1A9 Mens Watch", "GWG-B1000MG-1A9"),
        ("CASIO G-Shock GG-1000-1A3JF Mens Watch", "GG-1000-1A3JF"),
        ("CASIO G-Shock MTG-B4000BD-1A Mens Watch", "MTG-B4000BD-1A"),
        ("CASIO G-Shock GA-V01SKE-6A Transparent Pack", "GA-V01SKE-6A"),
        ("CASIO G-Shock GMD-S6900Y-9JF Mens Watch", "GMD-S6900Y-9JF"),
    ]

    @pytest.mark.parametrize("title,expected_model", GSHOCK_CSV_TITLES)
    def test_all_gshock_titles_resolve_via_signals(self, title, expected_model):
        """全 10 件 title で category=gshock + signals["model"] が正しく抽出される."""
        captured = {}

        def fake_resolve(ctx):
            captured.update(ctx)
            return ctx["signals"].get("model") or ""

        row = {"*Title": title}
        with patch("dedupe.resolver_io.resolve", side_effect=fake_resolve):
            result = resolver_io.resolve_csv_row(row, purpose="listing")

        # extract_gshock_model が hit するなら category=gshock + model 保持
        assert captured["category"] == "gshock", f"category not gshock for {title}"
        # 型番抽出は upper 正規化される (extractors/gshock.py 仕様)
        assert captured["signals"]["model"].upper() == expected_model.upper(), (
            f"model mismatch for {title}: got {captured['signals']['model']!r}"
        )
