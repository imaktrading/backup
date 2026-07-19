"""2026-07-18 (HQ依頼 dbscg_resolver_rarity_recovery) の回帰アンカー.

A. lookup_dragonball: _PARA/_p1 二重ソース重複では rarity 保持側(_PARA)を優先。
B. ★付き rarity_ebay を base コードへ正規化 + Features='Alternative Art'。
read-side + rarity正規化のみ (alias_of/KEY 非接触)。共有DB依存。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import psa_to_csv as P  # noqa: E402


def _db(brand, num, subj):
    return P.lookup_dragonball(brand=brand, card_number=num, subject=subj, verbose=False)


def test_A_fb01_071_altart_prefers_para():
    # cert158452539: _p1(rarity空)でなく _PARA(rarity保持)に解決
    r = _db("DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE",
            "FB01-071", "SON GOHAN CHILDHOOD ALTERNATE ART")
    assert r is not None
    assert r["card_id"] == "FB01-071_PARA"


def test_A_fb04_051_altart_prefers_para():
    # cert158452538
    r = _db("DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE MANGA BOOSTER 01",
            "FB04-051", "VEGETA ALTERNATE ART")
    assert r is not None
    assert r["card_id"] == "FB04-051_PARA"


def test_B_star_rarity_normalized_and_features():
    # L★ → SCR に正規化、Features に 'Alternative Art'
    r = _db("DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE",
            "FB01-071", "SON GOHAN CHILDHOOD ALTERNATE ART")
    assert "★" not in (r.get("rarity") or "")           # ★ 除去
    assert r["rarity"] == "SCR"                          # L★ → SCR (既存yaml準拠)
    assert "Alternative Art" in (r.get("features") or [])
    # C:Rarity が非空 (fail-closed skip を回避 = 受け入れ条件1)
    assert r["rarity"]


def test_B_base_card_rarity_unaffected():
    # ★無しの base カードは正規化の影響を受けない
    r = _db("DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE",
            "FB01-001", "")
    assert r is not None
    assert "★" not in (r.get("rarity") or "")
    assert "Alternative Art" not in (r.get("features") or [])
