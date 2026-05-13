"""G-shock band_color 整合性 test.

カタログ DB の band_color が model number suffix から導かれる正解値と一致する
ことを保証. 2026-05-13 17 件誤登録事故の再発防止.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

# scrapers/gshock の get_band_color_from_pid を import
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scrapers"))

from scrapers import gshock  # type: ignore  # noqa: E402
import api  # type: ignore  # noqa: E402


class TestGetBandColorFromPid(unittest.TestCase):
    """get_band_color_from_pid の pure 関数テスト."""

    def test_basic_black(self):
        self.assertEqual(gshock.get_band_color_from_pid("GA-2100-1A1JF"), "Black")

    def test_white_7a(self):
        # 2026-05-13 事故ケース: 7A7 が "Black" になっていた
        self.assertEqual(gshock.get_band_color_from_pid("GA-2100-7A7JF"), "White")
        self.assertEqual(gshock.get_band_color_from_pid("GA-2100BM-7A2JF"), "White")
        self.assertEqual(gshock.get_band_color_from_pid("BA-110X-7A1"), "White")

    def test_orange_8a(self):
        # 2026-05-13 事故ケース: 8A2 が "Black" になっていた
        self.assertEqual(gshock.get_band_color_from_pid("DW-5600MNC-8A2JF"), "Orange")

    def test_red_4(self):
        self.assertEqual(gshock.get_band_color_from_pid("GA-2300FL-4AJF"), "Red")

    def test_yellow_9(self):
        self.assertEqual(gshock.get_band_color_from_pid("DW-5600GL-9JR"), "Yellow")

    def test_jr_jf_strip(self):
        # JF/JR suffix を剥がしても同結果
        self.assertEqual(gshock.get_band_color_from_pid("GA-2100-1A1JF"),
                         gshock.get_band_color_from_pid("GA-2100-1A1"))

    def test_gold_6(self):
        # CASIO 公式 convention: 6 = Gold
        self.assertEqual(gshock.get_band_color_from_pid("BA-110AH-6A"), "Gold")

    def test_unknown_returns_empty(self):
        # 未知 suffix は空 (Black fallback 廃止 = precision 優先)
        self.assertEqual(gshock.get_band_color_from_pid("INVALID-XYZ"), "")
        self.assertEqual(gshock.get_band_color_from_pid(""), "")


class TestCatalogBandColorIntegrity(unittest.TestCase):
    """catalog DB 内の band_color が model number suffix と矛盾しないか.

    2026-05-13 事故 (17 件 'Black' 誤登録) の再発防止. 全 G-shock entry を走査して
    band_color と get_band_color_from_pid(pid) の不一致をフラグ.
    """

    def test_all_band_colors_consistent(self):
        conn = sqlite3.connect(str(api._DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT product_id, specs FROM products WHERE category='gshock'")
        mismatches = []
        for pid, specs_json in cur.fetchall():
            specs = json.loads(specs_json) if specs_json else {}
            cat_color = (specs.get("band_color") or "").strip()
            inferred = gshock.get_band_color_from_pid(pid)
            if not inferred:
                continue  # suffix 解析不能なものは skip
            if cat_color and cat_color != inferred:
                mismatches.append((pid, cat_color, inferred))
        conn.close()
        if mismatches:
            msg = "band_color mismatches:\n"
            for pid, cur_c, exp in mismatches:
                msg += f"  {pid}: catalog={cur_c!r} != inferred={exp!r}\n"
            self.fail(msg)


if __name__ == "__main__":
    unittest.main()
