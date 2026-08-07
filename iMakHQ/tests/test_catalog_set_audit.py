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


def test_card_total_extract():
    a = _load()
    assert a.card_total("097/080") == "080"
    assert a.card_total("050/156") == "156"
    assert a.card_total("") == ""


def test_row_set_issue_total_mismatch():
    a = _load()
    ref = {"Sun & Moon—Ultra Prism": "156", "Nihil Zero": "080"}
    # Ultra Prism(総数156)なのに /080 → 誤マップ検出 (今日のbuyer指摘の型)
    assert a.row_set_issue("Sun & Moon—Ultra Prism", "097/080", ref) is not None
    # 正: Nihil Zero /080 → None
    assert a.row_set_issue("Nihil Zero", "097/080", ref) is None
    # 参照に無いset / 番号不明 → 判定不能 None
    assert a.row_set_issue("Unknown Set", "001/100", ref) is None
    assert a.row_set_issue("Nihil Zero", "", ref) is None


def test_cross_era_is_detectable():
    a = _load()
    # DPt3(Legacy) が Scarlet & Violet set名 = 世代不一致 (今日の実バグ型)
    assert a.pid_era("DPt3-100") != a.eb_era("Scarlet & Violet—Destined Rivals")
    # M3(MEGA) が Sun & Moon = 不一致 (buyer指摘の型)。MEGAはbare運用なので era!=eb で検出
    assert a.pid_era("M3-097") != a.eb_era("Sun & Moon—Ultra Prism")


def test_excluded_pid():
    a = _load()
    # cardID-prefix は不正product_id=整合チェック対象外
    assert a._is_excluded_pid("cardID12345-080") is True
    assert a._is_excluded_pid("SM9-001") is False
    assert a._is_excluded_pid("") is False


def test_multi_total_whitelist_in_row_issue():
    a = _load()
    # "Sun & Moon" は verified-legit な多total (SM1p/051 と SM1S/060 が公式EN同名)
    assert "Sun & Moon" in a._KNOWN_MULTI_TOTAL_OK
    ref = {"Sun & Moon": "060"}
    # 少数派 /051 (SM1p) を /060基準で誤ブロックしない (whitelist で None)
    assert a.row_set_issue("Sun & Moon", "045/051", ref) is None
    # whitelist外の本物の誤マップは従来どおり検出 (回帰防止)
    ref2 = {"Sun & Moon—Ultra Prism": "156"}
    assert a.row_set_issue("Sun & Moon—Ultra Prism", "097/080", ref2) is not None


def test_audit_whitelist_and_cardid_skip(tmp_path):
    a = _load()
    import json
    import sqlite3
    db = str(tmp_path / "t.sqlite")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products(product_id TEXT, set_name TEXT, specs TEXT, category TEXT)")
    rows = [
        # Sun & Moon 多total (whitelist) → [3] に出ない
        ("SM1p-045", "サン＆ムーン", {"set_name_ebay": "Sun & Moon", "card_number_total": "051"}),
        ("SM1S-010", "コレクションサン", {"set_name_ebay": "Sun & Moon", "card_number_total": "060"}),
        # cardID 不正レコード → [3] 対象外
        ("cardID999-080", "x", {"set_name_ebay": "Sword & Shield—Lost Origin", "card_number_total": "080"}),
        ("S11-050", "ロストアビス", {"set_name_ebay": "Sword & Shield—Lost Origin", "card_number_total": "100"}),
        # 本物の多total誤マップ (whitelist外) → [3] に出る (回帰防止)
        ("SM12-035", "オルタージェネシス", {"set_name_ebay": "Alter Genesis", "card_number_total": "095"}),
        ("M3-097", "ムニキスゼロ", {"set_name_ebay": "Alter Genesis", "card_number_total": "080"}),
    ]
    for pid, sn, sp in rows:
        con.execute("INSERT INTO products VALUES(?,?,?,'pokemon_tcg')", (pid, sn, json.dumps(sp, ensure_ascii=False)))
    con.commit()
    con.close()
    _, _, total_viol = a.audit(db)
    sets_flagged = {v[0] for v in total_viol}
    assert "Sun & Moon" not in sets_flagged          # whitelist
    assert "Sword & Shield—Lost Origin" not in sets_flagged  # cardID除外で単一total化
    assert "Alter Genesis" in sets_flagged            # 本物の誤マップは検出 (回帰防止)
