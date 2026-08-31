# -*- coding: utf-8 -*-
"""ガチャの出品生成が Opus を使っていないこと (2026-08-31)。

★経緯: 課金の見直しで全プロジェクトのモデルを洗ったところ、**ガチャの2本だけ**が
  `claude-opus-5` だった。他カテゴリ (PSA / G-shock / メルカリ / 一番くじ /
  カタログ翻訳) は全部 Sonnet で回っており、ガチャだけ最上位である理由が無かった。
  ユーザー確定で Sonnet に落としたので、戻ってこないように固定する。

  併せて `gacha_to_csv.MODEL` は **使われていない定数**だった (このファイルは API を
  叩かない)。「ここが Opus」と読めて見直しのたびに迷うので、決定口を
  gacha_enrich.py の1か所に寄せた。2本が食い違わないことも見る。
"""
import os
import sys

import pytest

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import gacha_enrich as E                                          # noqa: E402
import gacha_to_csv as G                                          # noqa: E402


def test_gacha_enrich_is_not_opus():
    assert "opus" not in E.MODEL.lower(), (
        f"ガチャの生成が Opus に戻っている ({E.MODEL})。"
        "戻すなら課金の見直し (2026-08-31) を踏まえてユーザーに確認すること"
    )


def test_gacha_enrich_model_is_sonnet():
    assert E.MODEL == "claude-sonnet-4-6", E.MODEL


def test_gacha_to_csv_shares_the_same_model_constant():
    """決定口は1か所。2本が別々の値を持てるようだと見直しがまた迷子になる。"""
    assert G.MODEL == E.MODEL, (G.MODEL, E.MODEL)


def test_gacha_to_csv_does_not_call_the_api():
    """gacha_to_csv 側が API を叩き始めたら、この test の前提 (定数は飾り) が崩れる。"""
    src = open(os.path.join(_TOOLS, "gacha_to_csv.py"), encoding="utf-8").read()
    assert "messages.create" not in src, (
        "gacha_to_csv.py が API を叩き始めた。モデルの決定口を見直すこと"
    )
