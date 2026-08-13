"""8パックバトル promo の edition 一意特定 回帰テスト (2026-08-13).

依頼: requests/2026-08-12_auto_catalog_add_one_piece_tcg.md (cert160317119)
  PSA brand 'ONE PIECE JAPANESE PROMOS [SANJI 8 PACKS BATTLE-WINNER]' / #004。

判定: ① 正 (ST10-004_p1 は登録済) / ② 誤 (promo resolver が edition を特定できず
fail-closed reject) → 直したのは resolver 側の edition pair のみ。データ追加なし。

両側一致必須 ("8 PACKS BATTLE" in PSA brand かつ "8パックバトル" in official set 名) なので
語順の違う「スタンダードバトルパック」には発火しない。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))

import psa_to_csv as P  # noqa: E402


def test_sanji_8packs_battle_resolves_to_st10_004_p1():
    r = P.lookup_one_piece(
        brand="ONE PIECE JAPANESE PROMOS [SANJI 8 PACKS BATTLE-WINNER]",
        card_number="004",
        subject="SANJI 8 PACKS BATTLE-WINNER",
        verbose=False,
    )
    if r is None:
        pytest.skip("ST10-004_p1 not in shared DB")
    assert r["card_id"] == "ST10-004_p1"
    assert r.get("set_name_ebay") == "Promo Cards"


def test_standard_battle_pack_not_hijacked():
    """語順違いの「スタンダードバトルパック」は 8パックバトル pair に吸われない.

    edition pair は両側一致必須なので、PSA 側に '8 PACKS BATTLE' が無ければ発火しない。
    """
    hay = "ONE PIECE JAPANESE PROMOS [ZORO STANDARD BATTLE PACK VOL.9]"
    assert "8 PACKS BATTLE" not in hay
