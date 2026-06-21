"""Regression: 2026-06-21 — Tシャツ出品の3バグ是正(価格と無関係の壊れ).

① タイトル 'Japan New' が80字制限で 'Ja New' に語の途中で割れる(listing_common._truncate_at_word)。
② mercari webp 画像を image/jpeg 固定で送り Claude API 400拒否→生成失敗(_detect_media_type)。
③ Claude応答の JSON 後に説明文が付くと json.loads が 'Extra data' で失敗→生成失敗(_parse_json_lenient)。
"""
import base64
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_API = _ROOT / "iMakeBayAPI"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


# ---- ① 語境界トランケート(listing_common) ----
def test_truncate_at_word_no_midword():
    from listing_common import _truncate_at_word
    s = "UNIQLO UT One Piece 25th Luffy Gear Second T-Shirt Black US L (JP XL) NWT Japan New"
    out = _truncate_at_word(s, 80)
    assert len(out) <= 80
    assert "Ja New" not in out and not out.endswith("Ja")   # 'Japan' を割らない
    assert out.split()[-1] in s.split()                     # 末尾は完全な語


def test_truncate_at_word_fits():
    from listing_common import _truncate_at_word
    assert _truncate_at_word("short title", 80) == "short title"   # 収まれば不変


def test_enforce_coherence_no_broken_word():
    from listing_common import enforce_title_coherence
    title = "UNIQLO UT One Piece 25th Luffy Gear Second T-Shirt Black US Large Japan New Tag"
    out = enforce_title_coherence(title, is_new=True, max_chars=80)
    assert len(out) <= 80
    # 末尾が壊れ語('Ja' 等)でない = 全語が元タイトルの語
    src = set(title.split())
    for w in out.split():
        assert w in src or w in {"NWT", "New"}, f"broken/unknown word: {w}"


# ---- ②③ tshirt helpers ----
def _load_tshirt():
    p = _ROOT / "iMakMercari" / "tshirt_listing.py"
    sys.path.insert(0, str(p.parent))
    spec = importlib.util.spec_from_file_location("tshirt_listing_t", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_detect_media_type_webp_vs_jpeg():
    m = _load_tshirt()
    # webp: 'RIFF????WEBP'
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 16
    assert m._detect_media_type(base64.b64encode(webp).decode()) == "image/webp"
    # jpeg
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 16
    assert m._detect_media_type(base64.b64encode(jpeg).decode()) == "image/jpeg"
    # png
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assert m._detect_media_type(base64.b64encode(png).decode()) == "image/png"


def test_parse_json_lenient_extra_data():
    m = _load_tshirt()
    # JSON の後に説明文(Extra data) → 1個目の object だけ取れる
    txt = '{"title": "UNIQLO UT One Piece Tee", "collab": "One Piece"}\n\nThis listing looks good!'
    out = m._parse_json_lenient(txt)
    assert out["title"] == "UNIQLO UT One Piece Tee" and out["collab"] == "One Piece"
    # 通常の JSON もそのまま
    assert m._parse_json_lenient('{"a": 1}')["a"] == 1
