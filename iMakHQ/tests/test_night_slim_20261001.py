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


def test_weekly_gate_runs_every_six_days(tmp_path):
    import sys
    from datetime import datetime
    sys.path.insert(0, os.path.dirname(BAT))
    import weekly_gate as W
    p = str(tmp_path / "w.json")
    t0 = datetime(2026, 10, 1, 23, 40)
    assert W.main(["demand_winners", "--check"], path=p, now=t0) == 0        # 初回は走る
    W.main(["demand_winners", "--done", "1"], path=p, now=t0)               # 失敗は記録しない
    assert W.main(["demand_winners", "--check"], path=p, now=t0) == 0
    W.main(["demand_winners", "--done", "0"], path=p, now=t0)
    assert W.main(["demand_winners", "--check"], path=p, now=datetime(2026, 10, 2, 2, 0)) == 1   # 0時またぎの再開でも飛ばす
    assert W.main(["demand_winners", "--check"], path=p, now=datetime(2026, 10, 7, 23, 40)) == 0


def test_weekly_steps_and_removed_steps():
    b = _bat()
    for name in ("funnel_diff", "demand_winners", "restock_worklist", "ut_demand_words", "noclick_targets"):
        assert f"weekly_gate.py {name} --check" in b, name
    assert "python -u listing_funnel.py" in b and "listing_funnel --check" in b    # ファネル本体は毎晩
    assert "python -u hoju_naked_sheet.py" not in b                              # 読み手なし
    assert "python -u sheet_listable_flag.py --write" not in b                   # 出品くんが毎回塗り直す


def test_usb_copy_runs_right_after_daily_zip():
    """USB へは毎朝の zip ができた直後に続けて写す (別予約 5:30 だと、遅れた日に前日の zip を写していた)。"""
    src = io.open(os.path.join(os.path.dirname(BAT), "data_backup.py"), encoding="utf-8").read()
    i = src.index('st["pruned"] = prune()')
    assert 'usb_backup.py' in src[i:i + 1200] and 'st["usb"]' in src[i:i + 1200]
