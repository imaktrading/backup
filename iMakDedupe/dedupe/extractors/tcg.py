"""TCG カテゴリ (One Piece / Pokemon / Yu-Gi-Oh!) card_id 抽出.

fail-closed: 明確に hit しない title は None を返す (= 「不明」)。
複数 hit したら最初の 1 件を採用 (= タイトル先頭に card_id 出る慣習)。
"""

from __future__ import annotations

import re
from typing import Optional

_ONE_PIECE_RE = re.compile(
    r"#?((?:OP|ST|EB|PRB)\d+-\d+|P-\d+)",
    re.IGNORECASE,
)

# Phase 1d-TCG (2026-05-27): set 番号 + # 番号 別離 pattern.
# eBay snapshot title で「One Piece Card OP13 #119 Portgas」 のように set 番号と
# # 番号が space で分離される形式が大半。 結合形 `#OP13-119` は少数派。
# 間に商品名等 (= "Card", "Heroines Edition") が挟まるため `.*?` で許容。
# group(1)=prefix (OP/ST/EB/PRB)、 group(2)=set 番号、 group(3)=card 番号
_ONE_PIECE_SPLIT_RE = re.compile(
    r"\b(OP|ST|EB|PRB)(\d+)\b.*?#(\d+)\b",
    re.IGNORECASE,
)

_POKEMON_RE = re.compile(
    r"(?:#|\b)((?:SV|SM|S)\d+[a-z]?-\d+)\b",
    re.IGNORECASE,
)

_YUGIOH_RE = re.compile(
    r"\b([A-Z]{2,5}-(?:JP|EN)\d+)\b",
)


def extract_one_piece_id(title: str) -> Optional[str]:
    """One Piece TCG card_id 抽出.

    優先順 (Phase 1d-TCG):
    1. 結合形 `#OP01-016` / `OP01-016` (= 既存 Phase 0、 強い anchor)
    2. 分離形 `OP13 ... #119` → 結合 `OP13-119` (= Phase 1d 新規)

    set 番号 / # 番号 のいずれも欠ける title (= `Heroines Special Set Don!! Card`、
    `2nd Anniversary #081`) は **fail-closed = None**。 推測で結合しない。
    """
    if not title:
        return None
    m = _ONE_PIECE_RE.search(title)
    if m:
        return m.group(1).upper()
    m = _ONE_PIECE_SPLIT_RE.search(title)
    if m:
        return f"{m.group(1).upper()}{m.group(2)}-{m.group(3)}"
    return None


def extract_pokemon_id(title: str) -> Optional[str]:
    """Pokemon TCG card_id (= SV1a-001 / SM12-100)."""
    if not title:
        return None
    m = _POKEMON_RE.search(title)
    return m.group(1).upper() if m else None


def extract_yugioh_id(title: str) -> Optional[str]:
    """Yu-Gi-Oh! card_id (= LB-JP001 / LIOV-EN042)."""
    if not title:
        return None
    m = _YUGIOH_RE.search(title)
    return m.group(1).upper() if m else None


def extract_tcg_id(title: str) -> Optional[str]:
    """全 TCG カテゴリで試行、 最初に hit したものを返す.

    優先順位: One Piece > Pokemon > Yu-Gi-Oh!
    (One Piece が現状 iMak 主力、 hit 確度が最も高い)
    """
    if not title:
        return None
    for fn in (extract_one_piece_id, extract_pokemon_id, extract_yugioh_id):
        result = fn(title)
        if result:
            return result
    return None
