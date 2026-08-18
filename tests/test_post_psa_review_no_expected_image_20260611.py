"""Regression: 2026-06-11 post_psa_review の no-expected 分岐でも PSA 実物画像を出す.

問題 (ユーザー「cert 77429277 等、元画像すらない。なんで?」):
  catalog 期待値特定不能 (no-expected) の cert は、_generate_html の else 分岐が
  警告文 + 候補のみ生成し、PSA cert 実物画像 (cert_image_url) を一切 <img> 出力して
  いなかった。期待値が分からない時こそ実物↔候補を見比べたいのに実物が消えていた
  (画像URL自体は psa_cache に在り HTTP 200 で生きている=表示漏れ)。

修正: no-expected 分岐にも cert_image_url があれば PSA 実物画像を出す。
"""
import importlib.util
import sqlite3
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
    conn.commit(); conn.close()
    return db


def _no_expected_target():
    return {
        "cert": "77429277",
        "brand": "POKEMON JAPANESE PROMO 25TH ANNIVERSARY",
        "subject": "SHINING MAGIKARP",
        "card_number": "010",
        "category": "pokemon_tcg",
        "set_code": None,
        "csv_expected": "",  # → no-expected 分岐
        "cert_image_url": "https://d1htnxwo4o0jhw.cloudfront.net/cert/143622156/small/x.jpg",
        "candidates": [],
    }


def test_no_expected_branch_shows_psa_cert_image(tmp_path):
    R = _load()
    R.CATALOG_DB = _make_db(tmp_path)
    R.HTML_OUTPUT = tmp_path / "out.html"
    t = _no_expected_target()
    R._generate_html([t])
    html = R.HTML_OUTPUT.read_text(encoding="utf-8")
    assert "no-expected" in html, "no-expected 分岐に入っていない"
    # 回帰の核: 実物画像 (cert_image_url) が <img> で出ていること
    assert R._img_url(t["cert_image_url"]) in html, "no-expected で PSA 実物画像が出ていない (退行)"
    # 2026-08-18: 見出しを列ごとに分けた (「📋 PSA 表」「📋 PSA 裏」)
    assert "PSA 表" in html


def test_no_expected_without_image_no_crash(tmp_path):
    """cert_image_url が空でも crash せず警告だけ出る (fail-safe)."""
    R = _load()
    R.CATALOG_DB = _make_db(tmp_path)
    R.HTML_OUTPUT = tmp_path / "out.html"
    t = _no_expected_target()
    t["cert_image_url"] = ""
    R._generate_html([t])
    html = R.HTML_OUTPUT.read_text(encoding="utf-8")
    assert "no-expected" in html
    assert "期待値特定不能" in html
