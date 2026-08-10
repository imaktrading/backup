"""DBSCG LEADER rarity backfill (2026-08-10) 回帰テスト.

窓口GO: requests/2026-08-09_audit_catalog_fix_tcg_response.md §A+B+C

対象:
  A. scripts/backfill_dbscg_leader_rarity_20260810.py の対象/規則の同定
  B. migrations/2026-05-30_dbfw_official_import.py の LEADER rarity 導出 guard
  C. psa_to_csv._to_legacy_dict_dragonball が backfill 済の _p1 で SCR + Alternative Art を返すこと
     (unit test: mock record) と、実 DB 側の cert 158452540 相当 record が正しく resolve すること
     (integration test: DB 依存で skip 可)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "integrations"))


def _load_backfill_module():
    """ハイフン入り (無効な module 名) の migrations も load できるよう importlib で."""
    path = _REPO / "scripts" / "backfill_dbscg_leader_rarity_20260810.py"
    spec = importlib.util.spec_from_file_location("_bf_leader_rarity_20260810", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_dbfw_import_module():
    path = _REPO / "migrations" / "2026-05-30_dbfw_official_import.py"
    spec = importlib.util.spec_from_file_location("_dbfw_official_import", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bf = _load_backfill_module()
di = _load_dbfw_import_module()


# ------------------------------------------------------------------
# A. backfill script の規則・対象確定 (unit, DB 非依存)
# ------------------------------------------------------------------
class TestBackfillTargets:
    def test_target_count_is_14_fp030_excluded(self):
        # 依頼: 14件 (FP-030 除外)
        assert bf.EXPECTED == 14
        assert "FP-030" not in bf.BASE_TARGETS
        assert "FP-030" not in bf.ALT_ART_TARGETS
        assert "FP-030_p1" not in bf.ALT_ART_TARGETS

    def test_base_targets_are_4(self):
        assert set(bf.BASE_TARGETS) == {
            "FB07-025", "FB07-073", "FB07-097", "SB01-029",
        }

    def test_alt_art_targets_are_10(self):
        assert set(bf.ALT_ART_TARGETS) == {
            "FB01-070_p1", "FB03-078_p1", "FB04-103_p1",
            "FB07-025_p1", "FB07-073_p1", "FB07-097_p1",
            "FB09-073_p1", "SB01-029_p1",
            "FB07-097_p2", "FB07-097_p3",
        }

    def test_derive_rarity_base_returns_L_Leader(self):
        assert bf.derive_rarity(None) == ("L", "Leader")
        # variant_type='' も base 扱い
        assert bf.derive_rarity("") == ("L", "Leader")

    def test_derive_rarity_alt_art_returns_Lstar(self):
        assert bf.derive_rarity("alt_art") == ("L★", "L★")


# ------------------------------------------------------------------
# B. ingest guard の unit test (_derive_leader_rarity)
# ------------------------------------------------------------------
class TestIngestGuard:
    def test_alt_art_leader_derives_Lstar(self):
        specs = {"card_type": "LEADER", "variant_type": "alt_art"}
        assert di._derive_leader_rarity("FB01-070_p1", specs) == ("L★", "L★")

    def test_base_leader_derives_L_Leader(self):
        specs = {"card_type": "LEADER"}
        assert di._derive_leader_rarity("FB07-097", specs) == ("L", "Leader")

    def test_denylist_fp030_not_derived(self):
        # FP-030 は base 兄弟が L★ のみで裏付けなし → 空維持 (fail-closed)
        specs = {"card_type": "LEADER"}
        assert di._derive_leader_rarity("FP-030", specs) is None

    def test_non_leader_not_touched(self):
        specs = {"card_type": "BATTLE"}
        assert di._derive_leader_rarity("FB07-001", specs) is None

    def test_existing_rarity_not_overwritten(self):
        specs = {"card_type": "LEADER", "rarity": "L", "rarity_ebay": "Leader"}
        assert di._derive_leader_rarity("FB07-097", specs) is None

    def test_existing_rarity_ebay_not_overwritten(self):
        # rarity_ebay 単独が入っていても書き換えない
        specs = {"card_type": "LEADER", "rarity_ebay": "Leader"}
        assert di._derive_leader_rarity("FB07-097", specs) is None

    def test_build_specs_applies_guard_on_leader_alt_art(self):
        entry = {
            "card_id": "FB07-097_p1",
            "カードタイプ": "LEADER",
            "入手情報": "",
        }
        specs = di._build_specs(entry, existing_specs=None)
        assert specs.get("card_type") == "LEADER"
        assert specs.get("variant_type") == "alt_art"
        assert specs.get("rarity") == "L★"
        assert specs.get("rarity_ebay") == "L★"
        assert "derived" in (specs.get("spec_source") or "")

    def test_build_specs_applies_guard_on_leader_base(self):
        entry = {"card_id": "FB07-097", "カードタイプ": "LEADER", "入手情報": ""}
        specs = di._build_specs(entry, existing_specs=None)
        assert specs.get("rarity") == "L"
        assert specs.get("rarity_ebay") == "Leader"

    def test_build_specs_denylist_fp030_stays_empty(self):
        entry = {"card_id": "FP-030", "カードタイプ": "LEADER", "入手情報": ""}
        specs = di._build_specs(entry, existing_specs=None)
        assert specs.get("card_type") == "LEADER"
        assert specs.get("rarity") is None
        assert specs.get("rarity_ebay") is None


# ------------------------------------------------------------------
# C. psa_to_csv 側 ★-strip 経路の unit test (mock record)
# ------------------------------------------------------------------
class TestLegacyDictAltArtLeader:
    def _make_record(self, rarity: str, rarity_ebay: str) -> dict:
        return {
            "category": "dragonball_scg",
            "product_id": "FB07-097_p1",
            "name": "神龍",
            "name_en": "Shenron",
            "set_name": "神龍への願い",
            "set_name_official": "ブースターパック 神龍への願い [FB07]",
            "language": "both",
            "source": "dbfw_official",
            "images": ["https://example/x.png"],
            "specs": {
                "rarity": rarity,
                "rarity_ebay": rarity_ebay,
                "card_type": "LEADER",
                "variant_type": "alt_art",
                "card_number_text": "FB07-097",
                "set_name_ebay": "Wish For Shenron",
            },
        }

    def test_lstar_yields_scr_and_alternative_art(self):
        import psa_to_csv as pc  # type: ignore
        rec = self._make_record("L★", "L★")
        legacy = pc._to_legacy_dict_dragonball(rec)
        assert legacy["rarity"] == "SCR"
        assert legacy["rarity_ebay"] == "SCR"
        assert "Alternative Art" in (legacy.get("features") or [])

    def test_L_yields_Leader_no_alt_art_feature(self):
        import psa_to_csv as pc  # type: ignore
        rec = self._make_record("L", "Leader")
        rec["specs"]["variant_type"] = None
        legacy = pc._to_legacy_dict_dragonball(rec)
        assert legacy["rarity"] == "Leader"
        assert legacy["rarity_ebay"] == "Leader"
        assert "Alternative Art" not in (legacy.get("features") or [])


# ------------------------------------------------------------------
# 統合テスト (実 DB 依存 — 対象 record が居なければ skip)
# ------------------------------------------------------------------
try:
    from iMakCatalog import api as _api
    import psa_to_csv as _pc  # type: ignore
    _has_db = _api.lookup(category="dragonball_scg", product_id="FB07-097_p1") is not None
except Exception:
    _has_db = False

REQUIRES_DB = pytest.mark.skipif(
    not _has_db, reason="dragonball_scg FB07-097_p1 not in shared DB",
)


@REQUIRES_DB
class TestFB07097P1LookupIntegration:
    """cert 158452540 相当 (SHENRON alt art) が SCR + Alternative Art で返ること.

    注: このテストは backfill 適用後にのみ pass する (それ以前は skip 相当の空を返す)。
    Backfill 未適用時は xfail ではなく skip として扱う (テストが「そこにあること」自体を確定させる)。
    """

    def test_shenron_alt_art_lookup_returns_scr(self):
        import psa_to_csv as pc  # type: ignore
        from iMakCatalog import api

        rec = api.lookup(category="dragonball_scg", product_id="FB07-097_p1")
        if rec is None:
            pytest.skip("FB07-097_p1 not in DB")
        if not (rec["specs"].get("rarity") or rec["specs"].get("rarity_ebay")):
            pytest.skip("backfill (§A) not yet applied — DB rarity still empty")

        r = pc.lookup_dragonball(
            brand="DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE WISH FOR SHENRON",
            card_number="FB07-097",
            subject="SHENRON ALTERNATE ART",
            verbose=False,
        )
        assert r is not None
        assert r["card_id"] == "FB07-097_p1"
        assert r.get("rarity_ebay") == "SCR"
        assert "Alternative Art" in (r.get("features") or [])
