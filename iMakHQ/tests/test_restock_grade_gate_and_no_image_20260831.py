# -*- coding: utf-8 -*-
"""再出品くん (psa_restock_csv) のグレード確認 (2026-08-31)。

★2つの穴を同時にふさいだ。どちらも「新規側 (psa_to_csv) には入っていたが、
  fork には入っていなかった」もの。fork は 2026-06-18 に切り出して以来、
  新規側に入った 2026-08-23 の修正を受け取っていなかった。

  1) **PSA10 ゲートが無かった** (安全)
     C:Grade は "10" 固定・タイトルも "PSA 10" 始まりなので、PSA9 が混ざると
     グレード誤表示 + PSA10 相場の誤参照になる。2026-07-27 に実害4件 (END 済)。
  2) **要らない画像を毎回 API に送っていた** (課金)
     本番は TCG_USE_NEW_GEN=1 で、タイトルは新コアが catalog 値から作り直す。
     つまり画像から作ったタイトルは捨てられていた。グレードは PSA ページの
     Item Grade から読めるので、画像を送る必要が無い。
"""
import io
import os
import sys

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

import psa_restock_csv as R                                        # noqa: E402

_SRC = io.open(os.path.join(_TCG, "psa_restock_csv.py"), encoding="utf-8").read()


def test_psa_page_grade_is_parsed():
    """PSA ページの Item Grade を拾えること (これが無いと下の2つが効かない)。"""
    page = "\n".join(["Item Grade", "GEM MT 10",
                     "2025 ONE PIECE JAPANESE OP01 #001 LUFFY"])
    d = R.parse_psa_page(page)
    assert d.get("Grade") == "GEM MT 10", d


def test_psa_page_grade_japanese_label():
    page = "\n".join(["グレード", "MINT 9",
                     "2025 ONE PIECE JAPANESE OP01 #001 LUFFY"])
    d = R.parse_psa_page(page)
    assert d.get("Grade") == "MINT 9", d


def test_grade_number_reads_the_number():
    assert R._grade_number("GEM MT 10") == "10"
    assert R._grade_number("MINT 9") == "9"
    assert R._grade_number("") == ""
    assert R._grade_number(None) == ""


def test_grade_number_matches_the_new_generator():
    """読み方は新規側と同じ1本。fork が自前で持つと、また片方だけ直る。"""
    from psa_to_csv import grade_number as _new
    for v in ("GEM MT 10", "MINT 9", "NM-MT 8", "", None, "よめない"):
        assert R._grade_number(v) == _new(v), v


def test_restock_has_the_psa10_gate():
    """PSA10 以外は再出品しない。fork にはこのゲートが無かった。"""
    assert "PSA10 のみ出品する規定" in _SRC,         "再出品くんの PSA10 ゲートが消えている (PSA9 が 'PSA 10' として出る)"
    assert "_page_grade or str((claude_result or {}).get('psa_grade')" in _SRC,         "グレードの出どころが PSAページ→ラベル画像 の順でなくなっている"


def test_restock_skips_the_image_when_the_page_grade_is_readable():
    """新コアが有効でグレードが読めたら、画像を API に送らない (課金しない)。"""
    assert "if os.environ.get('TCG_USE_NEW_GEN') == '1' and _page_grade:" in _SRC,         "画像を送らない判定が消えている (捨てられるタイトルのために課金する)"
    i_skip = _SRC.index("and _page_grade:")
    i_call = _SRC.index("claude_result = generate_title_with_claude(")
    assert i_skip < i_call, "画像を送る呼び出しが判定より前にある = 判定が効かない"
