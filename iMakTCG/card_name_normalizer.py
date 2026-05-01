"""card_name_normalizer - PSA Subject 由来の Card Name/Character から variant suffix 剥がし.

設計原則 (修正連鎖を生まないため):
  - 既存モジュール (psa_to_csv.extract_character_name / pokemon_card_jp 等) を一切修正しない
  - psa_to_csv は character/card_name を normalize() に通すだけ (1-2 行 wire-in)
  - 失敗時は元値返却 (フォールバック耐性)

設計思想:
  PSA Subject はカード上の印字情報をそのまま持っており、雑誌付録/Promo/Anniversary 等の
  variant suffix が含まれる。これを Item Specifics の Card Name/Character にそのまま流すと:
    - eBay フィルタヒットしない (検索品質劣化)
    - バイヤー混乱 (商品名が冗長すぎる)

  既存 `extract_character_name` (psa_to_csv.py) は基本的な suffix を扱うが、新カード形式
  (雑誌付録/Anniversary 略号/Pokemon 略号 prefix) に都度未対応。本モジュールはそれを補強.

剥がし対象 (失敗ナレッジ蓄積、新ケースで都度追加):
  - 雑誌付録: "Weekly Shonen Jump '24-#35" 等
  - Pokemon prefix: "FA/", "AR/", "SR/", "SAR/", "UR/", "HR/", "MR/", "PR/"
  - Pokemon set 略号: "25TH ANNIVERSARY COLL.", "VSTAR UNIVERSE", "BATTLE PARTNERS" 等
  - One Piece event: "ICHIBAN KUJI PURCHASE BONUS", "LET'S START CP", "MINI-TIN PK SET" 等
  - 末尾記号トリム: trailing hyphen/comma/period (例: '24- → '24)

使用例:
    from card_name_normalizer import normalize_card_name
    raw = "JEWELRY BONNEY WEEKLY SHONEN JUMP '24-#35"
    clean = normalize_card_name(raw)
    # clean = "Jewelry Bonney"
"""
from __future__ import annotations

import re
from typing import Optional


# ============================================================================
# 剥がし対象パターン (末尾 anchor、長い順)
# 失敗ナレッジ: 新パターン発見時はここに追加
# ============================================================================

# Pokemon set/event variant 略号 (longer first)
_POKEMON_SUFFIXES = [
    r"\d+(?:ND|ST|RD|TH)\s+ANNIVERSARY\s+COLLECTION",
    r"\d+(?:ND|ST|RD|TH)\s+ANNIVERSARY\s+COLL\.?",
    r"\d+(?:ND|ST|RD|TH)\s+ANNIVERSARY",
    r"ANNIVERSARY\s+COLLECTION",
    r"ANNIVERSARY\s+COLL\.?",
    r"VSTAR\s+UNIVERSE",
    r"SPACE\s+JUGGLER",
    r"BATTLE\s+PARTNERS",
    r"TERASTAL\s+FESTIVAL\s+EX",
    r"TERASTAL\s+FESTIVAL",
    r"SPECIAL\s+ART\s+RARE",
    r"SPECIAL\s+ART",
    r"ART\s+RARE",
    r"ART",  # 単独 "ART" (= Art Rare 略号、Pokemon)
    r"COLL\.?",  # 単独の "COLL." 残骸
    # 2026-05-01: 観測済 Pokemon set 名 suffix (psa_to_csv._pokemon_card_name と同期).
    # 上流 (_pokemon_card_name) で剥がれていない場合の defense in depth.
    r"INCANDESCENT\s+ARCANA",
    r"EEVEE\s+HEROES",
    r"SHINY\s+STAR\s+V",
    r"DARK\s+PHANTASMA",
    r"WILD\s+FORCE",
    r"SHINY\s+TREASURE\s+EX",
    r"MEGA\s+DREAM\s+EX",
    r"POKEMON\s+GO",
    r"SUPER",  # 単独 'SUPER' rarity 残骸 (Gengar Ex Super case)
]

# One Piece event/promo variant 略号
_ONEPIECE_SUFFIXES = [
    r"ICHIBAN\s+KUJI\s+PURCHASE\s+BONUS",
    r"ICHIBAN\s+KUJI",
    r"LET'?S\s+START\s+CP\s+PR\s+PCK[\s\-A-Z]*",
    r"LET'?S\s+START\s+CP",
    r"MINI[\s\-]?TIN\s+PK\s+SET\s+VOL\.?\s*\d+[\s\-A-Z]*",
    r"MINI[\s\-]?TIN\s+PACK\s+SET",
    r"MINI[\s\-]?TIN",
    r"WEEKLY\s+SHONEN\s+JUMP[\s\S]*",  # 末尾全部 (号数等含む)
    r"MONTHLY\s+COMIC[\s\S]*",
    r"WEEKLY\s+JUMP[\s\S]*",
    r"V\s*JUMP[\s\S]*",
    r"PREMIUM\s+CARD\s+COLLECTION[\s\-A-Z]*",
    r"BEST\s+SELECTION\s+VOL\.?\s*\d+",
    r"BEST\s+SELECTION",
]

# Pokemon prefix (前置)
_POKEMON_PREFIXES = [
    r"FA",   # Full Art
    r"AR",   # Art Rare
    r"SAR",  # Special Art Rare
    r"SR",   # Super Rare
    r"UR",   # Ultra Rare
    r"HR",   # Hyper Rare
    r"MR",   # Mega Rare?
    r"PR",   # Promo
]


# ============================================================================
# 公開 API
# ============================================================================
def normalize_card_name(raw: Optional[str], franchise: str = "") -> str:
    """PSA Subject 由来文字列から variant suffix/prefix を剥がしてキャラ名のみ抽出.

    Args:
        raw: 生 Card Name/Character (PSA Subject 由来)
        franchise: 'Pokemon' / 'One Piece' / '' (auto). 不明時は両 franchise の suffix 試行.

    Returns:
        正規化済みキャラ名. 全部削れて空になる場合は raw を Title Case 化して返す.
    """
    if not raw:
        return raw or ""

    try:
        s = raw.strip()
        if not s:
            return raw

        # Pokemon prefix 剥がし (例: "FA/PIKACHU" → "PIKACHU")
        prefix_pattern = r"^(?:" + r"|".join(_POKEMON_PREFIXES) + r")/+"
        s = re.sub(prefix_pattern, "", s, flags=re.IGNORECASE)

        # 末尾 suffix 剥がし (繰り返し: 多重 suffix 対応)
        all_suffixes = _POKEMON_SUFFIXES + _ONEPIECE_SUFFIXES
        changed = True
        max_iter = 8
        while changed and max_iter > 0:
            changed = False
            max_iter -= 1
            for pat in all_suffixes:
                new_s = re.sub(r"\s+" + pat + r"\s*$", "", s, flags=re.IGNORECASE)
                if new_s != s:
                    s = new_s.strip()
                    changed = True
                    break

        # 末尾の余り記号トリム ('24- や ., や - 単独残し)
        s = re.sub(r"['\s\-,.]+$", "", s).strip()

        if not s:
            return raw  # 全部削れた場合は元値維持 (安全側)

        # 大文字 → Title Case (BOA HANCOCK → Boa Hancock)
        # 既に Mixed/Lower の場合は触らない
        if s.isupper():
            s = _smart_title_case(s)

        return s

    except Exception as e:
        print(f"    ⚠️ card_name_normalizer 例外、元値採用: {type(e).__name__}: {e}")
        return raw


# ============================================================================
# 内部処理
# ============================================================================
def _smart_title_case(s: str) -> str:
    """大文字キャラ名 → Title Case. 'D' (ミドルイニシャル) はそのまま大文字維持."""
    parts = re.split(r"(\s+|\.)", s)
    out = []
    for p in parts:
        if not p or p.isspace() or p == ".":
            out.append(p)
            continue
        if len(p) == 1 and p.isalpha():
            out.append(p.upper())  # "D" / "C" 等のイニシャルは大文字
        else:
            out.append(p.capitalize())
    return "".join(out)


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    samples = [
        # Bonney (雑誌付録)
        ("JEWELRY BONNEY WEEKLY SHONEN JUMP '24-#35", "One Piece", "Jewelry Bonney"),
        # Pikachu 25th (FA prefix + COLL. suffix)
        ("FA/PIKACHU 25TH ANNIVERSARY COLL.", "Pokemon", "Pikachu"),
        # Flying Pikachu V 25th
        ("FLYING PIKACHU V 25TH ANNIVERSARY COLL.", "Pokemon", "Flying Pikachu V"),
        # Eevee EX SAR
        ("EEVEE EX SPECIAL ART", "Pokemon", "Eevee Ex"),
        # Elesa Sparkle FA + VSTAR UNIVERSE
        ("FA/ELESA'S SPARKLE VSTAR UNIVERSE", "Pokemon", "Elesa's Sparkle"),
        # Lillie's Ribombee Art
        ("LILLIE'S RIBOMBEE ART", "Pokemon", "Lillie's Ribombee"),
        # P-001 Ichiban Kuji
        ("MONKEY D. LUFFY ICHIBAN KUJI PURCHASE BONUS", "One Piece", "Monkey D. Luffy"),
        # Nami Mini-Tin
        ("NAMI MINI-TIN PK SET VOL.2-BISAI", "One Piece", "Nami"),
        # 通常 (変更なし)
        ("BOA HANCOCK", "One Piece", "Boa Hancock"),
        ("Monkey D. Luffy", "One Piece", "Monkey D. Luffy"),
        # Hancock 技名 (これは TitleAgent / Identification Agent で別途処理)
        ("PERFUME FEMUR", "One Piece", "Perfume Femur"),
        # 空入力
        ("", "", ""),
    ]
    print("=== CLI test ===")
    for raw, fr, expected in samples:
        out = normalize_card_name(raw, fr)
        ok = "✓" if out == expected else "✗"
        print(f"  {ok}  raw={raw!r:>50}  → {out!r}  (期待={expected!r})")
