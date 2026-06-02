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

    def test_silver_8a(self):
        # 2026-05-13 事故ケース: 8A2 が "Black" になっていた → 修正で 'Orange' 採用
        # 2026-05-25 修正 (HQ 5/21 依頼): -8/-8A は Silver/Gray (旧 Orange は誤り).
        self.assertEqual(gshock.get_band_color_from_pid("DW-5600MNC-8A2JF"), "Silver")

    def test_red_4(self):
        self.assertEqual(gshock.get_band_color_from_pid("GA-2300FL-4AJF"), "Red")

    def test_yellow_9(self):
        self.assertEqual(gshock.get_band_color_from_pid("DW-5600GL-9JR"), "Yellow")

    def test_jr_jf_strip(self):
        # JF/JR suffix を剥がしても同結果
        self.assertEqual(gshock.get_band_color_from_pid("GA-2100-1A1JF"),
                         gshock.get_band_color_from_pid("GA-2100-1A1"))

    def test_red_6(self):
        # 2026-05-25 修正 (HQ 5/21 依頼): -6/-6A は Red (旧 Gold).
        # Casio 慣例で -6 系は Red/Orange、Gold ではない.
        self.assertEqual(gshock.get_band_color_from_pid("BA-110AH-6A"), "Red")

    def test_silver_8(self):
        # 2026-05-25 修正: -8/-8A は Silver/Gray (旧 Orange).
        self.assertEqual(gshock.get_band_color_from_pid("GD-B500S-8"), "Silver")

    def test_beige_5(self):
        # 2026-05-25 修正: -5/-5A は Beige (Sand/Tan/Khaki、旧 White).
        self.assertEqual(gshock.get_band_color_from_pid("GM-2100CL-5A"), "Beige")

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
        """heuristic 由来の entry のみ整合性 check.

        2026-05-13 改訂: band_color の優先順は 公式 > heuristic.
        2026-05-30 改訂: ShockBase / g-central / 公式 import で投入された entry は
          band_color_source 設定なしで公式 band_color 値 (= "Camouflage"/"Pink"/
          "Transparent" 等)、 heuristic との乖離は正常。 entry の `source` 列で
          公式系 (= shockbase / g-central / casio_official) 判定して skip。
        """
        OFFICIAL_ENTRY_SOURCES = {
            "shockbase", "casio_official", "casio_official_spec",
            "casio_official_categorized", "g-central+casiofanmag",
        }
        conn = sqlite3.connect(str(api._DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT product_id, source, specs FROM products WHERE category='gshock'")
        mismatches = []
        for pid, entry_source, specs_json in cur.fetchall():
            specs = json.loads(specs_json) if specs_json else {}
            cat_color = (specs.get("band_color") or "").strip()
            src = specs.get("band_color_source")
            if src == "hq_confirmed":
                continue
            # 公式系 entry (= ShockBase / g-central / casio 公式) は band_color 公式値、 skip
            entry_src = (entry_source or "").lower()
            if any(off in entry_src for off in ("shockbase", "g-central", "casio_official")):
                continue
            inferred = gshock.get_band_color_from_pid(pid)
            if not inferred:
                continue
            if cat_color and cat_color != inferred:
                mismatches.append((pid, cat_color, inferred, src))
        conn.close()
        if mismatches:
            msg = "heuristic-source band_color mismatches:\n"
            for pid, cur_c, exp, src in mismatches:
                msg += f"  {pid}: catalog={cur_c!r} != inferred={exp!r} (source={src!r})\n"
            self.fail(msg)


if __name__ == "__main__":
    unittest.main()
