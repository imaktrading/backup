"""UT 目視: 写真の出どころの札と、使う枚数 (12枚まで) を画面で出す (2026-10-12)。

ユーザー「出品に使う写真の出どころを書いておいて、ちゃんと出ているかわかるから」
「12枚の制限をかける意味ないよね？選ぶのが12枚までなだけで」。
それまで追加の写真は受け取る時に黙って12枚で切っていた。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import ut_identify as U


def test_画面に出どころの札と使う枚数():
    h = U.build_html([], [])
    h = h.decode() if isinstance(h, bytes) else h
    assert "srcl" in h and "同じ物 " in h and "探したURL" in h and "メルカリ" in h
    assert "出品に使う写真 " in h and "MAXPIC=12" in h and "nopicover" in h


def test_追加の写真を受け取る時に12枚で切らない():
    urls = [f"https://example.com/{i}.jpg" for i in range(15)]
    r = U.parse_result({"picks": [{"idx": 1, "pid": "p1", "color": "黒", "extra": urls}]})
    assert len(r["picks"][0]["extra"]) == 15


def test_選び直しても写真の候補と使う使わないを残す():
    """同じ物が3つ。候補を選び直すと出品に使う写真が変わっていた (2026-10-12)。
    ブラウザで A→B→C と選び直して、使う写真の集まりが3回とも同じことを確かめた。"""
    h = U.build_html([], [])
    h = h.decode() if isinstance(h, bytes) else h
    assert "function snapImgs" in h and "function restoreImgs" in h
    assert "if(grouped&&prev&&prev!==el){prev.classList.add('same');}" in h
    assert "if(grouped)restoreImgs(box,snap);" in h
