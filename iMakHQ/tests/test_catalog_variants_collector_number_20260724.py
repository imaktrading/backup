# -*- coding: utf-8 -*-
"""catalog_variants_for_cardno のコレクター番号フォールバック 回帰テスト (2026-07-24)。

バグ: Pokemon の eBay タイトルは card番号が「038/095」(コレクター番号)だが catalog の
product_id はセットコード形式(SM9-038)。product_id 一致だけ引く旧実装は 0件を返し、
RESTOCK 再仕入れ照合の目視ゲート②に候補が出ない=「候補が全然表示されない」不具合。
対策: product_id で 0件 かつ NNN/NNN 形式なら specs.card_number_text で再検索し、
title のキャラ名(name_en)一致で正しいセットを上位に並べる(複数セットが同番号を持つため)。
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mercari_psa_resource as mp  # noqa: E402


def _mkdb(tmp_path):
    db = str(tmp_path / "cat.sqlite")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (product_id TEXT, name_jp TEXT, set_name TEXT, "
                "images TEXT, specs TEXT, language TEXT, name_en TEXT, category TEXT)")
    rows = [
        # 同じコレクター番号 058/095 を持つ4セット(実DBと同型)
        ("SM8-058", "ブラッキー", "超爆インパクト", "[]", json.dumps({"card_number_text": "058/095"}), "ja", "Umbreon"),
        ("SM9-058", "カブト", "タッグボルト", "[]", json.dumps({"card_number_text": "058/095"}), "ja", "Kabuto"),
        ("SM10-058", "メグロコ", "ダブルブレイズ", "[]", json.dumps({"card_number_text": "058/095"}), "ja", "Sandile"),
        # セットコード形式で引ける One Piece(fallback を踏まない経路の非回帰確認)
        ("OP05-098", "エネル", "謀略の王国", "[]", json.dumps({"card_number_text": "98/..."}), "ja", "Enel"),
        ("OP05-098_L", "エネル", "謀略の王国", "[]", json.dumps({}), "ja", "Enel"),
        # 英語版は除外されること
        ("SM8-058", "Umbreon", "Burst Impact", "[]", json.dumps({"card_number_text": "058/095"}), "en", "Umbreon"),
    ]
    con.executemany("INSERT INTO products (product_id,name_jp,set_name,images,specs,language,name_en,category) "
                    "VALUES (?,?,?,?,?,?,?,'pokemon_tcg')", rows)
    con.commit()
    con.close()
    return db


def test_collector_number_fallback_with_character_hint(tmp_path):
    """★本命: 058/095 で product_id は引けないが card_number_text で3件ヒット、
    title のキャラ名 'Umbreon' で SM8-058(ブラッキー)が先頭に来る。"""
    db = _mkdb(tmp_path)
    v = mp.catalog_variants_for_cardno("058/095", _db=db,
                                       title_hint="PSA 10 Pokemon Super-Burst Impact #058/095 Umbreon")
    assert len(v) == 3, "英語版除外して日本語3件のはず"
    assert v[0]["product_id"] == "SM8-058", "キャラ名一致の変種が先頭に来ていない"


def test_collector_number_no_hint_returns_all(tmp_path):
    """title_hint 無しでも card_number_text で全変種を返す(ユーザーが目視で選ぶ)。"""
    db = _mkdb(tmp_path)
    v = mp.catalog_variants_for_cardno("058/095", _db=db)
    assert {c["product_id"] for c in v} == {"SM8-058", "SM9-058", "SM10-058"}


def test_setcode_path_unaffected(tmp_path):
    """セットコード形式(OP05-098)は従来どおり product_id 一致で引け、fallback を踏まない。"""
    db = _mkdb(tmp_path)
    v = mp.catalog_variants_for_cardno("OP05-098", _db=db)
    assert {c["product_id"] for c in v} == {"OP05-098", "OP05-098_L"}
    assert v[0]["product_id"] == "OP05-098"  # 完全一致が先頭


def test_no_match_returns_empty(tmp_path):
    """存在しないコレクター番号は空(推測で埋めない=fail-closed)。"""
    db = _mkdb(tmp_path)
    assert mp.catalog_variants_for_cardno("999/095", _db=db) == []
