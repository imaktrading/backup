"""Regression: 2026-06-08 post_psa_review の候補HTMLが character 名で候補を出せる.

問題 (ユーザー「HTMLに候補が表示されないと意味ない。なんで出ない?」):
  _get_candidates は set_code(brand正規表現) / expected_product_id / 全件 でしか引かず、
  character 名(subject)を使っていなかった。set_code抽出失敗 + lookup miss の One Piece Sabo は、
  catalog に OP10-049 Sabo が在っても候補に出ず (全件先頭30=無関係)、HTMLが目的を果たせなかった。

修正: subject + card_number を _get_candidates に渡し、miss時 (expected無し) は
  name_en LIKE %character% AND product_id LIKE %-NNN で pinpoint → キャラ候補を先頭に。
"""
import importlib.util
import sqlite3
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"


def _load():
    spec = importlib.util.spec_from_file_location("post_psa_review", str(_TOOLS / "post_psa_review.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _make_db(tmp_path):
    db = tmp_path / "cat.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE products (category TEXT, product_id TEXT, name_en TEXT, images TEXT)")
    rows = [
        ("one_piece_tcg", "OP10-049", "Sabo", '["http://x/op10-049.png"]'),
        ("one_piece_tcg", "OP03-001", "Sabo", '["http://x/op03-001.png"]'),
        ("one_piece_tcg", "DON-BASIC-001", "DON!! Card", '["http://x/don.png"]'),
        ("one_piece_tcg", "OP01-001", "Monkey.D.Luffy", '["http://x/luffy.png"]'),
    ]
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)", rows)
    conn.commit(); conn.close()
    return db


def test_character_candidate_surfaces_on_miss(tmp_path):
    R = _load()
    R.CATALOG_DB = _make_db(tmp_path)
    # miss: set_code無し / expected無し / subject=Sabo / card_number=049
    cands = R._get_candidates("one_piece_tcg", None, "049",
                              brand="ONE PIECE", expected_product_id=None, subject="Sabo")
    pids = [c[0] for c in cands]
    assert pids and pids[0] == "OP10-049", f"Sabo #049 が先頭に出ない: {pids[:5]}"


def test_character_only_when_no_number(tmp_path):
    R = _load()
    R.CATALOG_DB = _make_db(tmp_path)
    cands = [c[0] for c in R._get_candidates("one_piece_tcg", None, "",
             brand="ONE PIECE", expected_product_id=None, subject="Sabo")]
    assert "OP10-049" in cands and "OP03-001" in cands   # Sabo 両方出る
    assert "OP01-001" not in cands                        # 別キャラ(Luffy)は出ない


def test_no_subject_no_character_search(tmp_path):
    R = _load()
    R.CATALOG_DB = _make_db(tmp_path)
    # subject無し → character検索しない (従来挙動: 全件safety net)
    cands = [c[0] for c in R._get_candidates("one_piece_tcg", None, "049",
             brand="ONE PIECE", expected_product_id=None, subject="")]
    assert cands  # safety net で何かは出る
    assert cands[0] != "OP10-049"  # character pinpoint はしていない
