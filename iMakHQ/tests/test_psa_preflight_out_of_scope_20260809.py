# -*- coding: utf-8 -*-
"""psa_preflight — catalog が構造的に持たないものを **入口で** 落とす (2026-08-09).

実害:
    SDBH (スーパードラゴンボールヒーローズ) と 日本語でない Pokemon が
    GAP (= catalog 未収録) に混ざり、毎回 catalog へ「追加して」と依頼していた。
    catalog は毎回「対象外です」と答えるだけ。この往復が
    「3ヶ月で catalog へ 921本」の発生源のひとつ。

    2026-08-09 の `psa_preflight_report` では 9件中 **7件が対象外**で、
    うち 1件は catalog が「PSA raw Brand が無いと弁別できない」と質問で止めていた
    (cert 158452559 = `SUPER DRAGON BALL HEROES METEOR MISSION 2`)。

なぜ cert の台帳ではなく brand の規則で落とすか:
    台帳 (`out_of_scope.json`) は 1件ずつ人が足す。**同じ判断を毎回やることになる**。
    brand 文字列は PSA が付けた canonical な値なので、規則にすれば以後ゼロ工数。

守りたい性質:
  1. SDBH は落ちる / Fusion World は **落ちない** (誤爆したら出品機会を殺す)
  2. 日本語でない Pokemon は落ちる / 日本語 Pokemon は落ちない
  3. One Piece / Dragon Ball の英語版は **落とさない** (catalog が en を持っている)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import psa_preflight as pf  # noqa: E402


class TestSDBH:
    """実 PSA brand (psa_cache 924件から採取) で固定する."""

    FIRES = [
        "SUPER DRAGON BALL HEROES METEOR MISSION 2",
        "SUPER DRAGON BALL HEROES ULTRA GOD MISSION 5",
        "SUPER DRAGON BALL HEROES BIG BANG MISSION 12",
        "DRAGON BALL HEROES GALAXY MISSION 10",
        "DRAGON BALL HEROES GOD MISSION 1",
        "DRAGON BALL HEROES 2",
    ]
    # ★Fusion World。1件でも落ちたら出品できるカードを捨てることになる
    KEEPS = [
        "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE ENERGY MARKER PACK 0",
        "DRAGON BALL SUPER FUSION WORLD JAPANESE MANGA BOOSTER 02",
        "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE BLAZING AURA",
        "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE",
    ]

    def test_sdbh_is_out_of_scope(self):
        for b in self.FIRES:
            assert pf.out_of_scope_by_brand(b), f"SDBH を落とせていない: {b}"

    def test_fusion_world_is_kept(self):
        for b in self.KEEPS:
            assert pf.out_of_scope_by_brand(b) is None, f"Fusion World を誤って落とした: {b}"


class TestPokemonLanguage:
    def test_non_japanese_pokemon_is_out_of_scope(self):
        for b in ("POKEMON KOREAN SV7-STELLAR MIRACLE",
                  "POKEMON ASIA 25TH ANNIVERSARY PROMO",
                  "POKEMON BASE SET"):
            assert pf.out_of_scope_by_brand(b), f"非日本語 Pokemon を落とせていない: {b}"

    def test_japanese_pokemon_is_kept(self):
        for b in ("POKEMON JAPANESE M2A-MEGA DREAM EX",
                  "POKEMON JAPANESE SV8A-TERASTAL FEST EX",
                  "POKEMON JAPANESE M3-NULLIFYING ZERO"):
            assert pf.out_of_scope_by_brand(b) is None, f"日本語 Pokemon を誤って落とした: {b}"

    def test_english_one_piece_is_kept(self):
        """★one_piece_tcg / dragonball_scg は catalog が en を持つ (実測 en 1,710 / 1,444)。

        言語フィルタを Pokemon 以外に広げたら、ここが落ちる。
        """
        for b in ("ONE PIECE CARD GAME ROMANCE DAWN",
                  "DRAGON BALL SUPER CARD GAME FUSION WORLD AWAKENED PULSE"):
            assert pf.out_of_scope_by_brand(b) is None, f"英語版を誤って落とした: {b}"


def test_empty_brand_is_not_dropped():
    """brand が空なら判定しない (推測で落とさない = fail-closed)."""
    assert pf.out_of_scope_by_brand("") is None
    assert pf.out_of_scope_by_brand(None) is None
