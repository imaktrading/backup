# -*- coding: utf-8 -*-
"""決着済みの値は赤から外す / 新しい値は赤のまま.

依頼: `requests/2026-10-02_monthly_settled_values_exclude_go.md` [IMPLEMENT-GO]

仕上げ (`finish_ingest.py`) は「変換表に無い値」の件数をそのまま終了コードにしていたので、
決着済みの天井が残っているだけで毎月 NG(1) が出て、月次が失敗していると読まれていた
(総点検の28番)。★**新しい値を黙って緑にしない**ことが肝なので、両方向を固定する。
"""
import importlib.util
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "ebay_filter_map" / "_settled_unmapped.yaml"


def _mod():
    spec = importlib.util.spec_from_file_location(
        "_fi", ROOT / "tools" / "finish_ingest.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_every_entry_has_a_reason():
    """`why` の無い行は載せない (面倒だから外した、を防ぐ)."""
    t = yaml.safe_load(TABLE.read_text(encoding="utf-8"))
    for cat, fields in t.items():
        for field, r in (fields or {}).items():
            assert (r.get("why") or "").strip(), f"{cat}/{field} に why が無い"


def test_settled_values_are_not_red():
    m = _mod()
    u = Counter({"stage='V進化'": 279, "stage='レベルアップ'": 73})
    settled, reported, open_ = m.split_unmapped("pokemon_tcg", u)
    assert sum(settled.values()) == 352 and not open_


def test_suffix_marks_are_not_red():
    m = _mod()
    settled, _, open_ = m.split_unmapped(
        "gundam_tcg", Counter({"rarity='C+'": 62, "rarity='LR++'": 5}))
    assert sum(settled.values()) == 67 and not open_
    settled, _, open_ = m.split_unmapped(
        "dragonball_scg", Counter({"rarity='SR★'": 3}))
    assert sum(settled.values()) == 3 and not open_


def test_new_value_stays_red():
    """★表に載っていない値は赤のまま."""
    m = _mod()
    settled, reported, open_ = m.split_unmapped(
        "gundam_tcg", Counter({"rarity='ZZZ'": 1, "rarity='C+'": 2}))
    assert open_ == {"rarity='ZZZ'": 1}
    assert sum(settled.values()) == 2


def test_name_en_is_reported_but_not_red():
    """英語版が出ていない行は埋める手が無い。赤にしないが件数は出す."""
    m = _mod()
    settled, reported, open_ = m.split_unmapped(
        "pokemon_tcg", Counter({"name_en='ギリー'": 3}))
    assert reported == {"name_en='ギリー'": 3} and not open_ and not settled


def test_unknown_category_keeps_everything_red():
    """表に無いカテゴリは今までどおり全部 赤 (fail-closed)."""
    m = _mod()
    _, _, open_ = m.split_unmapped("yugioh_tcg", Counter({"rarity='X'": 1}))
    assert open_ == {"rarity='X'": 1}
