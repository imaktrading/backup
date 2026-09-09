# -*- coding: utf-8 -*-
"""仕入元にタイトルが無い種は、人が選んだカタログのカード名を入れる (2026-09-09)。

snkrdunk の候補は **仕入元にタイトルが無い** (キャッシュが持っていない)。C列が空でも
CSV は cert から作れるが、**シートのタイトルを見ている門が3つ**ある:

  - 仕入元が「PSA9」と書いているのを検出 (`psa_to_csv.non_psa10_certs`)
  - まとめ売りの検出 (`multi_card_certs`)
  - 作品の振り分け (`tcg_batch_select.classify_franchise` / ポケモン70%)

空だと3つ目が **既定の Pokemon** に倒れ、ワンピースのカードがポケモン枠を食う
(実測 2026-09-09: 行2760/2761 はどちらもワンピースだった)。
snkrdunk は PSA10 専用の一覧から取るので1つ目・2つ目は構造的に問題ない。
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import newcand_confirm as N     # noqa: E402


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "c.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE products (product_id TEXT, category TEXT, name TEXT, name_en TEXT)")
    con.executemany("INSERT INTO products VALUES (?,?,?,?)", [
        ("P-041_r1", "one_piece_tcg", "モンキー・D・ルフィ", "Monkey D. Luffy"),
        ("SB02-053", "dragonball_scg", "フリーザ", "Frieza"),
        ("SV8a-203", "pokemon_tcg", "", "Pikachu ex"),
    ])
    con.commit()
    con.close()
    return str(p)


def test_作品名とカード名と番号が入る(db):
    assert N.catalog_title_for("", "P-041_r1", db) == "ワンピース モンキー・D・ルフィ P-041_r1"


def test_ドラゴンボールのカテゴリ名は_scg(db):
    """★実カテゴリは `dragonball_scg` (`_tcg` ではない)。綴り違いは作品名が付かず
    番号でも判定できない (SB02-053 は DragonBall の番号パターンに当たらない) ので
    **既定の Pokemon に倒れる** = ポケモン70%の枠を食う。"""
    assert N.catalog_title_for("", "SB02-053", db) == "ドラゴンボール フリーザ SB02-053"


def test_日本語名が無ければ英語名を使う(db):
    assert N.catalog_title_for("", "SV8a-203", db) == "ポケモン Pikachu ex SV8a-203"


def test_引けなければ空(db):
    assert N.catalog_title_for("", "NOPE-999", db) == ""
    assert N.catalog_title_for("", "", db) == ""


def test_作った題で作品が正しく分かれる(db):
    """この関数の存在理由。出せる題が振り分けに効かないなら意味がない。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "iMakTCG"))
    import tcg_batch_select as T
    assert T.classify_franchise(N.catalog_title_for("", "P-041_r1", db)) == "OnePiece"
    assert T.classify_franchise(N.catalog_title_for("", "SB02-053", db)) == "DragonBall"
    assert T.classify_franchise(N.catalog_title_for("", "SV8a-203", db)) == "Pokemon"


def test_仕入元のタイトルがあればそちらが優先():
    """仕入元の文言は PSA9 検出・まとめ売り検出の材料なので、上書きしない。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "tools", "newcand_confirm.py"), encoding="utf-8").read()
    assert 'it["title"] or catalog_title_for(' in src
