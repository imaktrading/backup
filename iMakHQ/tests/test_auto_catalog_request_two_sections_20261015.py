# -*- coding: utf-8 -*-
"""2026-10-15 残務 №545: プログラムが書くカタログ依頼にも2節 (既に判明 / 聞きたいこと) を入れる。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


def test_auto_request_has_two_sections_and_keeps_table(tmp_path):
    import auto_catalog_add_request as A
    p = tmp_path / "x.md"
    A._write_request(p, "one_piece_tcg", [{"model": "P-041 test", "detected_at": "2026-10-15"}])
    t = p.read_text(encoding="utf-8")
    assert "## 既に判明していること" in t and "## 聞きたいこと" in t
    assert t.index("既に判明") < t.index("| `P-041 test` |") < t.index("聞きたいこと")   # 表は既知の節に
