# -*- coding: utf-8 -*-
"""PSA 再仕入れのボタン件数を、押した時と同じ外し方に揃える (2026-10-09)。

ユーザー「再仕入れ何回やってもボタン消えないんだけど」。押すと「候補0本」や「未発送の注文がある」で
飛ばされる札が、件数には残り続けていた。押した時に候補0本だった札を記録し、同じ日のうちは件数から外す。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import psa_resource_gate as G                                   # noqa: E402


def test_候補0本の記録は今日だけ効く(tmp_path):
    p = str(tmp_path / "nocand.json")
    G._save_nocand(["820000000001", "?", ""], path=p)
    import datetime as dt
    today = dt.date.today().isoformat()
    assert G.load_nocand_today(today, path=p) == {"820000000001"}
    assert G.load_nocand_today("2000-01-01", path=p) == set()


def test_記録が無ければ空(tmp_path):
    assert G.load_nocand_today("2026-10-09", path=str(tmp_path / "none.json")) == set()
