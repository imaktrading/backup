"""夜の先回り: 引けない物のうち まだ頼んでいない鑑定番号だけを頼む (2026-10-16 ユーザー「夜のうちにやっといて」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_preflight_nightly as N  # noqa: E402


def _r(cert, st):
    return {"cert": cert, "status": st, "category": "pokemon_tcg", "brand": "B", "subject": "S", "num": "1"}


def test_only_unrequested_misses_are_asked():
    rs = [_r("1", "RESOLVED"), _r("2", "REVIEW"), _r("3", "GAP"), _r("4", "OUT-OF-SCOPE"),
          _r("5", "INDEX-FAILURE"), _r("6", "AMBIGUOUS")]
    got = [r["cert"] for r in N.pick_new(rs, {"3": "2026-10-16"})]
    assert got == ["2", "5", "6"]


def test_request_has_two_sections_and_lists_certs():
    t = N.request_text("2026-10-17", [_r("2", "REVIEW")], 300, 120, {"RESOLVED": 100, "REVIEW": 1})
    assert "## 既に判明していること" in t and "## 聞きたいこと" in t
    assert "cert 2 " in t and "① カタログ側" in t


def test_bat_runs_it_after_the_prefetch():
    bat = open(os.path.join(os.path.dirname(__file__), "..", "tools", "run_psa_cache_warm.bat"), encoding="ascii").read()
    assert bat.index("psa_cache_warm.py --limit") < bat.index("psa_preflight_nightly.py") < bat.index("psawarm --end")
