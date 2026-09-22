# -*- coding: utf-8 -*-
"""目視画面に出す絵 (images[0]) が、埋め込みを断る公式サイトの URL になっていない (2026-09-22).

onepiece-cardgame.com / gundam-gcg.com は CORP same-site で画面に出ない。
控え (`tools/mirror_blocked_images.py`) を先頭に置く。月次でも走る。
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api  # noqa: E402


def test_first_image_is_displayable():
    db = sqlite3.connect(str(api._DB_PATH))
    bad = [pid for pid, im in db.execute("SELECT product_id, images FROM products")
           if (L := json.loads(im or "[]")) and api._is_blocked_host(L[0])]
    db.close()
    assert bad == [], f"先頭が画面に出せない公式 URL: {len(bad)}行 {bad[:5]}"
