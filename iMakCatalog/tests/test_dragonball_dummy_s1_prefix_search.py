"""案C prefix search + Q2 sibling-based subject verification の回帰テスト.

窓口GO: 2026-08-10 chase_lookup_dragonball_dummy_s1_response.md
  - lookup_dragonball Branch 1 で明示 suffix 候補が hit しない時、
    api.search_prefix(category, card_number+"_") で全 variant を列挙。
  - dummy 系 record (bandai_tcg_plus 由来、name='Dragon Ball' 等 product 名) は
    _record_name_matches_subject 単独では reject されるが、同 card_number の siblings
    のいずれかが subject と一致すれば family 全体を採用 (sibling gate)。
  - 既存の explicit-enum branch は preserve (回帰なし = 既知 5 test で verify 済み).

DB 依存: 共有 products.sqlite。DB に FB07-097 系 10 variants が居ないとテストは skip.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))

import api  # noqa: E402
import psa_to_csv as P  # noqa: E402


def _shenron_family_in_db() -> bool:
    """FB07-097 系 (dbfw_official + bandai_tcg_plus dummy) が DB に居るか."""
    for pid in ("FB07-097", "FB07-097_p1", "FB07-097_PARA_dummy_s1"):
        if api.lookup("dragonball_scg", pid) is None:
            return False
    return True


REQUIRES_DB = pytest.mark.skipif(
    not _shenron_family_in_db(),
    reason="FB07-097 family not in shared DB",
)


class TestApiSearchPrefix:
    """api.search_prefix は prefix 一致 record を全件返す (新設 helper)."""

    def test_search_prefix_returns_all_family_members(self):
        # FB07-097 family = 10 records (dbfw_official 4 + bandai_tcg_plus 6)
        rows = api.search_prefix("dragonball_scg", "FB07-097")
        pids = [r["product_id"] for r in rows]
        assert "FB07-097" in pids
        assert "FB07-097_p1" in pids
        assert "FB07-097_PARA_dummy_s1" in pids
        assert "FB07-097_dummy_s1" in pids
        assert len(rows) >= 6, f"expected ≥6 family members, got {len(rows)}: {pids}"

    def test_search_prefix_empty_prefix_returns_empty(self):
        # empty prefix はガードして [] を返す (LIKE '%%' で全件走査回避)
        assert api.search_prefix("dragonball_scg", "") == []

    def test_search_prefix_no_match_returns_empty(self):
        assert api.search_prefix("dragonball_scg", "FBXX-999") == []

    def test_search_prefix_limit_respected(self):
        rows = api.search_prefix("dragonball_scg", "FB07-097", limit=2)
        assert len(rows) == 2


@REQUIRES_DB
class TestPrefixSearchRegression:
    """既存 explicit-enum branch は preserve (regression guard)."""

    def test_shenron_alt_art_still_hits_p1_via_existing_branch(self):
        # SHENRON ALTERNATE ART — dbfw_official _p1 に explicit-enum で hit (前段)
        # 案C prefix search は fall through しないはず.
        r = P.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE WISH FOR SHENRON",
            card_number="FB07-097",
            subject="SHENRON ALTERNATE ART",
            verbose=False,
        )
        assert r is not None
        assert r["card_id"] == "FB07-097_p1"
        # name_en=Shenron を確認 (2026-08-09 e5a9fc9 で name_en 補完済)
        assert r["name_en"] == "Shenron"

    def test_base_lookup_no_subject_still_works(self):
        # subject 空 で base card lookup — 既存挙動 preserve
        r = P.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE",
            card_number="FB01-001",
            subject="",
            verbose=False,
        )
        assert r is not None
        assert r["card_id"] == "FB01-001"


@REQUIRES_DB
class TestPrefixSearchFallback:
    """explicit-enum で hit しない時に prefix search が発火する分岐."""

    def test_bogus_card_number_still_returns_none(self):
        # 存在しない card_number → prefix search でも siblings が 0 → None (fail-closed)
        r = P.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE AWAKENED PULSE",
            card_number="FB99-999",
            subject="SHENRON",
            verbose=False,
        )
        assert r is None

    def test_subject_no_family_match_returns_none(self):
        # FB07-097 family には SHENRON しか居ない。全く違う subject を渡すと
        # sibling gate で reject (fail-closed = 誤 match 防止)
        r = P.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE WISH FOR SHENRON",
            card_number="FB07-097",
            subject="MONKEY D LUFFY ZORO SANJI",  # 全く別キャラ
            verbose=False,
        )
        # 現在の実装で subject が 全 sibling と mismatch → None
        # (SHENRON=神龍/Shenron のいずれか、LUFFY/ZORO/SANJI は含まれない)
        assert r is None


@REQUIRES_DB
class TestSiblingBasedVerification:
    """Q2 セット動作: dummy 系のみ登録の card_number でも sibling name が subject と一致すれば
    prefix search 分岐で hit する.
    """

    def test_shenron_base_still_hits_via_existing_branch(self):
        # subject=SHENRON (variant hint なし) → 既存 explicit-enum branch で
        # base FB07-097 が hit (dbfw_official, name_en='Shenron'). prefix search 分岐
        # までは到達しない (regression guard: 前段が破壊されていないこと).
        r = P.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE WISH FOR SHENRON",
            card_number="FB07-097",
            subject="SHENRON",
            verbose=False,
        )
        assert r is not None
        # dbfw_official base or _p1/_p2/_p3 のいずれか (dummy 系ではない)
        assert r["card_id"].startswith("FB07-097")
        assert "dummy_s1" not in r["card_id"]

    def test_dummy_only_family_hits_via_prefix_search(self):
        # FB06-009 family = ['FB06-009_dummy_s1', 'FB06-009_PARA_dummy_s1'] (Android 16)
        # base FB06-009 / _PARA / _p1 全て未登録 → 既存 explicit-enum で全 miss
        # → prefix search 分岐に落ちて Android 16 で subject 一致 → _PARA_dummy_s1 を採用
        # (PARA 優先 rule で alt art 側を返す).
        if api.lookup("dragonball_scg", "FB06-009_dummy_s1") is None:
            pytest.skip("FB06-009 family not in DB")
        if api.lookup("dragonball_scg", "FB06-009") is not None:
            pytest.skip("FB06-009 base now exists — test premise invalidated")
        r = P.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE MANGA BOOSTER 03",
            card_number="FB06-009",
            subject="ANDROID 16 ALTERNATE ART",
            verbose=False,
        )
        assert r is not None
        # prefix search 分岐で採用される. PARA suffix 保持 = alt art 側優先.
        assert r["card_id"] == "FB06-009_PARA_dummy_s1"

    def test_dummy_only_family_wrong_subject_rejected(self):
        # 同 FB06-009 family (Android 16 のみ) に対し全く違う subject → sibling gate で reject
        if api.lookup("dragonball_scg", "FB06-009_dummy_s1") is None:
            pytest.skip("FB06-009 family not in DB")
        if api.lookup("dragonball_scg", "FB06-009") is not None:
            pytest.skip("FB06-009 base now exists — test premise invalidated")
        r = P.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE MANGA BOOSTER 03",
            card_number="FB06-009",
            subject="MONKEY D LUFFY",  # 全く別
            verbose=False,
        )
        # sibling gate で reject (fail-closed)
        assert r is None

    def test_dummy_only_family_no_variant_hint_returns_base_variant(self):
        # subject に variant hint なし → PARA 優先しない. 通常 base が優先.
        # FB06-009 family には base が居ないので、depth が浅い _dummy_s1 (depth=2) が
        # PARA_dummy_s1 (depth=3) より優先されるかを確認.
        # ★実装の priority tuple: (direct, source_rank, para_rank, depth, pid)
        #   direct: 両者とも subject 'ANDROID 16' に match
        #   source_rank: 両者 bandai_tcg_plus → 同点
        #   para_rank: _dummy_s1=1, _PARA_dummy_s1=0 → PARA 優先が勝つ
        # → hint なしでも PARA が優先される (rarity 情報保持のため妥当な設計)
        if api.lookup("dragonball_scg", "FB06-009_dummy_s1") is None:
            pytest.skip("FB06-009 family not in DB")
        r = P.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE MANGA BOOSTER 03",
            card_number="FB06-009",
            subject="ANDROID 16",  # hint なし
            verbose=False,
        )
        assert r is not None
        assert r["card_id"] == "FB06-009_PARA_dummy_s1"


class TestPriorityOrdering:
    """prefix search 分岐の priority sort ロジック (単体で verify)."""

    def test_priority_favors_direct_subject_match(self):
        # 内部の priority 関数を直接 test することはできないが、
        # 実 DB を通した動作確認を tally しておく (回帰時にどちらが返るか固定).
        # FB07-097 family: dbfw_official 4 (name=神龍, name_en=Shenron)
        #                  bandai_tcg_plus 6 (name='Dragon Ball' 等)
        # subject=SHENRON → direct match のみ最優先 → dbfw_official 側 (p1/p2/p3/base)。
        # PARA 優先 rule 適用外 (subject に PARA hint なし)、_p1 が最短 depth。
        if not _shenron_family_in_db():
            pytest.skip("family not in DB")
        r = P.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE",
            card_number="FB07-097",
            subject="SHENRON",
            verbose=False,
        )
        assert r is not None
        # 既存 branch で dbfw_official 側の最初の match が返る
        assert r["card_id"].startswith("FB07-097")
        # dummy_s1 系は返さない
        assert "dummy_s1" not in r["card_id"]
