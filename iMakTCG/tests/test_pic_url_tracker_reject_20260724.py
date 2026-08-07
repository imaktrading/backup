"""PicURL に トラッキングビーコン/プレースホルダが混入する回帰を固定 (2026-07-24)。

契機: cert 55542036 (Vaporeon #071) の入稿が eBay ErrorCode 20002
      「Picture URL は 1本500字以内 / 全体3975字以内」で失敗。
真因: PSA card 画像 fetch が 403 → DOM scrape の緩い filter
      ['cert','card','psa','grading'] が、URL内に psacard.com/cert を埋め込んだ
      Bing トラッキングビーコン(bat.bing.com, 582字)と table-image-ink プレースホルダを
      誤って拾い PicURL に混入させた。
対策: _is_real_card_image で本物のカード画像 CDN のみ許可 + トラッキング/装飾/長すぎURL を除外。
      _build_pic_url でも二重ガード。
純関数のみ (DB/network 非依存)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psa_to_csv import _is_real_card_image, _build_pic_url, PIC_URL, _PIC_URL_MAX_LEN


# --- 実際に混入した gomi (2026-07-24 cert 55542036) ---
_BING_BEACON = ("https://bat.bing.com/action/0?ti=97014114&tm=gtm002&Ver=2&mid="
                "a919a625-31ae-4f36-805b-786e" + "x" * 500)  # 582字相当 (>500)
_PLACEHOLDER = "https://i.psacard.com/psacard/images/cert/table-image-ink.png?fm=webp&q=80"
_REAL_FRONT = "https://d1htnxwo4o0jhw.cloudfront.net/cert/204191756/small/3vVodO44E0qzdklhSOse-A.jpg"
_REAL_BACK = "https://d1htnxwo4o0jhw.cloudfront.net/cert/204191756/small/coeY-FnKtUKgxsQ-WWydIA.jpg"


def test_bing_tracker_rejected():
    assert _is_real_card_image(_BING_BEACON) is False


def test_placeholder_rejected():
    # table-image-ink プレースホルダ (URL内に psacard/cert を含むが本物でない)
    assert _is_real_card_image(_PLACEHOLDER) is False


def test_real_psa_card_cdn_accepted():
    assert _is_real_card_image(_REAL_FRONT) is True
    assert _is_real_card_image(_REAL_BACK) is True


def test_over_length_url_rejected():
    long_but_cdn = ("https://d1htnxwo4o0jhw.cloudfront.net/cert/1/small/" + "a" * 500 + ".jpg")
    assert len(long_but_cdn) > _PIC_URL_MAX_LEN
    assert _is_real_card_image(long_but_cdn) is False


def test_non_http_rejected():
    assert _is_real_card_image("") is False
    assert _is_real_card_image("data:image/png;base64,AAAA") is False
    assert _is_real_card_image(None) is False


def test_build_pic_url_drops_junk_keeps_dummy():
    # gomi が Front/Back に入っても PicURL には載らず、ダミー999は必ず残る
    data = {"CardImageUrlFront": _BING_BEACON, "CardImageUrlBack": _PLACEHOLDER}
    pic = _build_pic_url(data)
    assert "bat.bing" not in pic
    assert "table-image" not in pic
    assert PIC_URL in pic
    # eBay 制約: 各 URL 500字以内 / 全体 3975字以内
    for u in pic.split("|"):
        assert len(u) <= _PIC_URL_MAX_LEN
    assert len(pic) <= 3975


def test_build_pic_url_keeps_real_images():
    data = {"CardImageUrlFront": _REAL_FRONT, "CardImageUrlBack": _REAL_BACK}
    pic = _build_pic_url(data)
    parts = pic.split("|")
    assert _REAL_FRONT in parts
    assert _REAL_BACK in parts
    assert parts[-1] == PIC_URL   # ダミーは末尾


def test_build_pic_url_all_junk_falls_to_dummy_only():
    data = {"CardImageUrlFront": _BING_BEACON, "CardImageUrlBack": None}
    pic = _build_pic_url(data)
    assert pic == PIC_URL   # 本物ゼロ → ダミー1本のみ
