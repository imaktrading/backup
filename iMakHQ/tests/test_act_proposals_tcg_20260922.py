"""Act 提案 (hq/requests/2026-09-21_act_code_proposals_tcg.md) 2・3 の回帰。"""
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakTCG")
SRC = lambda n: open(os.path.join(ROOT, n), encoding="utf-8").read()  # noqa: E731


def test_blank_name_en_gets_its_own_reason():
    s = SRC("tcg_listing_fields.py")
    assert "は catalog の name_en が空" in s
    assert s.index("は catalog の name_en が空") < s.index("の名前が PSA Subject と不一致")


def test_non_psa10_is_not_counted_as_failure():
    s = SRC("psa_to_csv.py")
    assert "GRADE_EXCLUDED = set()" in s
    assert "GRADE_EXCLUDED.add(str(cert_number))" in s
    i = s.index("if str(cert) in GRADE_EXCLUDED:")
    assert i < s.index('print(f"    ⚠️ Skipping #{cert}: selfcheck failed in build_row")')
