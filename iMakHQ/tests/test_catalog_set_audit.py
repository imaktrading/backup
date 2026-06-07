# -*- coding: utf-8 -*-
"""カタログ set_name_ebay 内部整合監査 (catalog_set_audit) の判定ロジック。

2026-06-07: set_name_ebay 誤りが「出品後にバイヤー指摘で発覚」した反省から、
出品前/カタログ更新時に内部矛盾を検出するゲートを新設。本テストは世代判定の核を守る。
"""
import importlib.util
import os

_M = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools", "catalog_set_audit.py"))


def _load():
    spec = importlib.util.spec_from_file_location("catalog_set_audit_t", _M)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pid_era():
    a = _load()
    assert a.pid_era("M3-097") == "MEGA"
    assert a.pid_era("DPt3-100") == "Legacy(DP/HGSS)"
    assert a.pid_era("XY2-085") == "XY"
    assert a.pid_era("SM9-001") == "Sun & Moon"
    assert a.pid_era("SV2P-075") == "Scarlet & Violet"
    assert a.pid_era("S9-100") == "Sword & Shield"
    assert a.pid_era("BW9-001") == "Black & White"


def test_eb_era():
    a = _load()
    assert a.eb_era("Sun & Moon—Ultra Prism") == "Sun & Moon"
    assert a.eb_era("Scarlet & Violet—Destined Rivals") == "Scarlet & Violet"
    assert a.eb_era("Nihil Zero") == "bare/other"      # 新弾(prefix無)は世代判定対象外


def test_cross_era_is_detectable():
    a = _load()
    # DPt3(Legacy) が Scarlet & Violet set名 = 世代不一致 (今日の実バグ型)
    assert a.pid_era("DPt3-100") != a.eb_era("Scarlet & Violet—Destined Rivals")
    # M3(MEGA) が Sun & Moon = 不一致 (buyer指摘の型)。MEGAはbare運用なので era!=eb で検出
    assert a.pid_era("M3-097") != a.eb_era("Sun & Moon—Ultra Prism")
