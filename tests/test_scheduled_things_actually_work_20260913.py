# -*- coding: utf-8 -*-
"""作ってあるのに動いていなかった物 (2026-09-13 横断確認で発覚)。

ユーザー「作って終わりじゃなくて、ちゃんと動くか確認しないと」。

1. PSA の売れ筋順が **219件中0件** に点が付く。鍵 (AI列) は出品後に入る物で、
   前段で「既出品の2枚目」を落とすようになってから、残る候補は全部 鍵が無い = 構造的に0件。
   → 鍵が無い候補は PSA データの手元キャッシュから product_id を引く
2. 夜の再仕入れ照合がメルカリを **1晩10件** しか調べず、34〜41件が毎晩持ち越し
   (再仕入れ可が1週間 14〜16件のまま収束しない) → 夜間は40件 (1走行の安全上限60の内側)
3. PSA データを夜に貯めるタスクが 8/19 に作られてから **一度も動いていない (Disabled)**
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakTCG", ROOT / "iMakHQ" / "tools", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import tcg_batch_select as T  # noqa: E402


def test_demand_uses_psa_data_when_sheet_key_is_missing(tmp_path, capsys):
    funnel = tmp_path / "funnel_20260913.csv"
    # demand_by_set が読む形は既存テストに合わせず、ここでは関数を差し替えて点の付き方だけ見る
    funnel.write_text("title\n", encoding="utf-8")
    orig = T.demand_by_set
    T.demand_by_set = lambda rows: {"SV5K": 100.0, "OP09": 50.0}
    try:
        f = T.build_demand_of(["111", "222", "333"], funnel_glob=str(tmp_path / "funnel_*.csv"),
                              key_map={"111": "one_piece_tcg:OP09-001", "222": "", "333": ""},
                              fallback_key_of={"222": "SV5K-078"}.get)
    finally:
        T.demand_by_set = orig
    assert f("111") == 50.0, "シートの鍵がある物は今までどおり"
    assert f("222") == 100.0, "鍵が無くても PSA データの product_id から点が付く"
    assert f("333") is None
    out = capsys.readouterr().out
    assert "2/3件に点が付きます" in out and "PSAデータから 1件" in out


def test_nightly_restock_batch_is_not_the_default_ten():
    bat = io.open(ROOT / "iMakHQ" / "tools" / "run_hoju_search.bat", encoding="ascii").read()
    assert "set RESTOCK_SCRAPE_BATCH=40" in bat
    i = bat.index("set RESTOCK_SCRAPE_BATCH=40")
    j = bat.index("python -u psa_resource_gate.py --nightly")   # 先頭の説明コメントではなく実際の呼び出し
    assert i < j, "照合を呼ぶ前に件数を設定していない"


def test_batch_stays_inside_the_safety_cap():
    src = io.open(ROOT / "iMakHQ" / "tools" / "psa_resource_gate.py", encoding="utf-8").read()
    assert 'os.environ.get("RESTOCK_MAX_SCRAPE", "60")' in src


def test_bat_files_stay_ascii():
    """日本語を書くと cmd.exe が文字化けしてコマンドとして読み、夜間処理ごと動かなくなる (2026-07-30 実害)。"""
    for name in ("run_hoju_search.bat", "run_psa_cache_warm.bat"):
        raw = (ROOT / "iMakHQ" / "tools" / name).read_bytes()
        assert all(b < 128 for b in raw), name


def test_bat_files_keep_crlf_line_endings():
    """★2026-09-13: 夜間バッチに1行足した時、書き戻しで改行が CRLF → LF に変わっていた (CR 240個 → 0個)。
    cmd.exe は LF だけのバッチで `goto :label` の飛び先を見失うことがあり、夜間処理が途中で止まる。
    """
    for name in ("run_hoju_search.bat", "run_psa_cache_warm.bat"):
        raw = (ROOT / "iMakHQ" / "tools" / name).read_bytes()
        lf = raw.count(b"\n")
        crlf = raw.count(b"\r\n")
        assert lf and crlf == lf, f"{name}: 改行 {lf}個のうち CRLF は {crlf}個"
