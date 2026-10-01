# -*- coding: utf-8 -*-
"""ワンピの `language` は証拠 (絵の置き場) から決める — `en` は 0 で維持.

依頼: `requests/2026-10-01_onepiece_language_redecide_go.md` [IMPLEMENT-GO]

2026-10-01 実測: `en` 1,778行のうち **英語版の絵 (`card_image/OP-EN/`) を持つ行は 0**。
`en` は「英語版」ではなく「EN/JA 一覧の突き合わせの鍵が外れた」の意味になっていた。
出品くんの候補一覧が `en` を外すので、日本語版 1,778行が選択肢から消えていた。
"""
import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = "C:/dev/iMak_data/catalog/products.sqlite"
JA_IMG = "https://files.bandai-tcg-plus.com/card_image/OP-JA/OP06/OP06-022.png"
EN_IMG = "https://files.bandai-tcg-plus.com/card_image/OP-EN/OP06/OP06-022.png"
SITE = "https://www.onepiece-cardgame.com/images/cardlist/card/EB03-053_p2.png"


def _scraper():
    spec = importlib.util.spec_from_file_location(
        "_op", ROOT / "scrapers" / "one_piece_tcg.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _mig():
    spec = importlib.util.spec_from_file_location(
        "_lang", ROOT / "migrations" / "2026-10-01_onepiece_language_from_evidence.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# --- 取り込み側 (これから入る行) ---

def test_en_list_with_japanese_art_is_not_en():
    """★本件の core。英語版の一覧に在っても、絵が日本語版なら `en` にしない."""
    m = _scraper()
    assert m.detect_language({"x": 1}, None, image_url_en=JA_IMG) == "both"
    assert m.detect_language({"x": 1}, {"y": 1}, image_url_en=JA_IMG,
                             image_url_ja=JA_IMG) == "both"


def test_en_only_when_english_art_exists():
    m = _scraper()
    assert m.detect_language({"x": 1}, None, image_url_en=EN_IMG) == "en"
    assert m.detect_language({"x": 1}, {"y": 1}, image_url_en=EN_IMG,
                             image_url_ja=JA_IMG) == "both"


def test_ja_only_and_no_evidence():
    m = _scraper()
    assert m.detect_language(None, {"y": 1}, image_url_ja=JA_IMG) == "ja"
    assert m.detect_language(None, None) is None          # 証拠なし -> 空欄


# --- 決め直しの規則 (既に在る行) ---

def test_decide_keeps_hand_registered_japanese_rows():
    """集英社の付録・セブンイレブン等は絵が PSA 実写なので、出所で日本語版と分かる."""
    d = _mig().decide
    assert d("ja", "shueisha_chopper1_bundle+psa_cert168157614", []) == "ja"
    assert d("ja", "clone_ST13-003+psa_cert145597172_slab_confirmed", []) == "ja"
    assert d("ja", "admirable_collection_ac01_web_confirmed", []) == "ja"


def test_decide_moves_unfounded_en():
    d = _mig().decide
    assert d("en", "bandai_tcg_plus+opcg_official", [JA_IMG]) == "both"
    assert d("en", "bandai_tcg_plus", [SITE]) == "both"
    assert d("en", "bandai_tcg_plus", []) is None          # 証拠なし
    assert d("en", "bandai_tcg_plus", [EN_IMG]) == "en"    # 英語版の絵があれば en


# --- 本番データ ---

def test_no_en_rows_without_english_art():
    c = sqlite3.connect(DB, timeout=120)
    try:
        bad = []
        for pid, im in c.execute(
                "SELECT product_id, images FROM products "
                "WHERE category='one_piece_tcg' AND language='en'"):
            try:
                imgs = json.loads(im or "[]")
            except ValueError:
                imgs = []
            if not any(isinstance(u, str) and "card_image/OP-EN/" in u for u in imgs):
                bad.append(pid)
    finally:
        c.close()
    assert not bad, f"英語版の絵が無いのに en の行が {len(bad)}行: {bad[:5]}"


def test_listing_language_does_not_come_from_this_column():
    """出品の Language は `specs.language` から来る (この列は候補の絞り込み用).

    列を直しても出品CSV の中身が変わらないことを固定する。
    """
    import sys
    if str(ROOT.parent) not in sys.path:
        sys.path.insert(0, str(ROOT.parent))
    from iMakCatalog import api
    for pid in ("EB03-053_p2", "OP13-004_p1"):
        r = api.lookup("one_piece_tcg", pid)
        assert r, pid
        assert (r.get("specs") or {}).get("language") == "Japanese", pid
