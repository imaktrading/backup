# -*- coding: utf-8 -*-
"""ボタンの色は「今押すといいか」だけを表す (2026-08-16 ユーザー指示)。

★経緯: ユーザー「いまだに、そのボタンをいつ押せばいいのか分からない」。
  従来の色は **verified かどうか** や飾りで青/赤/緑に塗り分けており、押し時とは無関係だった。
  色が意味を持たないと、結局ログを最後まで読むまで押し時が分からない。

  → 既定は全部黒。**残件ラベルを持つボタンだけ**が「押すと出てくる件数 > 0」の時に青くなる。
  併せて、残件ラベル(最大4行)が見切れないようボタンの高さを行数に合わせる。
"""
from __future__ import annotations

import re

_PANEL = r"C:\dev\iMak\iMakHQ\control_panel.py"


def _src():
    return open(_PANEL, encoding="utf-8", errors="replace").read()


def test_buttons_default_to_black():
    """飾りの色分けをやめ、既定は黒。"""
    src = _src()
    assert 'color = "black"' in src, "汎用ボタンの既定が黒でない"
    assert 'fg="black"' in src, "カテゴリボタンの既定が黒でない"
    # verified で青くする旧ロジックが残っていない
    assert not re.search(r'"#0066cc" if SCRIPTS\[', src), "verified で青くする旧ロジックが残っている"


def test_blue_only_when_pressing_yields_something():
    """青くするのは「押すと出てくる件数 > 0」の時だけ。"""
    src = _src()
    assert "act_kind" in src, "押し時の判定が無い"
    assert 'fg=("#0066cc" if act_kind.get(kind) else "black")' in src
    for kind in ('"hoju_search": bool(s.get("can"))',
                 '"hoju_confirm": bool(cf.get("ready") or cf.get("unjudged"))',
                 '"newcand": bool(nc.get("show") or nc.get("auto"))'):
        assert kind in src, f"判定が無い: {kind}"


def test_every_badge_button_is_registered():
    """残件ラベルを持つボタンは全部登録する (🌱 が漏れていた)。"""
    src = _src()
    assert "if _bg:" in src, "badge の登録が種類決め打ちのまま"
    assert '_bg in ("hoju_search", "hoju_confirm")' not in src


def test_label_fits_in_the_button():
    """ラベルがボタンからはみ出さない。

    ★2026-08-22 に作りを変えた。以前は件数をラベルに焼いていたので行数が伸び、
      高さを行数に合わせて広げていた (max(3, min(7, ...)))。
      いまは **件数をヒントに逃がしてラベルは固定** なので、高さも固定でよい。
      ユーザー指示「ラベルはシンプルにして、押すべき時は青色に。
      件数や詳細はヒントテキストに移行」。

    ★2026-08-31 例外: 「棚を入れ替える」ボタンだけ、ユーザーが明示で
      ラベルにも件数・金額を求めた。この1つだけは高さも伸びる (height=5)。
      他のボタンがこの型に倣って際限なく伸びないよう、例外は
      `kind == "shelf_evict"` に限定されていることまで確認する。
    """
    src = _src()
    assert "b.config(text=text, height=(5 if extra else 3)," in src, "ラベルの既定挙動を変えている"
    assert "set_tip(" in src, "件数をヒントに回していない"
    assert "(16, 3, 2, 170) if compact else (18, 3, 4, 250)" in src, "既定の高さ/折返し幅が小さいまま"
    i = src.index("def paint_hoju_badge")
    body = src[i:i + 1600]
    assert 'kind == "shelf_evict"' in body, "ラベル例外の対象が絞られていない"
    assert body.count('kind + "_label"') >= 1, "ラベル例外の取り出し方が変わっている"
