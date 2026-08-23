# -*- coding: utf-8 -*-
"""「PSA10のみ出品する」を規定にした (2026-08-23 ユーザー確定)。

この規定は、**グレードを毎回ちゃんと持っていること**が前提になる。持っていなければ
全部止まってしまうし、逆に「無ければ通す」に逃がすと規定した意味が無い。

実測でわかっていたこと (この修正の理由):
  8/23 朝に「グレードは PSA のページから読む」を入れたが、保存済の cert は
  読み出し口で早期 return していたため素通りしていた。その日出した9件は
  **全て保存データにグレードが無く、一度も確かめていなかった**。

なので直したのは2つ:
  ① 保存分にグレードが無ければ **取り直す** (1 cert につき一度だけ)
  ② 取りに行ったら、読めても読めなくても Grade の欄を作る
     (作らないと「未取得」と見なされて毎回 PSA を叩きに行く)
"""
import os
import re
import sys

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

_SRC = open(os.path.join(_TCG, "psa_to_csv.py"), encoding="utf-8").read()


# ── ① 保存分にグレードが無ければ取り直す ──────────────────────────
def test_cached_without_grade_is_refetched():
    """Grade の欄が無い保存分は、早期 return させずに取り直す。"""
    assert "if cached and cached.get('Subject') and 'Grade' not in cached:" in _SRC, \
        "保存分のグレード未取得を見て取り直す分岐が消えている"


def test_refetch_uses_key_absence_not_emptiness():
    """空文字は「取りに行ったが読めなかった」。毎回叩き直さない。"""
    assert "not cached.get('Grade')" not in _SRC, \
        "空判定にすると、読めない個体を毎回 PSA に取りに行ってしまう"


def test_scrape_always_creates_the_grade_field():
    assert "data.setdefault('Grade', '')" in _SRC, \
        "取りに行った事実が残らず、毎回取り直しになる"


# ── ② 規定そのもの ────────────────────────────────────────────────
def test_gate_uses_the_new_rule():
    assert "is_psa10_confirmed(claude_title, _vision_grade)" in _SRC, \
        "出品直前のゲートが新しい規定を使っていない"


def test_unconfirmed_grade_says_why_it_was_dropped():
    """黙って落とさない。落ちた理由が走行ログに残ること。"""
    assert "グレードを確かめられなかった" in _SRC


def test_no_caller_left_on_the_old_gate():
    """旧判定の呼び出しが1つも残っていないこと (定義と例外文だけは残る)。"""
    calls = [m for m in re.findall(r"(?<!def )is_psa10_or_unknown\([^)]*\)", _SRC)]
    assert calls == [], f"旧判定を呼んでいる箇所が残っている: {calls}"


# ── 入口の仕分け ──────────────────────────────────────────────────
def test_supplier_filter_catches_other_graders():
    import psa_to_csv as P
    assert P.supplier_grade_hint("【CGC10】ピカチュウ") == "CGC"
    assert P.supplier_grade_hint("BGS 9.5 Charizard") == "BGS"
    # PSA10 と書いてあるなら、他社名が出ても落とさない (付属品の可能性)
    assert P.supplier_grade_hint("PSA10 CGCカードローダー付き") is None


def test_confirmed_rule_end_to_end():
    import psa_to_csv as P
    assert P.is_psa10_confirmed("PSA 10 Pokemon x", "10") is True
    for g in ("9", "8", "", None):
        assert P.is_psa10_confirmed("PSA 10 Pokemon x", g) is False, g
