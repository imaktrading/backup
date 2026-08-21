# -*- coding: utf-8 -*-
"""psa_preflight の scope 判定を tcg_scope 1本に委譲した回帰テスト (2026-08-21).

回答書: `2026-08-19_psa_preflight_scope_ssot_gap_response.md`

何が起きていたか:
    2026-08-11 に「枠を食う前に落とす」で preflight を前段へ移した結果、
    SSOT (`tcg_scope`) を通らないまま OUT-OF-SCOPE / GAP が確定するようになっていた。
    preflight は `out_of_scope_by_brand` という **二つ目の真理表** を持っており、
    tcg_scope の8本のうち DIVERS / ITAJAGA / FAMILY POKEMON / ウエハース / Web期 の
    5本が欠けていた。そのためウエハースは毎日 `GAP`(catalog未収録) として落ち、
    カタログへ誤依頼が出続けていた。

ここで固定すること:
  1. 依頼書の8件が OUT-OF-SCOPE になる (誤カタログ依頼と目視枠の浪費が止まる)
  2. **逆方向**: preflight にしか無かった Neo 期が対象内へ戻らない
     (片側だけ見て委譲すると、真理表を1本にするつもりで穴が開く)
  3. 真理表が2本に戻っていない (`out_of_scope_by_brand` が復活していない)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import psa_preflight as P  # noqa: E402


def oos(brand):
    """preflight が実際に使う scope 判定 (= tcg_scope 1本)。理由文字列 or None。"""
    fired, why = P.is_out_of_scope(P.detect_franchise_from_brand(brand), brand)
    return why if fired else None


# 依頼書 2026-08-19_psa_preflight_scope_ssot_gap.md の実測 8件。
# (cert, brand, 委譲前の preflight ラベル)
GAP_BEFORE = [
    ("146117881", "ONE PIECE WAFERS JAPANESE 20TH ANNIVERSARY", "GAP"),
    ("152136358", "POKEMON JAPANESE WEB", "GAP"),
    ("158452571", "DRAGON BALL SUPER DIVERS 4", "REVIEW"),
    ("163045378", "DRAGON BALL SUPER DIVERS ADVANCE PACK DRAGON BALL 40TH ANNIVERSARY EDITION",
     "REVIEW"),
    ("142931324", "POKEMON JAPANESE SWORD & SHIELD FAMILY POKEMON CARD GAME", "RESOLVED"),
    ("158452535", "ITAJAGA DRAGON BALL VOL.7", "OUT-OF-SCOPE"),
    ("158452537", "ITAJAGA DRAGON BALL VOL.8", "OUT-OF-SCOPE"),
    ("158452575", "DRAGON BALL SUPER DIVERS 7", "OUT-OF-SCOPE"),
]


class TestGapCertsAreNowOutOfScope:
    def test_all_eight_are_out_of_scope(self):
        for cert, brand, before in GAP_BEFORE:
            assert oos(brand), f"{cert} ({before}) を対象外にできていない: {brand}"

    def test_classify_labels_them_out_of_scope(self):
        """台帳 (psa_out_of_scope.json) に頼らず、**規則だけ**で OUT-OF-SCOPE になること。

        台帳に無い5件を、台帳に載っていない cert 番号で classify にかける。
        ここが GAP のままだと、また毎日カタログへ誤依頼が出る。
        """
        for cert, brand, before in GAP_BEFORE:
            if before == "OUT-OF-SCOPE":
                continue                      # 台帳で個別に救済済 = 規則の検査にならない
            res = P.classify("_test_" + cert, {"Brand": brand}, None)
            assert res["status"] == "OUT-OF-SCOPE", f"{cert}: {res['status']} ({brand})"
            assert res["reason"]


class TestReverseDirection:
    """★逆方向。preflight にしか無かったものが、委譲で静かに対象内へ戻らないこと。"""

    def test_pokemon_neo_stays_out_of_scope(self):
        """`157799487 POKEMON JAPANESE NEO`。Neo 期を tcg_scope へ移すまでは戻っていた。"""
        why = oos("POKEMON JAPANESE NEO")
        assert why and "Neo" in why
        res = P.classify("_test_157799487", {"Brand": "POKEMON JAPANESE NEO"}, None)
        assert res["status"] == "OUT-OF-SCOPE"

    def test_neo_is_a_word_not_a_substring(self):
        assert oos("POKEMON JAPANESE NEON GENESIS") is None

    def test_sdbh_stays_out_of_scope(self):
        """`HEROES` が `DRAGON BALL` と離れて出る PSA 表記も落ちること。

        `DRAGON BALL SON GOKU HEROES UGM5` は detect_franchise_from_brand が
        "Dragon Ball" を返すので、franchise だけ見ていると素通りする。
        """
        for b in ("DRAGON BALL SON GOKU HEROES UGM5",
                  "SUPER DRAGON BALL HEROES METEOR MISSION 2",
                  "SUPER DRAGON BALL HEROES ULTRA GOD MISSION 5"):
            assert oos(b), f"SDBH を落とせていない: {b}"

    def test_fusion_world_is_not_caught(self):
        """誤爆したら出品できるカードを捨てることになる (psa cache 1,144件で実測0件)。"""
        for b in ("DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE ENERGY MARKER PACK 0",
                  "DRAGON BALL SUPER FUSION WORLD JAPANESE MANGA BOOSTER 02",
                  "DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE BLAZING AURA"):
            assert oos(b) is None, f"Fusion World を誤って落とした: {b}"


class TestSingleTruthTable:
    def test_out_of_scope_by_brand_is_gone(self):
        """真理表を2本に戻さない。増やすと同じ事故 (片方だけ直る) が起きる。"""
        assert not hasattr(P, "out_of_scope_by_brand"), \
            "psa_preflight に2つ目の scope 真理表が復活している"

    def test_preflight_uses_tcg_scope(self):
        import tcg_scope
        assert P.is_out_of_scope is tcg_scope.is_out_of_scope
        assert P.detect_franchise_from_brand is tcg_scope.detect_franchise_from_brand
