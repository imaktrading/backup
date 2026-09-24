# -*- coding: utf-8 -*-
"""specs / images が JSON として読めること (2026-09-24).

1バイト化け (`"` が `*` や 0x02 に) が 5行で起きていて、その category を見る監査・テストが
丸ごと落ちた (14件)。件数が少なく気づきにくいので、常設で見る。
直し方: migrations/2026-09-24_fix_corrupt_{image,specs}_bytes.py
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api  # noqa: E402


def test_specs_and_images_are_valid_json():
    db = sqlite3.connect(str(api._DB_PATH))
    db.text_factory = bytes
    bad = []
    for pid, sp, im in db.execute("SELECT product_id, specs, images FROM products"):
        for col, v in (("specs", sp), ("images", im)):
            if v is None:
                continue
            try:
                json.loads(v.decode("utf-8"))
            except Exception as e:
                bad.append((pid.decode("utf-8", "replace"), col, str(e)[:40]))
    db.close()
    assert bad == [], f"JSON として読めない行: {len(bad)}件 {bad[:5]}"
