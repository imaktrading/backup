"""Step2 回帰: lookup_one_piece promo scoring の brand-class bug 修正アンカー.

HQ提供3ケース (requests/2026-06-09_..._HQ_repro_cases.md):
  A Chopper(誤マッチ): 'PREMIUM CARD COLLECTION'(generic) で EB01-006_P_treasure を
     誤選択しない (cross-set Memorial promo を原典ST01より上位にしない)。
  B Marco(取れない誤り): 'ONE PIECE JAPANESE PROMOS' #002 → OP08-002_P_LF を拾う。
  C Sabo(正例・壊さない): BEST SELECTION VOL.4 → OP10-049_p1。
共通方針: 誤variant=誤出品直結。判別不能/tie は None(fail-closed)、推測で当てない。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import psa_to_csv as P  # noqa: E402


def _pid(card_no, subject, brand):
    r = P._search_one_piece_promo_by_number(card_no, subject, brand=brand, verbose=False)
    return r["product_id"] if r else None


def test_caseA_chopper_never_mispicks_eb01_memorial():
    # 誤マッチアンカー: generic 'PREMIUM CARD COLLECTION' で EB01-006_P_treasure を選ばない
    pid = _pid("006", "TONY TONY CHOPPER", "ONE PIECE JAPANESE PREMIUM CARD COLLECTION")
    assert pid != "EB01-006_P_treasure", "cross-set Memorial promo を誤選択"
    # 拾えた場合は原典 ST01-006 系であること (EB01等 別setでない)。tie→None も許容(fail-closed)
    assert pid is None or pid.startswith("ST01-006"), pid


def test_caseB_marco_promos_resolves_op08_lf():
    assert _pid("002", "MARCO WEEKLY SHONEN JUMP-#8",
                "ONE PIECE JAPANESE PROMOS") == "OP08-002_P_LF"


def test_caseC_sabo_best_selection_unchanged():
    assert _pid("049", "SABO",
                "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-"
                ) == "OP10-049_p1"
