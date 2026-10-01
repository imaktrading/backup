"""補URL探索: ワンピースの bandai 側の行を、カタログの版の対応表で公式の行に読み替える (2026-10-01)。

bandai 側の行 (EB01-057_OP11 等) は入手元が英語のセット名で、版 (SP/パラレル) も KEY から読めず、
検索語に版が乗らなかった。対応表に載る物だけ公式の行で引く。載らない物は今までどおり。
"""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import mercari_psa_resource as mp  # noqa: E402


def _setup(tmp_path):
    db = str(tmp_path / "p.sqlite")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (product_id, name_jp, images, set_name, specs, category)")
    con.execute("INSERT INTO products VALUES (?,?,?,?,?,?)",
                ("EB01-057_OP11", "ナミ", "[]", "BOOSTER -A FIST OF DIVINE SPEED- [OP-11]",
                 json.dumps({"rarity": "SR"}), "one_piece_tcg"))
    con.execute("INSERT INTO products VALUES (?,?,?,?,?,?)",
                ("EB01-057_p2", "ナミ", "[]", None,
                 json.dumps({"rarity": "SPカード", "get_info": "ブースターパック 神速の拳【OP-11】",
                             "variant_type": "alt_art"}, ensure_ascii=False), "one_piece_tcg"))
    con.commit()
    con.close()
    mp_path = str(tmp_path / "map.json")
    with open(mp_path, "w", encoding="utf-8") as f:
        json.dump({"map": {"EB01-057_OP11": "EB01-057_p2"}}, f)
    return db, mp_path


def test_official_variant_key(tmp_path, monkeypatch):
    _, path = _setup(tmp_path)
    assert mp.official_variant_key("one_piece_tcg:EB01-057_OP11", _path=path) == "one_piece_tcg:EB01-057_p2"
    assert mp.official_variant_key("one_piece_tcg:EB01-057", _path=path) == "one_piece_tcg:EB01-057"
    assert mp.official_variant_key("pokemon_tcg:EB01-057_OP11", _path=path) == "pokemon_tcg:EB01-057_OP11"
    assert mp.official_variant_key("one_piece_tcg:X", _path=str(tmp_path / "none.json")) == "one_piece_tcg:X"


def test_meta_and_print_word_use_official_row(tmp_path, monkeypatch):
    db, path = _setup(tmp_path)
    monkeypatch.setattr(mp, "OP_VARIANT_MAP_PATH", path)
    m = mp.card_meta_for_key("one_piece_tcg:EB01-057_OP11", {}, db)
    assert m["official_key"] == "one_piece_tcg:EB01-057_p2"
    assert m["get_info"] == "ブースターパック 神速の拳【OP-11】"
    assert m["rarity"] == "SPカード"
    assert m["set"] == "BOOSTER -A FIST OF DIVINE SPEED- [OP-11]"   # 公式の行は set 空 → 元の行の set
    assert mp.print_word_for_key(m["official_key"], m["hint"]) == "SP"
    # 読み替え前の KEY では版が読めない (= 直す前の状態)
    assert mp.print_word_for_key("one_piece_tcg:EB01-057_OP11", m["hint"]) == ""


def test_pack_code_without_booster_word_is_pack():
    """公式の入手元は「双璧の覇者【OP-06】」のように「ブースター」を書かない。弾コードでパックと読む。"""
    for gi in ("双璧の覇者【OP-06】", "ONE PIECE CARD THE BEST【PRB-01】", "メモリアルコレクション【EB-01】"):
        assert mp.print_word_for_key("one_piece_tcg:OP06-042_p1", ["", gi, "", "alt_art", "L", ""]) == "パラレル"
    assert mp.print_word_for_key("one_piece_tcg:OP02-013_p5", ["", "2nd ANNIVERSARY SET", "", "alt_art", "SR", ""]) == ""
    assert mp.print_word_for_key("one_piece_tcg:ST13-001_p1", ["", "3兄弟の絆【ST-13】", "", "alt_art", "L", ""]) == ""
    # プロモの SP は rarity が「SP P」
    assert mp.print_word_for_key("one_piece_tcg:P-105_p2",
                                 ["", "ブースターパック 神の島の冒険【OP-15】", "", "alt_art", "SP P", ""]) == "SP"
