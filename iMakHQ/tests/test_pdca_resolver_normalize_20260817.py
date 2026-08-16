# -*- coding: utf-8 -*-
"""カタログに在るのに「未登録」と言い続けるのを止める (2026-08-17)。

★事故: OP12-034 と 001/032(CLF) が **5日連続**「catalog 未登録」として再掲され、
  カタログに催促が飛び続けていた。実測すると **どちらも catalog に実在**
  (`product_id='OP12-034'` / `CLF-001`)。
  原因はカタログ側ではなく、こちらの照合。queue の item_id は missing_models.csv 由来の
  崩れた長文字列 ("OP12-034 psa10 ペローナ SR [OP12-034](プロモ…") で、
  resolver が product_id の完全一致しか見ていなかったため永久に外れていた。

★fail-closed: 印刷番号 (001/032) だけでは閉じない。別セットの同番号を
  「解決済」にしてしまうため、セット記号との組でだけ照合する。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys

_TOOLS = r"C:\dev\iMak\iMakHQ\tools"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_hq_pdca_store_norm", os.path.join(_TOOLS, "pdca_store.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    if _TOOLS not in sys.path:
        sys.path.insert(0, _TOOLS)
    spec.loader.exec_module(m)
    return m


P = _load()


def test_setcode_is_extracted_from_a_messy_string():
    """崩れた文字列からカード番号を取り出す (純関数)。"""
    c = P.candidate_ids("OP12-034 psa10 ペローナ SR [OP12-034](プロモーションカード)")
    assert "OP12-034" in c["ids"]
    c2 = P.candidate_ids("001/032 【PSA10】ポケモンカード フシギダネ CLF 001/032")
    assert c2["numbers"] == ["001/032"] and "CLF" in c2["hints"]


def _db(tmp_path, rows):
    p = tmp_path / "products.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE products (product_id TEXT, alias_of TEXT, specs TEXT)")
    con.executemany("INSERT INTO products VALUES (?,?,?)", rows)
    con.commit(); con.close()
    return str(p)


def test_registered_card_closes_even_with_a_messy_id(tmp_path):
    """catalog に在れば、文字列が崩れていても解決済とみなす。"""
    db = _db(tmp_path, [("OP12-034", None, "{}"),
                        ("CLF-001", None, json.dumps({"card_number_text": "001/032"}))])
    r = P.make_catalog_resolver(db)
    assert r("one_piece_tcg", "OP12-034 psa10 ペローナ SR [OP12-034](プロモ") is True
    assert r("pokemon_tcg", "001/032 【PSA10】フシギダネ CLF 001/032") is True


def test_unregistered_card_stays_open(tmp_path):
    """本当に無いものは閉じない (催促を消してはいけない)。"""
    db = _db(tmp_path, [("OP12-034", None, "{}")])
    r = P.make_catalog_resolver(db)
    assert r("one_piece_tcg", "ZZ99-999 存在しないカード") is False
    assert r("pokemon_tcg", "cert150639361 POKEMON CROWN ZENITH") is False


def test_printed_number_alone_does_not_close(tmp_path):
    """★印刷番号だけで閉じない。別セットの同番号を解決済にしないため。"""
    db = _db(tmp_path, [("CLF-001", None, json.dumps({"card_number_text": "001/032"}))])
    r = P.make_catalog_resolver(db)
    # セット記号のヒントが無い → 閉じない
    assert r("pokemon_tcg", "001/032 なにかのカード") is False
    # 別セットの記号しか無い → 閉じない
    assert r("pokemon_tcg", "001/032 SV1a のカード") is False
