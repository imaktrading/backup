#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""psa_to_csv: 非日本語版(ASIA/KOREAN/CHINESE)を out-of-scope skip (2026-07-02)。

ASIA 版 promo 等は日本版 catalog に解決せず missing_models に積まれ「catalog_add」として
永久 recurring 化していた(POKEMON ASIA 25TH ANNIVERSARY, seen×21)。catalog に足しても
当店は日本版のみ扱うため埋まらない → is_out_of_scope_language で早期 skip。won't-fix で
隠すのでなく生成ルール自体を賢くする方針(Gemini 諮問結論)。その回帰固定。
"""
import importlib.util
import os
import sys

_TCG_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG"))
_PSA = os.path.join(_TCG_DIR, "psa_to_csv.py")


def _load():
    if _TCG_DIR not in sys.path:
        sys.path.insert(0, _TCG_DIR)  # psa_to_csv の兄弟モジュール(pokemon_card_jp 等)解決用
    spec = importlib.util.spec_from_file_location("psa_to_csv_mod", _PSA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_asia_brand_out_of_scope():
    m = _load()
    assert m.is_out_of_scope_language("POKEMON ASIA 25TH ANNIVERSARY PROMO")
    assert m.is_out_of_scope_language("POKEMON KOREAN SWORD & SHIELD")
    assert m.is_out_of_scope_language("POKEMON CHINESE PROMO")


def test_japanese_brand_in_scope():
    m = _load()
    # 日本版は対象内(誤除外しない)
    assert not m.is_out_of_scope_language("POKEMON JAPANESE M-P PROMO")
    assert not m.is_out_of_scope_language("ONE PIECE JAPANESE PROMOS")
    assert not m.is_out_of_scope_language("POKEMON JAPANESE SV10-GLORY OF TEAM ROCKET")


def test_empty_and_no_language_marker_in_scope():
    m = _load()
    # 言語マーカー無しは skip しない(過剰除外=recall損 防止)
    assert not m.is_out_of_scope_language("")
    assert not m.is_out_of_scope_language("POKEMON SV10 GLORY")


# --- 2026-07-05: catalog-aware 化の回帰 (cert 142931332 誤 skip 事故) ---

def test_asia_brand_but_resolves_to_jp_catalog_not_skipped():
    """PSA が日本版 Golden Box(S8a-G) を "ASIA 25TH ANNIVERSARY" と誤ラベルしても、
    日本版 catalog に解決できれば skip しない(false-positive skip = recall 損 防止)。"""
    m = _load()
    # lookup が解決(= 日本版 catalog hit)を返すケース
    hit = lambda brand, cn, subj: {"card_id": "S8a-G-005", "rarity": "RRR"}
    assert not m.should_skip_out_of_scope_language(
        "POKEMON ASIA 25TH ANNIVERSARY PROMO", "Pokemon", "005/015",
        "PIKACHU V 25TH ANNIV-GOLDEN BOX", lookup_pokemon_fn=hit)


def test_asia_brand_unresolved_still_skipped_failclosed():
    """日本版 catalog に解決できない真の ASIA/中国/韓国版は従来通り skip(fail-closed 維持)。"""
    m = _load()
    miss = lambda brand, cn, subj: None
    assert m.should_skip_out_of_scope_language(
        "POKEMON ASIA 25TH ANNIVERSARY PROMO", "Pokemon", "005/015",
        "SOME ASIA-ONLY CARD", lookup_pokemon_fn=miss)
    # 非Pokemon の ASIA/KOREAN/CHINESE も従来通り skip
    assert m.should_skip_out_of_scope_language(
        "POKEMON KOREAN SWORD & SHIELD", "Pokemon", "001", "PIKACHU",
        lookup_pokemon_fn=miss)


def test_japanese_brand_never_skipped_regardless_of_lookup():
    """JAPANESE brand は lookup 有無に関係なく skip しない(既存挙動不変)。"""
    m = _load()
    miss = lambda brand, cn, subj: None
    assert not m.should_skip_out_of_scope_language(
        "POKEMON JAPANESE M-P PROMO", "Pokemon", "005", "PIKACHU",
        lookup_pokemon_fn=miss)


def test_lookup_exception_falls_back_to_skip():
    """lookup が例外でも fail-closed(skip)に倒す(誤出品より skip 優先)。"""
    m = _load()
    def boom(brand, cn, subj):
        raise RuntimeError("db down")
    assert m.should_skip_out_of_scope_language(
        "POKEMON ASIA 25TH ANNIVERSARY PROMO", "Pokemon", "005", "X",
        lookup_pokemon_fn=boom)
