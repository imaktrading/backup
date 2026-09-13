# -*- coding: utf-8 -*-
"""「カタログに無い」の依頼に **手がかり** を載せる (2026-09-13)。

catalog の回答 (2026-09-12_ut_not_in_catalog_response.md): 8件 **1件も特定できなかった**。
理由は「カタログに無い」ではなく「手がかりが足りない」。品番 (E+9桁) か公式ページの URL が
1つあれば引ける。写真だけでは品番に辿り着けない。

それまで渡していたのは タイトル / 色 / サイズ / タグの番号 / 見つけた語 / 仕入元 / **写真1枚目だけ**。
- ユーザー「私がどこまで作業できるかわからんけど、任意で参考URLを入れる欄を設けてもらうか」
  → 目視で「カタログに無い」を押した時だけ **作品名 / 参考URL** の欄が出る。**どちらも任意**
- 写真は全部 (最大10枚)。タグは2枚目以降に写っていることが多い
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ" / "tools", ROOT / "iMakMercari", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ut_identify as U  # noqa: E402

REF = "https://www.uniqlo.com/jp/ja/products/E481120-000/00"
P1 = "https://static.mercdn.net/item/detail/orig/photos/m1_1.jpg"
P2 = "https://static.mercdn.net/item/detail/orig/photos/m1_2.jpg"


def test_optional_clues_are_parsed_and_bad_url_dropped():
    res = U.parse_result({"nocat": [4, 5, 6], "nocat_info": {
        "4": {"work": " 鬼滅の刃  猗窩座 ", "ref": REF},
        "5": {"work": "", "ref": "公式にあった"},      # URL でない
        "6": {"work": "", "ref": ""}}})
    assert res["nocat"] == [4, 5, 6], "欄が空でも依頼は出る (任意)"
    assert res["nocat_info"] == {4: {"work": "鬼滅の刃 猗窩座", "ref": REF}}


def test_old_payload_without_info_still_works():
    res = U.parse_result({"nocat": [4]})
    assert res["nocat"] == [4] and res["nocat_info"] == {}


def test_request_carries_work_ref_and_every_photo():
    md = U.request_md([{"url": "https://jp.mercari.com/item/m1", "title": "ユニクロ 鬼滅 T | L",
                        "color": "ネイビー", "size": "M", "tag": "", "kw": "",
                        "work": "鬼滅の刃", "ref": REF, "photos": [P1, P2]}])
    assert "| 作品名 (目視) | 参考URL |" in md
    assert "鬼滅の刃" in md and REF in md
    assert f"[1]({P1})" in md and f"[2]({P2})" in md
    assert "T ／ L" in md, "縦棒で表が崩れる"


def test_empty_clues_show_a_dash():
    md = U.request_md([{"url": "https://jp.mercari.com/item/m2", "title": "t", "photo": P1}])
    line = [ln for ln in md.splitlines() if "m2" in ln][0]
    assert line.count("| - |") >= 2 and f"[1]({P1})" in line


def test_same_day_old_table_gets_a_new_section():
    old = ("# 依頼\n\n| メルカリのタイトル | 色 | サイズ | タグの番号 | 見つけた語 | 仕入元 | 写真 |\n"
           "|---|---|---|---|---|---|---|\n| a | | | - | - | https://jp.mercari.com/item/m0 | - |\n")
    md = U.request_md([{"url": "https://jp.mercari.com/item/m3", "title": "t"}], existing=old)
    assert "## 追加分" in md and md.count("| 作品名 (目視) |") == 1


def test_screen_shows_the_fields_only_for_not_in_catalog():
    import io
    src = io.open(ROOT / "iMakHQ" / "tools" / "ut_identify.py", encoding="utf-8").read()
    assert "class='catinfo' style='display:none'" in src
    assert "ci.style.display=btn.dataset.a==='cat'?'':'none'" in src
    assert "nocat_info:nocatInfo" in src
