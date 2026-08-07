"""title_generation_agent の回帰テスト.

2026-06-13: _ensure_character_in_title が variant 込み character
('Scrafty Art' 等) を丸ごと追加し、タイトル中の既出キャラ名
('Scrafty Card') と重複させる事故 (#137 Scrafty / #089 Bombirdier /
#101 Blaziken / #077 Irida) の再発防止。token 単位で未出のものだけ
追加する仕様を固定する。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from title_generation_agent import _ensure_character_in_title, refine_title


def _dup_tokens(title: str) -> list:
    """4字以上の語で 2 回以上出現するもの (= 重複) を返す."""
    toks = [w.lower() for w in re.split(r"\s+", title) if len(w) >= 4]
    return sorted({w for w in toks if toks.count(w) > 1})


# ---------------------------------------------------------------------------
# 重複事故の再発防止 (2026-06-13)
# ---------------------------------------------------------------------------
def test_variant_character_does_not_duplicate_existing_name():
    """character='Scrafty Art' / title に既に 'Scrafty' → 'Art' のみ追加、重複なし."""
    title = "PSA 10 Pokemon Scarlet & Violet—White Flare #137/086 Scrafty Card"
    out = _ensure_character_in_title(title, "Scrafty Art")
    assert out == "PSA 10 Pokemon Scarlet & Violet—White Flare #137/086 Scrafty Card Art"
    assert _dup_tokens(out) == []


def test_variant_character_multi_token_suffix_dedup():
    """character='Irida Space Juggler' / 'Irida' 既出 → 'Space Juggler' のみ追加."""
    title = "PSA 10 Pokemon Sword & Shield—Astral Radiance #077/067 Irida Card"
    out = _ensure_character_in_title(title, "Irida Space Juggler")
    assert out == "PSA 10 Pokemon Sword & Shield—Astral Radiance #077/067 Irida Card Space Juggler"
    assert "irida" not in [w.lower() for w in out.split() if out.lower().split().count(w.lower()) > 1]
    assert _dup_tokens(out) == []


def test_all_four_regression_cases_no_dup():
    """6/13 run で重複した 4 件すべてで重複ゼロ."""
    cases = [
        ("PSA 10 Pokemon Scarlet & Violet—White Flare #137/086 Scrafty Card", "Scrafty Art"),
        ("PSA 10 Pokemon Scarlet & Violet—Violet ex #089/078 Bombirdier Card", "Bombirdier Art"),
        ("PSA 10 Pokemon Scarlet & Violet—Destined Rivals #101/098 Blaziken Card", "Blaziken Art"),
        ("PSA 10 Pokemon Sword & Shield—Astral Radiance #077/067 Irida Card", "Irida Space Juggler"),
    ]
    for title, char in cases:
        out = _ensure_character_in_title(title, char)
        assert _dup_tokens(out) == [], f"dup in: {out!r}"


# ---------------------------------------------------------------------------
# 既存挙動の回帰 (壊していないこと)
# ---------------------------------------------------------------------------
def test_full_character_absent_still_appended():
    """技名 Subject でキャラ名が title 不在 → フル追加 (Hancock 補完) は維持."""
    title = "PSA 10 One Piece TCG 500 Years in the Future #OP07-057 Perfume Femur Card"
    out = _ensure_character_in_title(title, "Boa Hancock")
    assert out.endswith("Boa Hancock")


def test_character_already_present_is_noop():
    """character がフル一致で既出 → 何も足さない."""
    title = "PSA 10 Pokemon Battle Partners #105 Lillie's Ribombee Art Rare"
    assert _ensure_character_in_title(title, "Lillie's Ribombee") == title


def test_empty_character_noop():
    title = "PSA 10 Pokemon #001 Pikachu"
    assert _ensure_character_in_title(title, None) == title
    assert _ensure_character_in_title(title, "") == title


def test_refine_title_end_to_end_no_dup():
    """公開 API refine_title 経由でも重複が出ない."""
    out = refine_title(
        "PSA 10 Pokemon Scarlet & Violet—Destined Rivals #101/098 Blaziken Card",
        character="Blaziken Art", franchise="Pokemon TCG",
    )
    assert _dup_tokens(out) == []
