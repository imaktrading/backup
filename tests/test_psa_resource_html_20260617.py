"""Regression: 2026-06-17 — PSA再仕入れ 目視ビューア(仕入候補+補を正カードと並べHTML化)。

番号一致では弾けない変種取り違え(CHR/VMAX・JP/Asia)を買う前に目視する HTML を出力。
- Mercari候補は item m<id> から CDN 画像URLを構成(scraping不要)
- build_html は純粋(画像URLを受け取り描画)
- オークションはソース側(mercari _AUCTION_MARKERS / snkrdunk isSaleOnly)で既に除外済なので
  ここには来ない前提

ネットに触れないよう mercari_image_url / build_html のみを検証。
"""
import importlib.util
import os
import tempfile
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_resource_html.py"
_spec = importlib.util.spec_from_file_location("psa_resource_html_t", _PATH)
prh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prh)


def test_mercari_image_url_from_item_id():
    u = prh.mercari_image_url("https://jp.mercari.com/item/m12345678901")
    assert u == "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg"
    assert prh.mercari_image_url("https://snkrdunk.com/apparels/134163") == ""
    assert prh.mercari_image_url("") == ""


def test_candidate_image_routes_mercari_offline():
    # mercari は CDN 構成(ネット不要)
    img = prh.candidate_image("mercari", "https://jp.mercari.com/item/m98765432109")
    assert img.endswith("m98765432109_1.jpg")


def test_build_html_handles_list_ref_label():
    # catalog hint は list で来る → _html.escape が落ちない(2026-06-17 実機crash回帰)
    import os
    import tempfile
    out = os.path.join(tempfile.mkdtemp(prefix="psa_html_"), "psa_resource_review_listlabel.html")
    p = prh.build_html([{"title": ["A", "B"], "ref_image": "https://x/r.jpg",
                         "ref_label": ["OP11", "SR"], "ng": False, "candidates": []}], out)
    h = open(p, encoding="utf-8").read()
    assert "OP11 / SR" in h and "A / B" in h


def test_build_html_writes_ref_and_candidates():
    items = [{
        "title": "PSA 10 One Piece P-041 Luffy",
        "ref_image": "https://example.com/ref.jpg",
        "ref_label": "ルフィ P-041 7-11 promo",
        "ng": False,
        "candidates": [
            {"channel": "snkrdunk", "url": "https://snkrdunk.com/apparels/1/used/2", "price": 48888, "image": "https://example.com/s.jpg", "is_main": True},
            {"channel": "mercari", "url": "https://jp.mercari.com/item/m1", "price": 105000, "image": "https://static.mercdn.net/x_1.jpg", "is_main": False},
        ],
    }]
    out = os.path.join(tempfile.mkdtemp(prefix="psa_html_"), "psa_resource_review_test.html")
    p = prh.build_html(items, out)
    htmltext = open(p, encoding="utf-8").read()
    assert "ref.jpg" in htmltext          # 正カード画像
    assert "P-041" in htmltext            # タイトル
    assert "snkrdunk.com/apparels/1" in htmltext  # 候補リンク
    assert "★最安" in htmltext            # main マーク
    assert "¥48,888" in htmltext          # 価格整形
