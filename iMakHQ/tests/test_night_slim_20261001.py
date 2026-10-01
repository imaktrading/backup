# -*- coding: utf-8 -*-
"""夜の束のスリム化 (2026-10-01 全体点検・ユーザー「いい機会だ、全体点検やる！」)。"""
import io
import os

BAT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "run_hoju_search.bat")


def _bat():
    return io.open(BAT, encoding="ascii").read()


def test_zero_backup_search_is_resumable():
    """補0本の探索も night_step で囲む。再開のたびに同じ30件を探し直していた (10/01 約1時間)。"""
    b = _bat()
    chk = b.index("night_step.py hoju psa_hoju_fill.search.--limit=30 --check")
    loop = b.index("python -u psa_hoju_fill.py search --limit=30")
    ok = b.index("night_step.py hoju psa_hoju_fill.search.--limit=30 --done 0")
    assert chk < loop < ok
    assert "|| goto :topup" in b[chk:loop]


def test_pricedown_uses_listing_cache_before_getitem():
    """値下げ余地の現価格は出品一覧のキャッシュから。GetItem 439回 (約20分) を叩き直していた。"""
    src = io.open(os.path.join(os.path.dirname(BAT), "noconvert_pricedown.py"), encoding="utf-8").read()
    assert "_A._fetch_live(use_cache=True)" in src
    assert "cur, ccy = _price(r.get(\"item_id\"))" in src
    assert "return fetch_listing_price(iid)" in src          # 一覧に無い物だけ従来どおり


def test_kuji_detail_runs_once():
    """一番くじの候補集め・詳細取りは run_kuji_night (live 40 / detail 200) の1回だけ。
    5 (live 10) と 5b (detail 120) は同じ処理の二重だった (約10分)。"""
    b = _bat()
    assert "ichibankuji_restock.py prefetch-live 10" not in b
    assert "ichibankuji_restock.py prefetch-detail 120" not in b
    assert "python -u run_kuji_night.py" in b
    assert "python -u ichibankuji_restock.py prefetch 10" in b      # 在庫切れの候補集め (別物) は残す
