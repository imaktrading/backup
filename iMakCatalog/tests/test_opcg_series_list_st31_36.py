"""OPCG 公式 SERIES_LIST に ST-31〜36 (550031〜550036) が入っていることの回帰 test.

依頼: requests/2026-08-01_fix_catalog_data_only_BC_response.md §B-1
判定: ① 誤 (公式90枚に対し catalog 30枚しか入っていなかった) → SERIES_LIST を直す = GO

未発売 series (550037 / 550117 / 550118 / 550205 = 空ページ 45710 bytes / cards=0) は
足さない。ここも回帰で担保する。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))

from iMakCatalog.scrapers import _opcg_official_local_fetch as fetcher  # noqa: E402


class TestSeriesListSt31to36(unittest.TestCase):
    def setUp(self):
        self.ids = {sid for sid, _ in fetcher.SERIES_LIST}

    def test_new_st31_to_36_present(self):
        for sid in ("550031", "550032", "550033", "550034", "550035", "550036"):
            self.assertIn(sid, self.ids, f"{sid} が SERIES_LIST に無い")

    def test_st_range_is_1_to_36_inclusive(self):
        # スタートデッキ ST-01 〜 ST-36 が漏れなく (30 枚 → 36 枚)
        st_ids = [f"5500{n:02d}" for n in range(1, 37)]
        for sid in st_ids:
            self.assertIn(sid, self.ids, f"ST id {sid} 欠落")

    def test_unreleased_series_not_included(self):
        # 空ページを返す未発売 series は追加しない (窓口 §B-1 の生存確認署名)
        for sid in ("550037", "550117", "550118", "550205"):
            self.assertNotIn(sid, self.ids, f"{sid} は未発売のため入れてはいけない")

    def test_total_series_count_is_61(self):
        # 3 (限定/promo/family) + 2 (PRB) + 4 (EB) + 16 (OP) + 36 (ST) = 61
        self.assertEqual(len(fetcher.SERIES_LIST), 61)
        # 重複 id 無し
        self.assertEqual(len(self.ids), len(fetcher.SERIES_LIST))


if __name__ == "__main__":
    unittest.main()
