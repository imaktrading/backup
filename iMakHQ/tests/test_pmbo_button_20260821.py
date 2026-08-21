# -*- coding: utf-8 -*-
"""TOPパネルの「📣 Pm/Bo」ボタン (2026-08-21).

ユーザー依頼: 「ボタンを出品君TOPパネルのオファー対応の横に Pm/Bo ボタンを」

UK/AU/CA のミラー出品に 広告10% と ベストオファー を付ける。
人が3サイトの画面を回って手でやっていた作業。

★いきなり書かない。**まず数えて見せて、人が了解してから**実行する。
  3,500件規模を1件ずつ書き換える処理なので、押し間違いで走らせない。
"""
from __future__ import annotations

import io
import os
import re

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(HQ, "control_panel.py")
SRC = io.open(PANEL, encoding="utf-8").read()


def test_ボタンがある():
    assert 'text="📣 Pm/Bo"' in SRC


def test_オファー対応の隣にある():
    """side=right は pack した順に右から左へ並ぶ。
    見た目で隣にするには オファー対応 の **直前** に pack する."""
    i_pm = SRC.index('self.pmbo_btn.pack(')
    i_of = SRC.index('self.offer_btn.pack(')
    assert i_pm < i_of, "オファー対応 より後に pack すると隣に並ばない"


def test_押しても即実行しない():
    """★確認を挟む。3,500件を1件ずつ書き換えるので、押し間違いで走らせない."""
    body = SRC[SRC.index("def open_mirror_pmbo"):SRC.index("def open_listing")]
    assert "askyesno" in body
    # 最初の起動は --write なし (数えるだけ)
    assert "args=(False,)" in body


def test_同じ道具を呼んでいる():
    body = SRC[SRC.index("def open_mirror_pmbo"):SRC.index("def open_listing")]
    assert "mirror_promo_bestoffer.py" in body
    assert '"--write"' in body


def test_失敗を黙って飲まない():
    body = SRC[SRC.index("def open_mirror_pmbo"):SRC.index("def open_listing")]
    assert "showerror" in body


# ── 一番くじの補URL 2ボタン (2026-08-22 ユーザー指示) ──────────────────
#
# 「PSA で実績があるので、ボタンを作って」「新規出品パネルにね」
# PSA と同じ 2段 (夜=検索 / 昼=目視)。画面も PSA の確証UI をそのまま使う。

def test_一番くじの補URLボタンが2つある():
    assert "🎴 くじ補URL 夜間検索" in SRC
    assert "🎴 くじ補URL 昼確認" in SRC


def test_ラベルが長すぎない():
    """★2026-08-22「ラベルがボタンからはみ出ていて、どのボタンが何かわからない」。
    PSA の一番長いラベル (20字) 以下に収める."""
    for lb in ("🎴 くじ補URL 夜間検索", "🎴 くじ補URL 昼確認"):
        assert len(lb) <= 20, lb


def test_一番くじは絵文字で見分けられる():
    """★PSA と混ざって見えた。一番くじは 🎴 を頭に付けて系統を揃える."""
    for lb in ("🎴 くじ補URL 夜間検索", "🎴 くじ補URL 昼確認"):
        assert lb.startswith("🎴")


def test_夜と昼で別のコマンド():
    assert '"kuji_hoju_fill.py", "--search"' in SRC
    assert '"kuji_hoju_fill.py", "--confirm"' in SRC


def test_新規出品パネルに置かれる():
    """★出品→itemID書込→補URL確保 は一連の流れ。既存メンテ側に離すと導線が切れる
    (PSA の 🆕/🩹 と同じ扱い)."""
    i = SRC.index('if "kuji_hoju_fill.py" in cmd:')
    assert 'return "hoju"' in SRC[i:i + 200]


def test_昼は件数を区切る():
    """確証UIは全件まとめて送信する = 出した分はやり切る必要がある。
    PSA と同じく1回10件ずつ."""
    i = SRC.index('"kuji_hoju_fill.py", "--confirm"')
    assert "--limit=10" in SRC[i:i + 120]
