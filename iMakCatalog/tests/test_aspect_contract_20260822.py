# -*- coding: utf-8 -*-
"""決定表 (_contract_aspects.yaml) が壊れていないこと.

この表が唯一の口。壊れると「その都度判断」に逆戻りするので回帰で守る。
"""
import json
import sqlite3
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "ebay_filter_map" / "_contract_aspects.yaml"
MASTER = Path(r"C:\dev\iMak_data\catalog\_input\ebay_aspects_183454_latest.json")


class TestAspectContract(unittest.TestCase):
    def setUp(self):
        self.doc = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["aspects"]

    def test_covers_all_ebay_aspects(self):
        """eBay の全項目が表に載っている (載っていない = 判断の余地が残る)."""
        master = set(json.loads(MASTER.read_text(encoding="utf-8"))["aspects"])
        listed = {a["ebay_aspect"] for a in self.doc}
        self.assertEqual(master - listed, set(), "決定表に無い eBay 項目がある")

    def test_emit_true_has_source(self):
        """出すと決めた項目には出どころがある (空欄の出しっぱなしを防ぐ)."""
        for a in self.doc:
            if a["emit"]:
                self.assertTrue(a["source"], f"{a['ebay_aspect']}: emit なのに source が無い")

    def test_emit_false_has_reason(self):
        """出さないと決めた項目には理由がある (蒸し返し防止)."""
        for a in self.doc:
            if not a["emit"]:
                self.assertTrue(a.get("reason"), f"{a['ebay_aspect']}: 出さない理由が無い")

    def test_catalog_sources_exist_in_db(self):
        """catalog 管轄の source が実際に DB に在るキーであること."""
        db = sqlite3.connect(r"C:/dev/iMak_data/catalog/products.sqlite")
        try:
            for a in self.doc:
                src = a["source"]
                if not (a["emit"] and a["owner"] == "catalog" and src
                        and src.startswith("specs.")):
                    continue
                key = src.split(".", 1)[1]
                n = db.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM products "
                    "WHERE json_extract(specs, '$.' || ?) IS NOT NULL LIMIT 1)",
                    (key,)).fetchone()[0]
                self.assertTrue(n, f"{a['ebay_aspect']}: {src} を持つ行が1件も無い")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
