"""公式サイズページから実寸を取る処理の回帰 (2026-09-14).

- 表が2つに分かれ、colspan で値がまとまっている形 (公式の実物 463102_size.html と同じ形)
- 同じサイズに違う値が2つ出るページは入れない (fail-closed)
- cm だけ保存し、換算した inch は size_chart_inch に入れない (窓口 2026-09-14)
- to_inch は cm/2.54 を 1/4 に四捨五入 (公式モーダルと 2,580/2,580 一致した規則)
- 実寸モーダルで cm に切り替わっていない (cm == inch) 時は cm を捨てる
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scrapers")]

import uniqlo_ut_sizepage as P  # noqa: E402

PAGE = """
<table><tr><th class="header01">サイズ</th><th>XS</th><th>S</th></tr>
<tr><th>身丈</th><td>63</td><td>65</td></tr>
<tr><th>肩幅</th><td>42</td><td>43.5</td></tr>
<tr><th>身幅</th><td>46</td><td>49</td></tr>
<tr><th>袖丈</th><td>40.5</td><td>42</td></tr></table>
<table><tr><th class="header01">サイズ</th><th>XXL</th><th>3XL</th></tr>
<tr><th>身丈</th><td colspan="2">76</td></tr>
<tr><th>肩幅</th><td>50.5</td><td>52.5</td></tr>
<tr><th>身幅</th><td>63</td><td>67</td></tr>
<tr><th>袖丈</th><td>48</td><td>49</td></tr></table>
<table><tr><th>サイズ</th><th>S</th></tr><tr><th>身長</th><td>160</td></tr></table>
"""


class TestSizePage(unittest.TestCase):
    def test_two_tables_and_colspan(self):
        rows = P.parse_size_page(PAGE)
        self.assertEqual([r["size"] for r in rows], ["XS", "S", "XXL", "3XL"])
        self.assertEqual(rows[2]["length"], "76")
        self.assertEqual(rows[3]["length"], "76")
        self.assertEqual(rows[1], {"size": "S", "length": "65", "shoulder": "43.5",
                                   "chest": "49", "sleeve": "42"})

    def test_conflicting_values_rejected(self):
        bad = PAGE + '<table><tr><th>サイズ</th><th>XS</th></tr><tr><th>身丈</th><td>99</td></tr></table>'
        self.assertIsNone(P.parse_size_page(bad))

    def test_no_table(self):
        self.assertIsNone(P.parse_size_page("<html><body>Access Denied</body></html>"))

    def test_to_inch_matches_official(self):
        # 公式モーダルの実物の組 (2026-09-14 DB から)
        for cm, inch in (("64", "25 1/4"), ("48", "19"), ("44.5", "17 1/2"), ("66", "26"),
                         ("49", "19 1/4"), ("45", "17 3/4"), ("59", "23 1/4")):
            self.assertEqual(P.to_inch(cm), inch)


class TestNoConvertedInchSaved(unittest.TestCase):
    def test_writer_does_not_set_size_chart_inch(self):
        src = (ROOT / "scrapers" / "uniqlo_ut_sizepage.py").read_text(encoding="utf-8")
        body = src.split("def main()")[1]
        self.assertNotIn('"size_chart_inch":', body)


class TestSizeChartCmGuard(unittest.TestCase):
    def test_cm_equal_inch_is_dropped(self):
        src = (ROOT / "scrapers" / "uniqlo_ut_sizechart.py").read_text(encoding="utf-8")
        self.assertIn('_click(d, "cm", exact=True)', src)
        self.assertIn("if cm and cm == inch:", src)


if __name__ == "__main__":
    unittest.main()
