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


def test_caseA_chopper_real_brand_resolves_p1():
    # HQ実機確定(2026-06-10): 実 brand に 25TH ANNIVERSARY → ST01-006_p1(25周年エディション)に一意解決
    pid = _pid("006", "TONY TONY CHOPPER",
               "ONE PIECE JAPANESE 25TH ANNIVERSARY PREMIUM CARD COLLECTION")
    assert pid == "ST01-006_p1", pid


def test_caseA_chopper_generic_brand_failclosed():
    # edition句無しの generic brand → 判別不能(ST01-006_P vs _P_p) → None(fail-closed)。EB01は選ばない
    pid = _pid("006", "TONY TONY CHOPPER", "ONE PIECE JAPANESE PREMIUM CARD COLLECTION")
    assert pid != "EB01-006_P_treasure", "cross-set Memorial promo を誤選択"
    assert pid is None or pid.startswith("ST01-006"), pid


def test_caseA_edition_no_overfire_to_other_edition():
    # 暴発防止: 25TH brand が別edition _p4(FILM RED) を誤選択しない
    pid = _pid("006", "TONY TONY CHOPPER",
               "ONE PIECE JAPANESE 25TH ANNIVERSARY PREMIUM CARD COLLECTION")
    assert pid != "ST01-006_p4", "別edition(FILM RED)に暴発"


def test_caseB_marco_promos_resolves_op08_lf():
    assert _pid("002", "MARCO WEEKLY SHONEN JUMP-#8",
                "ONE PIECE JAPANESE PROMOS") == "OP08-002_P_LF"


def test_caseC_sabo_best_selection_unchanged():
    assert _pid("049", "SABO",
                "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-"
                ) == "OP10-049_p1"


def test_anniversary_set_edition_resolves_p4():
    # 2026-07-02 (cert84400496): '1ST ANNIVERSARY SET' [OTAMA] #006 → OP01-006_p4.
    # 汎用promo(OP01-006_P 'Promotion Card' score150 同点)に沈まず、ordinal一致で一意化。
    assert _pid("006", "OTAMA", "ONE PIECE JAPANESE 1ST ANNIVERSARY SET") == "OP01-006_p4"


def test_anniversary_ordinal_no_overfire():
    # 暴発防止: ordinal番号一致必須。'2ND ANNIVERSARY' brand は 1st ANNIVERSARY set(_p4)を選ばない。
    pid = _pid("006", "OTAMA", "ONE PIECE JAPANESE 2ND ANNIVERSARY SET")
    assert pid != "OP01-006_p4", "別ordinal(2nd)が1st edition(_p4)に暴発"
