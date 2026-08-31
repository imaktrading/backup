# -*- coding: utf-8 -*-
"""出品の器はあるが在庫0の cert を、生きている出品と分けて扱う (2026-08-31)。

## 実害 (catalog 依頼 2026-08-29 → 追記 2026-08-31)
cert152976751 は 7/14 に出品後、仕入元が切れて数量0で取り下げ済み(器だけ残存)。
`already_listed_reason` は「itemID 非空 = 出品済」としか見ないため、二重出品ガードが
これを **まだ生きている出品**と同じ扱いで毎回黙って落としていた。
目視に8回出て8回とも OK と答えられ、8回とも何も起きなかった
(グローバル規約「silent drop 禁止・"正常"と書かない」に抵触)。

## 直し方
判定 (二重出品ガード) 自体は変えない。**同じ「落とす」でも理由が違う集合を分けて記録**し、
status_now.py (毎セッション必ず見る現在地) に出す。qty は funnel CSV (ローカル、
cull_end/shelf_evict と同じ) から見る。**eBay は叩かない**。
"""
import csv
import os
import sys

_HQ_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")
for _p in (_HQ_TOOLS, _TCG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sheet_io as SIO                                             # noqa: E402
import psa_to_csv as P                                              # noqa: E402
import status_now as SN                                             # noqa: E402

NL = chr(10)


def _rows(pairs):
    """(itemID, cert) のペア列 → build_cert_map が読める2次元配列 (ヘッダ行付き)。"""
    header = [""] * 9
    out = [header]
    for iid, cert in pairs:
        r = [""] * 9
        r[SIO.PRODUCT_COL_ITEMID] = iid
        r[SIO.PRODUCT_COL_CERT] = cert
        out.append(r)
    return out


# ── sheet_io.zero_qty_ghost_certs (純関数) ──────────────────────────
def test_zero_qty_is_ghost():
    all_values = _rows([("358000000001", "152976751")])
    got = SIO.zero_qty_ghost_certs(all_values, ["152976751"], {"358000000001": 0.0})
    assert got == {"152976751"}


def test_positive_qty_is_not_ghost():
    """在庫が残っているなら従来どおり (=生きている出品として止める)。"""
    all_values = _rows([("358000000001", "152976751")])
    got = SIO.zero_qty_ghost_certs(all_values, ["152976751"], {"358000000001": 3.0})
    assert got == set()


def test_unknown_qty_is_not_ghost_failclosed():
    """funnel に無い/分からない itemID は ghost にしない (fail-closed)。"""
    all_values = _rows([("358000000001", "152976751")])
    got = SIO.zero_qty_ghost_certs(all_values, ["152976751"], {})
    assert got == set()


def test_cert_without_itemid_is_not_ghost():
    all_values = _rows([])
    got = SIO.zero_qty_ghost_certs(all_values, ["152976751"], {"x": 0.0})
    assert got == set()


# ── psa_to_csv._latest_funnel_qty_map (ローカル funnel CSV 読取、eBay 不使用) ──
def _funnel(tmp_path, rows):
    p = tmp_path / "funnel_20260831.csv"
    lines = ["item_id,qty"] + [f"{iid},{qty}" for iid, qty in rows]
    p.write_text(NL.join(lines), encoding="utf-8")
    return str(tmp_path)


def test_funnel_qty_map_reads_latest(tmp_path):
    d = _funnel(tmp_path, [("358000000001", 0), ("358000000002", 5)])
    got = P._latest_funnel_qty_map(funnel_dir=d)
    assert got["358000000001"] == 0.0
    assert got["358000000002"] == 5.0


def test_funnel_qty_map_missing_dir_returns_empty(tmp_path):
    assert P._latest_funnel_qty_map(funnel_dir=str(tmp_path / "no_such_dir")) == {}


def test_ghost_check_never_touches_ebay():
    import inspect
    src = inspect.getsource(P._latest_funnel_qty_map)
    for banned in ("_fetch_active_live", "GetMyeBaySelling", "ActiveList", "anthropic", "requests."):
        assert banned not in src, banned


# ── psa_to_csv 側の配線 (2つの理由に分けて記録している) ──────────────
def test_extraction_records_ghost_separately_from_live_skip():
    src = open(os.path.join(_TCG, "psa_to_csv.py"), encoding="utf-8").read()
    assert 'record_cert_skips("same_cert_zero_qty_ghost", sorted(_ghost))' in src
    assert 'record_cert_skips("same_cert_already_listed", _live_skip)' in src
    assert "_ghost_certs(all_values, _skipped_cert, _latest_funnel_qty_map())" in src


# ── status_now.py の表示 (silent にしない) ──────────────────────────
def test_status_now_reads_the_ghost_ledger(tmp_path, monkeypatch):
    p = tmp_path / "extract_cert_skips.jsonl"
    lines2 = [
        '{"ts": "2026-08-29T09:00:00", "reason": "same_cert_already_listed", "certs": ["999"]}',
        '{"ts": "2026-08-30T09:00:00", "reason": "same_cert_zero_qty_ghost", "certs": ["152976751"]}',
    ]
    p.write_text(NL.join(lines2) + NL, encoding="utf-8")
    monkeypatch.setattr(SN, "CERT_SKIP_LEDGER", str(p))
    got = SN._zero_qty_ghost_certs()
    assert any("152976751" in ln for ln in got)
    assert not any("999" in ln for ln in got), "生きている出品の分まで出している"


def test_status_now_ghost_section_is_wired_into_the_report():
    src = open(os.path.join(os.path.dirname(os.path.abspath(SN.__file__)),
                            "status_now.py"), encoding="utf-8").read()
    assert "_zero_qty_ghost_certs()" in src
    assert "在庫0" in src
