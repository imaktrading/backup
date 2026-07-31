"""目視HTML の JS が **文法として成立している**ことの回帰テスト (2026-08-01).

なぜ要るか (実害):
    `psa_resource_confirm._JS_RESTOCK` は Python の **非 raw** 文字列。ここに `\\n` を
    1文字の escape のつもりで `\\n` と書くと **本物の改行**が埋まり、JS の文字列リテラルが
    行の途中で切れて SyntaxError になる。JS は script ブロック単位で parse するため、
    **そのブロック内の関数が全部未定義**になる (zoom / upd / setAll / setRsn / go / imgFail)。
    2026-07-30 に go() の confirm メッセージを足した際にこれが混入し、
    **RESTOCK 視覚確証 UI が丸ごと無反応**になっていた (虫眼鏡も ✅RESTOCK確定 も効かない)。
    既存の test_viewer_zoom は「`function zoom(` が HTML に在るか」しか見ないので素通りした。
    = 文字列としての存在ではなく **parse できるか**を見る必要がある。

やり方:
    node が入っていない環境なので、JS の全機能を parse するのではなく
    **この事故のクラス (行を跨いだ文字列リテラル) だけ**を確実に検出する軽量チェックにする。
    行コメント/ブロックコメントを除去した上で、1行内の未 escape なクォートが
    奇数個 = その行で開いた文字列が閉じていない、と判定する。
"""
import os
import re
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import psa_resource_confirm as C            # noqa: E402
import viewer_zoom as Z                     # noqa: E402


def _strip_comments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in js.split("\n"))


def unterminated_string_lines(js: str):
    """行を跨いで閉じていない文字列リテラルの (行番号, 行) を返す。無ければ空。"""
    bad = []
    for n, line in enumerate(_strip_comments(js).split("\n"), 1):
        for q in ("'", '"'):
            # 直前が \ でないクォートだけ数える
            if len(re.findall(r"(?<!\\)" + q, line)) % 2:
                bad.append((n, line.strip()))
                break
    return bad


def test_restock_js_has_no_line_broken_string():
    """★本命。ここが落ちたら RESTOCK 視覚確証は**全ボタン無反応**になっている。"""
    assert unterminated_string_lines(C._JS_RESTOCK) == []


def test_confirm_js_has_no_line_broken_string():
    assert unterminated_string_lines(C._JS) == []


def test_zoom_js_has_no_line_broken_string():
    assert unterminated_string_lines(Z.ZOOM_JS) == []


def test_detector_actually_detects():
    """検出器そのものが効いていることの確認 (通らないテストは無いのと同じ)。"""
    broken = "if(!confirm('a\nb')) return;"
    assert unterminated_string_lines(broken)
    assert unterminated_string_lines(r"if(!confirm('a\nb')) return;") == []


def test_generated_restock_html_keeps_functions_intact():
    """実出力の script ブロックまで通しで見る (定数だけ直して配線が抜ける事故を防ぐ)。"""
    html = C.build_restock_html([{
        "idx": 1, "title": "t", "card_no": "001", "ebay_url": "https://e/1",
        "ref_image": "https://r/ref.jpg",
        "candidates": [{"channel": "mercari", "url": "https://jp.mercari.com/item/m1",
                        "price": 1000, "image": "https://y/c.jpg"}]}])
    js = html.split("<script>")[1].split("</script>")[0]
    assert unterminated_string_lines(js) == []
    for fn in ("zoom", "upd", "setAll", "setRsn", "go", "imgFail"):
        assert f"function {fn}(" in js, fn
