"""目視HTML 共通の虫眼鏡(現物|候補の並列拡大)の回帰テスト (2026-07-28).

psa_resource_confirm で有効だったので3ビューアに横展開した。守るべき性質:
  1. 候補単独の全画面にしない(見比べが目的なので現物と並べる)
  2. ボタンで preventDefault + stopPropagation(親のクリック=選択/チェックを誤爆させない)
  3. 候補画像が無ければボタンを出さない
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

from viewer_zoom import ZOOM_JS, ZOOM_OVERLAY, zoom_button  # noqa: E402


def test_button_carries_both_images():
    h = zoom_button("https://c/cand.jpg", "https://r/ref.jpg")
    assert 'data-img="https://c/cand.jpg"' in h
    assert 'data-ref="https://r/ref.jpg"' in h


def test_no_button_without_candidate_image():
    assert zoom_button("", "https://r/ref.jpg") == ""
    assert zoom_button(None) == ""


def test_button_does_not_trigger_parent_click():
    """候補カード/label はクリックで選択・チェックが動く。拡大で誤爆させない。"""
    assert "preventDefault" in ZOOM_JS
    assert "stopPropagation" in ZOOM_JS


def test_overlay_has_two_panes():
    assert "id='zref'" in ZOOM_OVERLAY and "id='zcand'" in ZOOM_OVERLAY


def test_ref_pane_hidden_when_no_reference():
    """現物画像が無い行では候補だけ出す(空URLの img を出さない)。"""
    assert "L.style.display='none'" in ZOOM_JS


def test_escape_closes():
    assert "Escape" in ZOOM_JS


def test_html_escaped():
    """URL 内の " が属性を閉じてしまわないこと(閉じられると任意の属性を注入できる)。"""
    h = zoom_button('https://c/a.jpg"onerror=alert(1)', "")
    assert '&quot;' in h
    assert 'data-img="https://c/a.jpg"o' not in h      # 生の " で属性が切れていない


def _built_pages():
    """3ビューアの実出力を集める(生成が壊れていないことも兼ねる)。"""
    import ichibankuji_restock as I
    import psa_resource_html as H
    import tempfile
    pages = {}
    pages["ichibankuji"] = I.build_identify_html([{
        "row": 5, "item_id": "358", "title": "一番くじ A賞", "prize": "A賞",
        "ref_image": "https://x/ref.jpg",
        "candidates": [{"url": "https://jp.mercari.com/item/m123456789",
                        "price": 3000, "image": "https://y/c.jpg"}]}])
    out = os.path.join(tempfile.mkdtemp(), "v.html")
    H.build_html([{"title": "t", "ref_image": "https://x/ref.jpg", "ref_label": "正カード",
                   "candidates": [{"channel": "mercari", "url": "https://jp.mercari.com/item/m1",
                                   "price": 100, "image": "https://y/c.jpg"}]}], out)
    pages["psa_resource_html"] = open(out, encoding="utf-8").read()
    return pages


def test_viewers_render_zoom():
    for name, html in _built_pages().items():
        assert "class='zm'" in html, name
        assert "id='zov'" in html, name
        assert "function zoom(" in html, name
        assert "data-ref=" in html, name
