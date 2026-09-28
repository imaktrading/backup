# -*- coding: utf-8 -*-
"""PSA の Variety が `RARE+` ならガンダムのパラレル行を返す (2026-09-28).

実害: cert151333415 (GD02-094 ガロード・ラン&ティファ・アディール) は現物がパラレル
(アイスの絵) なのに、通常版 (紫の絵) の行を返していた。
パラレルかどうかは **PSA の `Variety/Pedigree` 欄にしか出ない** (Subject にも Brand にも無い)。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from integrations import psa_to_csv as P  # noqa: E402

BRAND, NUM, SUBJ = "2025 GUNDAM JAPANESE DUAL IMPACT", "094", "GARROD RAN/TIFFA ADILL"


def _has(pid: str) -> bool:
    import api
    return api.lookup("gundam_tcg", pid) is not None


@pytest.mark.skipif(not _has("GD02-094_para"), reason="GD02-094_para が catalog に無い")
def test_variety_rare_plus_picks_parallel():
    r = P.lookup_gundam(BRAND, NUM, SUBJ, verbose=False, variety="RARE+")
    assert r and r["card_id"] == "GD02-094_para"


@pytest.mark.skipif(not _has("GD02-094"), reason="GD02-094 が catalog に無い")
def test_without_variety_keeps_base():
    """欄を渡さなければ従来どおり (呼び出し側が未対応でも壊さない)."""
    r = P.lookup_gundam(BRAND, NUM, SUBJ, verbose=False)
    assert r and r["card_id"] == "GD02-094"
