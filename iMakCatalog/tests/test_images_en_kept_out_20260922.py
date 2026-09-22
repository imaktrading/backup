# -*- coding: utf-8 -*-
"""英語版の絵は images に入れず specs.images_en に保有する (2026-09-22 ユーザー確定)."""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api  # noqa: E402


def test_no_english_image_in_images():
    db = sqlite3.connect(str(api._DB_PATH))
    bad = [pid for pid, im in db.execute(
        "SELECT product_id, images FROM products WHERE category IN "
        "('one_piece_tcg','dragonball_scg','gundam_tcg')")
        if any(k in u for u in json.loads(im or "[]") for k in api._EN_IMAGE_MARKS)]
    db.close()
    assert bad == [], f"images に英語版の絵: {len(bad)}行 {bad[:5]}"


def test_upsert_moves_english_images_to_specs(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_DB_PATH", tmp_path / "t.sqlite")  # 空の DB に schema.sql から作る
    api.upsert("one_piece_tcg", "X-1", "n", {},
               images=["https://files.bandai-tcg-plus.com/card_image/OP-EN/P/a.png",
                       "https://files.bandai-tcg-plus.com/card_image/OP-JA/P/a.png"])
    r = api.lookup("one_piece_tcg", "X-1")
    assert r["images"] == ["https://files.bandai-tcg-plus.com/card_image/OP-JA/P/a.png"]
    assert r["specs"]["images_en"] == ["https://files.bandai-tcg-plus.com/card_image/OP-EN/P/a.png"]
