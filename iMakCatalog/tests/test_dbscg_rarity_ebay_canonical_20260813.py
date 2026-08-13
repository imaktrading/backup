"""DBSCG rarity_ebay canonical 是正 (2026-08-13) の回帰アンカー.

依頼: requests/2026-08-13_dbscg_rarity_ebay_raw_values.md (HQ / 実害 cert158452539)

確定事実 (公式を 2026-08-13 に実取得):
  https://www.dbs-cardgame.com/fw/{jp,en}/cardlist/ の rarity filter は
  **L / C / UC / R / SR / SCR / PR の 7 値のみ**。★ は公式 rarity 語彙に無い。
  detail.php?card_no=FB01-071 も rarity="L" (★なし) を返す。
  → ★ は parallel / alt-art の刷り違いマーカーであり rarity ではない。

したがって:
  - specs.rarity_ebay には ★ を落とした base の eBay canonical 値が入る
  - ★ の意味は Features='Alternative Art' が担う
  - 旧 "L★ → SCR" は「Leader parallel を Secret Rare と名乗る」誤りなので廃止
  - 変換は catalog 側で完了 (契約 v1.2 §1-1)、出品側は再変換しない
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))

from iMakCatalog import api  # noqa: E402
from iMakCatalog.ebay_filter_map import loader  # noqa: E402

CAT = "dragonball_scg"

# 公式 rarity 語彙 (2026-08-13 実取得) → eBay master (cat 183454) 実在値
OFFICIAL_TO_EBAY = {
    "L": "Leader",          # master に Leader は無いが facet は FREE_TEXT (HQ 裁定 2026-07-21)
    "C": "Common",
    "UC": "Uncommon",
    "R": "Rare",
    "SR": "Super Rare",
    "SCR": "Secret Rare",
    "PR": "Promo",
}


class TestYaml:
    def test_yaml_covers_official_vocabulary_only(self):
        data = loader.load_yaml(loader.YAML_DIR / "dragonball.yaml")
        m = {e["source"]: e["ebay"] for e in data["rarity"]}
        for src, expected in OFFICIAL_TO_EBAY.items():
            assert m.get(src) == expected, f"{src} → {m.get(src)!r} (expected {expected!r})"

    def test_yaml_has_no_star_entries(self):
        data = loader.load_yaml(loader.YAML_DIR / "dragonball.yaml")
        stars = [e["source"] for e in data["rarity"] if "★" in str(e["source"])]
        assert stars == [], f"★ は公式 rarity ではない: {stars}"


class TestDeriveRarityEbay:
    def test_star_is_stripped_before_lookup(self):
        assert api.derive_rarity_ebay(CAT, "L★") == "Leader"
        assert api.derive_rarity_ebay(CAT, "L★★") == "Leader"
        assert api.derive_rarity_ebay(CAT, "SR★") == "Super Rare"
        assert api.derive_rarity_ebay(CAT, "SCR★★") == "Secret Rare"

    def test_base_codes_map_to_master_values(self):
        for src, expected in OFFICIAL_TO_EBAY.items():
            assert api.derive_rarity_ebay(CAT, src) == expected

    def test_unmapped_is_fail_closed_none(self):
        # 未登録は raw に degrade せず None (誤値で出品しない > 出品数)
        assert api.derive_rarity_ebay(CAT, "ZZZ") is None
        assert api.derive_rarity_ebay(CAT, "") is None
        assert api.derive_rarity_ebay(CAT, None) is None
        assert api.derive_rarity_ebay(CAT, "★") is None


def _specs(product_id: str) -> dict | None:
    db = sqlite3.connect(str(api._DB_PATH))
    row = db.execute("SELECT specs FROM products WHERE category = ? AND product_id = ?",
                     (CAT, product_id)).fetchone()
    db.close()
    return json.loads(row[0]) if row else None


class TestDbState:
    def test_no_star_left_in_rarity_ebay(self):
        db = sqlite3.connect(str(api._DB_PATH))
        rows = db.execute("SELECT specs FROM products WHERE category = ?", (CAT,)).fetchall()
        db.close()
        left = [json.loads(s or "{}").get("rarity_ebay") for (s,) in rows]
        assert [v for v in left if v and "★" in v] == []

    def test_harm_case_cert158452539_is_leader_with_alt_art(self):
        """実害カード: 'L★' → 記号除去で 'L' 1文字になり出品取り止めになった行."""
        specs = _specs("FB01-071_PARA")
        if specs is None:
            pytest.skip("FB01-071_PARA not in shared DB")
        assert specs["rarity_ebay"] == "Leader"
        assert "Alternative Art" in (specs.get("features") or [])
        # 公式 rarity (生値) は触らない = SSOT は公式のミラーのまま
        assert specs["rarity"] == "L★"

    def test_audit_reports_rarity_section(self):
        """set_name_integrity_audit §7 が rarity 生値焼き付きを毎日出す (0 でも出し続ける)."""
        sys.path.insert(0, str(_REPO / "tools"))
        import set_name_integrity_audit as audit_mod  # noqa: E402

        report = audit_mod.render(
            [], [], [], [], {}, {},
            {"dragonball_scg": {"raw_stamped": 0, "map_drift": 0}},
            ["dragonball_scg"],
        )
        assert "## 7." in report
        assert "raw_stamped" in report
        assert "| dragonball_scg | 0 | 0 |" in report

    def test_base_card_has_no_alt_art_feature(self):
        specs = _specs("FB01-071")
        if specs is None:
            pytest.skip("FB01-071 not in shared DB")
        assert specs["rarity_ebay"] == "Leader"
        assert "Alternative Art" not in (specs.get("features") or [])
