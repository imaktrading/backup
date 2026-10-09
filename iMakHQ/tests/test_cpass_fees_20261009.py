# -*- coding: utf-8 -*-
"""SpeedPAK (EE…/EX…) の送料をセラーポータルから取って O列に入れる (2026-10-09)。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import cpass_fees as CF
import order_purchase_sync as O


def test_is_cpass_tracking():
    assert CF.is_cpass_tracking("EE1013103618068SX06010905F0N")
    assert CF.is_cpass_tracking("EX1013103323773FE06020002E0N")
    assert not CF.is_cpass_tracking("LX333090259JP") and not CF.is_cpass_tracking("")


def test_save_accumulates(tmp_path):
    p = str(tmp_path / "f.json")
    CF.save_from_extension({"fees": {"EE1013103618068SX06010905F0N": {"yen": 4295}}}, path=p)
    r = CF.save_from_extension({"fees": {"EE1013104028900SX06010906G0N": {"yen": 3142}, "bad": {"yen": 1}}}, path=p)
    assert r["new"] == 1 and r["total"] == 2


def test_targets_only_empty_speedpak_rows():
    rows = [["h"] * 26]
    def row(t, post=""):
        r = [""] * 26
        r[13], r[14] = t, post
        return r
    rows += [row("EE1013103618068SX06010905F0N"), row("LX333090259JP"), row("EE1013104028900SX06010906G0N", "3142")]
    assert O.ship_cost_targets(rows) == [(2, "EE1013103618068SX06010905F0N")]


def test_extension_registered():
    m = json.load(open(os.path.join(HERE, "..", "tools", "sellerhub_grab", "manifest.json"), encoding="utf-8"))
    assert any("cpass_fees.js" in c["js"] for c in m["content_scripts"])
