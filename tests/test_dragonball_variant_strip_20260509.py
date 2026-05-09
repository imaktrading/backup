"""Regression: 2026-05-09 Dragon Ball SCG BCGF World Tour promo の variant suffix 残留.

事故 (csv_output/tcg_upload_20260509_154142.csv Row 2):
  cert 89740092  Son Goku FS02-04 (BCGF23-24 World Tour Promo print):
    C:Card Name = "Son Goku BCGF23-24 World Tour"  (event/tournament suffix 残留)
    C:Character = "Son Goku BCGF23-24 World Tour"  (同上)
  → eBay フィルタヒット劣化 + バイヤー視認性低下.

修正方針 (本体 logic 不変、list 拡張のみ):
  iMakTCG/card_name_normalizer.py に _DRAGONBALL_SUFFIXES を新設し、
  - "BCGF23-24 World Tour" / "BCGF24-25 World Tour Promo" 等の Bandai Card Games Fest
    + World Tour 系 promo 接尾辞を網羅
  - all_suffixes へ統合 (Pokemon/One Piece と並列)

設計原則:
  - 既存 Pokemon/One Piece 剥がしロジックは不変 (副作用ゼロ)
  - データ追加のみ (CLAUDE.md spell #1 "その修正、YAML でできないか？" 準拠)
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"
if str(_TCG) not in sys.path:
    sys.path.insert(0, str(_TCG))


def _load_psa_to_csv_tcg():
    """sys.modules キャッシュ汚染回避用、絶対パスから iMakTCG/psa_to_csv.py を load.
    別 test (iMakCatalog/integrations/psa_to_csv.py を import する) の影響で
    full suite 走行時に同名 module 名衝突する事故を防ぐ.
    """
    path = _TCG / "psa_to_csv.py"
    spec = importlib.util.spec_from_file_location("_test_psa_to_csv_tcg_dragonball", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_strips_bcgf_world_tour_5_9_case():
    """5/9 実事故ケース: 'Son Goku BCGF23-24 World Tour' → 'Son Goku'."""
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("Son Goku BCGF23-24 World Tour", "Dragon Ball") == "Son Goku"


def test_strips_bcgf_world_tour_uppercase():
    """大文字も Title Case 化される."""
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("SON GOKU BCGF23-24 WORLD TOUR", "Dragon Ball") == "Son Goku"


def test_strips_bcgf_world_tour_promo_variant():
    """'WORLD TOUR PROMO' (より長い変種) も剥がす."""
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("VEGETA BCGF24-25 WORLD TOUR PROMO", "Dragon Ball") == "Vegeta"


def test_strips_bandai_card_games_fest_only():
    """BCGF 接頭詞無しの 'Card Games Fest' 単独でも剥がせる."""
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("Piccolo Card Games Fest 2024", "Dragon Ball") == "Piccolo"


def test_existing_pokemon_behavior_preserved():
    """副作用ゼロ確認: 既存 Pokemon 剥がしは無変更."""
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("FA/PIKACHU 25TH ANNIVERSARY COLL.", "Pokemon") == "Pikachu"
    assert normalize_card_name("Ho-Oh V Incandescent Arcana", "Pokemon") == "Ho-Oh V"


def test_existing_onepiece_behavior_preserved():
    """副作用ゼロ確認: 既存 One Piece 剥がしは無変更."""
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("JEWELRY BONNEY WEEKLY SHONEN JUMP '24-#35", "One Piece") == "Jewelry Bonney"


def test_no_overstrip_when_no_variant():
    """variant 無しの平 character は不変."""
    from card_name_normalizer import normalize_card_name
    assert normalize_card_name("Son Goku", "Dragon Ball") == "Son Goku"
    assert normalize_card_name("Vegeta", "Dragon Ball") == "Vegeta"


# ============================================================================
# Title 経路 (build_title 入口) でも subject pre-normalization が効くこと
# 5/9 17:43 再送で発覚: card_name_normalizer は Card Name/Character には効くが、
# build_title が raw subject を直接使うため Title に BCGF 残留していた事故対応.
# ============================================================================
def test_build_title_with_normalized_subject_strips_bcgf():
    """psa_to_csv の subject_clean = normalize_card_name(...) → build_title 経路で
    BCGF World Tour suffix が title に混入しないこと.
    """
    from card_name_normalizer import normalize_card_name
    _psa_tcg = _load_psa_to_csv_tcg()

    subject_clean = normalize_card_name("SON GOKU BCGF23-24 WORLD TOUR", "Dragon Ball")
    assert subject_clean == "Son Goku"

    title = _psa_tcg.build_title(
        "Dragon Ball Super Card Game",
        "Bandai Card Games Fest23-24 World Tour Promo",
        "FS02-04",
        subject_clean,
    )
    # 主要回帰目標: Subject 由来の "BCGF23-24" は title に出ない
    assert "BCGF" not in title, f"BCGF should not appear in title, got: {title!r}"
    # Son Goku は残る
    assert "Son Goku" in title


def test_build_title_with_normalized_subject_no_change_for_clean_input():
    """副作用ゼロ: variant 無しの subject はそのまま title に組込まれる."""
    from card_name_normalizer import normalize_card_name
    _psa_tcg = _load_psa_to_csv_tcg()

    subject_clean = normalize_card_name("VEGETA", "Dragon Ball")
    assert subject_clean.lower() == "vegeta"

    title = _psa_tcg.build_title(
        "Dragon Ball Super Card Game",
        "STARTER DECK VEGETA",
        "FS02-01",
        subject_clean,
    )
    assert "Vegeta" in title
