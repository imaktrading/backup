"""Regression: 2026-06-09 TCG短タイトルを catalog 実ファクト(年/レアリティ/set code)で補強.

短タイトル(<70)が SEO 機会損失。TOPセラーが使う year/rarity/set_code は catalog にある事実なので、
refine_title 後 (最終段) に決定論で足す。捏造しない: facts 無ければ伸ばさない / 80字超えない。
"""
import importlib.util
import sys
from pathlib import Path

_TCG = Path(__file__).resolve().parent.parent / "iMakTCG"
if str(_TCG) not in sys.path:
    sys.path.insert(0, str(_TCG))


def _load():
    spec = importlib.util.spec_from_file_location("psa_to_csv", str(_TCG / "psa_to_csv.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


P = _load()


def test_pads_with_year_rarity_setcode():
    t = "PSA 10 Pokemon MEGA Dream ex #205/193 Team Rocket's Mimikyu Card"  # 64
    out = P._pad_title_with_facts(t, "2025", "AR", "M2a")
    assert "Art Rare" in out and "2025" in out and len(out) <= 80 and len(out) > len(t)


def test_no_fabrication_unmapped_rarity():
    # MA は map に無い → rarity足さない (捏造しない)
    t = "PSA 10 Pokemon MEGA Dream ex #229/193 Hawlucha Ex Card"
    out = P._pad_title_with_facts(t, None, "MA", "M2a")
    assert "Rare" not in out.replace("Card", "")   # rarity語は付かない
    assert out.endswith("M2a")                       # set_code は付く


def test_no_year_when_absent_or_default():
    # year が None/非4桁 → 足さない (default 2025 捏造防止)
    t = "PSA 10 Pokemon X #001/100 Foo Card"
    out = P._pad_title_with_facts(t, None, "SR", "SV1")
    assert "2025" not in out and "Super Rare" in out


def test_never_exceeds_80_and_skips_when_long():
    long = "PSA 10 Pokemon Scarlet & Violet Crown Zenith #100/172 Origin Forme Dialga V"  # ~74
    out = P._pad_title_with_facts(long, "2022", "SR", "S12a")
    assert len(out) <= 80


def test_unchanged_when_already_70():
    t = "A" * 72
    assert P._pad_title_with_facts(t, "2025", "SR", "M1S") == t
