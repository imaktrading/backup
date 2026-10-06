# -*- coding: utf-8 -*-
"""eBay 正規表記マスタ: 置き場を2か所見る / 読めない時は黙らせない (2026-10-06)。

経緯: マスタを `C:/dev/iMak_data/hq/requests/` に置いていたが、requests/ は KAGOYA に
同期されない。サーバーで監査が走ると読めず、`Hydreigon ex` → `Hydreigon Ex` のような
eBay 正規化済みの行を「カタログと違う」に倒して **正しい行を除外**していた。
しかも「マスタが無い」とはどこにも出なかった (= 黙って誤除外 = fail-closed の暴走)。
出典: hq/requests/2026-10-05_act_code_proposals_tcg.md 提案1
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iMakeBayAPI"))

import aspect_contract as ac                                   # noqa: E402
import csv_auditor as ca                                       # noqa: E402


def test_候補は新しい置き場が先で古い置き場も残っている():
    paths = [str(p).replace("\\", "/") for p in ac.EBAY_MASTER_CANDIDATES]
    assert paths[0].endswith("/hq/ebay_master/ebay_183454_facet_master_20260821.json")
    assert any("/hq/requests/" in p for p in paths[1:]), "古い置き場も当分は見る"


def test_読める置き場を選ぶ(tmp_path, monkeypatch):
    no = tmp_path / "ない.json"
    yes = tmp_path / "ある.json"
    yes.write_text('{"aspects": {"Card Name": {"all": ["Hydreigon Ex"]}}}', encoding="utf-8")
    monkeypatch.setattr(ac, "EBAY_MASTER_CANDIDATES", (no, yes))
    assert ac.ebay_master_path() == yes
    assert ac.load_ebay_master() == {"Card Name": {"all": ["Hydreigon Ex"]}}


def test_どれも無ければ先頭を返す_読み込みはNone(tmp_path, monkeypatch):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    monkeypatch.setattr(ac, "EBAY_MASTER_CANDIDATES", (a, b))
    assert ac.ebay_master_path() == a
    assert ac.load_ebay_master() is None


def test_読めない時は誤除外の恐れとして報告される(monkeypatch):
    monkeypatch.setattr(ca, "load_ebay_master", lambda *a, **k: None)
    assert ca._ebay_master_unreadable() is True
    monkeypatch.setattr(ca, "load_ebay_master", lambda *a, **k: {"Card Name": {}})
    assert ca._ebay_master_unreadable() is False
