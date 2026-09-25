# -*- coding: utf-8 -*-
"""券面番号の正のキーは `card_number_text` (2026-09-26 確定).

依頼 `2026-09-25_promo_ingest_card_number_text_missing.md`:
出品くん・テストが読むのは `card_number_text`。取り込みが `card_number` の名前で書くと、
その行だけカード番号が空で出品される (2026-06-21 に一度直し、2026-09-05 に 50件 再発)。

**別名 `card_number` は持たない**。同じ値を2つの名前で持つと、また片方だけ直す事故が起きる。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api  # noqa: E402

CATS = ("one_piece_tcg", "dragonball_scg", "gundam_tcg", "pokemon_tcg")


def test_no_card_number_alias():
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    bad = [(c, p) for c, p in db.execute(
        "SELECT category, product_id FROM products "
        "WHERE json_extract(specs,'$.card_number') IS NOT NULL")]
    db.close()
    assert bad == [], f"別名 card_number を持つ行: {len(bad)}件 {bad[:5]}"


def test_promo_ingest_rows_have_card_number_text():
    """プロモ取り込みの行は券面番号を持つ (公式ページに番号が載っている行だけが対象).

    ★catalog 全体には `card_number_text` が空で正しい行が 698件ある
      (公式が印刷番号を打っていないカード。2026-08-22 ユーザー確定)。
      ここで見るのは **公式ページから写して入れた行**だけ。
    """
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    bad = [(p, s) for p, s in db.execute(
        "SELECT product_id, source FROM products "
        "WHERE source LIKE 'opcg_official_promo%' "
        "AND json_extract(specs,'$.card_number_text') IS NULL")]
    db.close()
    assert bad == [], f"プロモ取り込みで card_number_text が無い行: {len(bad)}件 {bad[:5]}"
