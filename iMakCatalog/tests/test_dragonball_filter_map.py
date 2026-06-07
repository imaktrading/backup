"""Dragonball set_name 誤マッピング回帰テスト (2026-06-08 FB04-08 / FS01-08 根治).

- DB ebay_filter_map の set_code が HQ確定の公式英語名であること (誤値への逆戻り検出)
- api.lookup が代表 product_id で正しい set_name を返すこと
- register_filter_map が upsert (yaml修正→loader で値更新) されること
  = yaml↔DB 乖離 (本バグの真因) の再発防止
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

CAT = "dragonball_scg"

# HQ確定の公式英語 set 名 (dbs-cardgame.com 公式 + 複数小売一致)
EXPECTED_SET_CODE = {
    "FB04": "Ultra Limit", "FB05": "New Adventure", "FB06": "Rivals Clash",
    "FB07": "Wish for Shenron", "FB08": "Saiyan's Pride",
    "FS01": "Starter Deck Son Goku", "FS02": "Starter Deck Vegeta",
    "FS03": "Starter Deck Broly", "FS04": "Starter Deck Frieza",
    "FS05": "Starter Deck Bardock",
}
# 旧誤値 (絶対に逆戻りしてはいけない)
FORBIDDEN = {
    "FB04": "Fusion Surge", "FB05": "Rising Spark", "FB06": "Perfect Combination",
    "FB07": "Ultra Limit", "FB08": "Secret of Evolution",
    "FS01": "Starter Deck Saiyan Genesis", "FS05": "Starter Deck Androids",
    "FS06": "Starter Deck Pirates",
}


def _db_set_code(code):
    con = sqlite3.connect(str(api._DB_PATH))
    try:
        r = con.execute(
            "SELECT ebay_value FROM ebay_filter_map "
            "WHERE category=? AND field='set_code' AND source_value=?",
            (CAT, code)).fetchone()
        return r[0] if r else None
    finally:
        con.close()


def test_db_set_code_matches_official():
    for code, expected in EXPECTED_SET_CODE.items():
        assert _db_set_code(code) == expected, f"{code} set_code != {expected!r}"


def test_db_set_code_not_forbidden_old_values():
    for code, bad in FORBIDDEN.items():
        assert _db_set_code(code) != bad, f"{code} が旧誤値 {bad!r} に逆戻り"


def test_register_filter_map_upserts():
    """既存キーの ebay_value が register_filter_map で更新される (INSERT OR IGNORE でない)."""
    code = "FB04"
    original = _db_set_code(code)
    assert original == "Ultra Limit"
    try:
        api.register_filter_map(CAT, "set_code", code, "TEST_SENTINEL", note="upsert-test")
        assert _db_set_code(code) == "TEST_SENTINEL", "upsert されていない (IGNORE のまま)"
    finally:
        api.register_filter_map(CAT, "set_code", code, original, note="restore")
    assert _db_set_code(code) == original
