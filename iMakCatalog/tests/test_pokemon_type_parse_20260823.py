# -*- coding: utf-8 -*-
"""ポケモンのタイプ判定 (2026-08-23 の取り違え再発防止).

事故: `type_en` に Lightning / Darkness / Metal / Colorless が1件も無く、
      ピカチュウ 6,138枚が 'Fighting' になっていた。原因は2つ:
      ① 公式のクラス名は electric / dark / steel / none (lightning 等ではない)
      ② HTML 全体から最初のアイコンを採っていたので **弱点**を拾っていた
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
from pokemon_tcg import _parse_detail_html, _TYPE_CLASS_TO_EN  # noqa: E402

HTML_PIKACHU = (
    '<h1 class="Heading1 mt20">ピカチュウ</h1>'
    '<div class="td-r"><span class="hp">HP</span><span class="hp-num">70</span>'
    '<span class="hp-type">タイプ</span><span class="icon-electric icon"></span></div>'
    '<h2>ワザ</h2><h4><span class="icon-electric icon"></span>でんじスパーク</h4>'
    '<th>弱点</th><td><span class="icon-fighting icon"></span>×2</td>'
)
HTML_TRAINER = '<h1 class="Heading1 mt20">ハイパーボール</h1><h2>ルール</h2><th>弱点</th><td><span class="icon-fighting icon"></span></td>'


class TestTypeParse(unittest.TestCase):
    def test_reads_type_field_not_weakness(self):
        """タイプ欄から読む (弱点の闘を拾わない)."""
        out = _parse_detail_html(HTML_PIKACHU, "1")
        self.assertEqual(out.get("type_en"), "Lightning")
        self.assertEqual(out.get("type_jp"), "雷")

    def test_no_type_field_stays_empty(self):
        """タイプ欄が無いカード (トレーナーズ等) は空のまま."""
        out = _parse_detail_html(HTML_TRAINER, "2")
        self.assertIsNone(out.get("type_en"))

    def test_class_map_covers_official_names(self):
        """公式のクラス名 11種を網羅している."""
        for k in ("grass", "fire", "water", "electric", "psychic", "fighting",
                  "dark", "steel", "dragon", "fairy", "none"):
            self.assertIn(k, _TYPE_CLASS_TO_EN)

    def test_db_has_all_eleven_types(self):
        """DB に 11タイプすべて在る (欠けていたら取り違えのサイン)."""
        db = sqlite3.connect(str(api._DB_PATH))
        try:
            seen = set()
            for (sp,) in db.execute("SELECT specs FROM products WHERE category='pokemon_tcg' "
                                    "AND json_extract(specs,'$.type_en') IS NOT NULL"):
                seen.add(json.loads(sp)["type_en"])
        finally:
            db.close()
        self.assertEqual(set(_TYPE_CLASS_TO_EN.values()) - seen, set())


if __name__ == "__main__":
    unittest.main()
