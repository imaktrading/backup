# -*- coding: utf-8 -*-
"""PB01 (プレミアムグッズセット ガンダムW) は公式の行 (画像つき) を返す.

依頼: `requests/2026-09-30_gundam_pb01_resolver_returns_imageless_clone.md`
2026-07 に作った画像なしの複製行 `*_PB01` を返していたため、出品くんが毎回
NO-IMAGE で落としていた (4日/6回)。公式の入手情報を取り直して `_p4` が正と確かめた。
"""
import pytest

from iMakCatalog.integrations.psa_to_csv import lookup_gundam

BRAND = "GUNDAM JAPANESE PB01-PREMIUM GOODS SET -MOBILE SUIT GUNDAM WING-"
CASES = [("010", "HEERO YUY", "ST02-010_p4"), ("100", "A SHOW OF RESOLVE", "GD01-100_p4")]


@pytest.mark.parametrize("number,subject,expect_setname_has", CASES)
def test_pb01_hits_official_row_with_images(number, subject, expect_setname_has):
    rec = lookup_gundam(BRAND, number, subject=subject, verbose=False)
    assert rec is not None, f"PB01 #{number} が引けない"
    assert "[PB01]" in (rec.get("set_name_official") or ""), rec.get("set_name_official")
    assert rec.get("images"), f"画像なしの行を返している ({expect_setname_has} が正)"


def test_imageless_clone_rows_are_gone():
    from iMakCatalog import api
    for pid in ("ST02-010_PB01", "GD01-100_PB01"):
        assert api.lookup("gundam_tcg", pid) is None, f"{pid} が残っている"
