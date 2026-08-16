# -*- coding: utf-8 -*-
"""Porter 生成の 1回あたり上限 と「直らないAPIエラーで即停止」(2026-08-17)。

★事故: Anthropic の残高切れで **76件中70件が全部失敗**した。直らないエラーなのに
  1件ずつ画像を取り直して最後まで走り、時間だけ溶けた。
  併せてユーザー指示「(Porterは)15件で」= 1回に作る件数の上限を入れる。
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys

_SRC = r"C:\dev\iMak\iMakMercari\mercari_to_ebay_csv.py"


def _load():
    """import 時に 'API key.txt' を cwd から読むので、そのフォルダで読み込む。"""
    d = os.path.dirname(_SRC)
    if d not in sys.path:
        sys.path.insert(0, d)
    cwd = os.getcwd()
    os.chdir(d)
    try:
        spec = importlib.util.spec_from_file_location("_hq_mercari_to_ebay", _SRC)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    finally:
        os.chdir(cwd)
    return mod


M = _load()


def test_fatal_errors_are_recognized():
    """課金・認証・権限は人が直すまで失敗し続ける → リトライも継続もしない。"""
    for msg in ("Your credit balance is too low to access the Anthropic API",
                "billing error", "invalid x-api-key", "authentication_error",
                "permission_error", "Quota exceeded"):
        assert M.is_fatal_api_error(Exception(msg)), msg


def test_transient_errors_are_not_fatal():
    """一時的なものまで止めない (次の1件で回復することがある)。"""
    for msg in ("overloaded_error", "Connection reset by peer",
                "Read timed out", "500 Internal Server Error"):
        assert not M.is_fatal_api_error(Exception(msg)), msg


def test_run_stops_on_fatal_error():
    """走行そのものを止める配線があること (残りを空振りさせない)。"""
    src = open(_SRC, encoding="utf-8", errors="replace").read()
    assert "except FatalApiError" in src
    assert re.search(r"except FatalApiError[\s\S]{0,400}break", src), "止めずに続けている"
    # 出来た分は捨てない (break であって return/exit ではない)
    assert "raise FatalApiError" in src


def test_porter_has_a_per_run_cap():
    """★ユーザー指示「15件で」。件数は if 分岐でなくカテゴリ設定に持たせる。"""
    assert M.SHEET_REGISTRY["porter"].get("max_items") == 15
    src = open(_SRC, encoding="utf-8", errors="replace").read()
    assert 'get("max_items")' in src, "設定を読んでいない"
    assert "rows = rows[:_cap]" in src, "上限を適用していない"
    assert '"--limit"' in src, "--limit で上書きできない"


def test_other_sheets_are_unlimited_unless_configured():
    """他カテゴリは今まで通り全件 (勝手に絞らない)。"""
    for k, cfg in M.SHEET_REGISTRY.items():
        if k != "porter":
            assert "max_items" not in cfg, k


def test_upload_csv_has_no_bom():
    """eBay 入稿CSV は BOM なし (規約)。

    BOM を付けると先頭の3バイトが1列目の見出し `*Action(...)` にくっつき、
    eBay から別の列名に見える = その列が丸ごと無視されて入稿エラーになりうる。
    PSA 側 (psa_to_csv) は BOM なしで揃っている。
    """
    src = open(_SRC, encoding="utf-8", errors="replace").read()
    i = src.index("with open(OUTPUT_CSV")
    line = src[i:src.index(chr(10), i)]
    assert 'encoding="utf-8"' in line and "utf-8-sig" not in line, line


def test_existing_output_csvs_have_no_bom():
    """出力済みの入稿CSVにも BOM が残っていないこと。"""
    import glob
    bad = []
    for p in sorted(glob.glob(r"C:\dev\iMak\iMakHQ\csv_output\*_upload_2026081*.csv")):
        with open(p, "rb") as f:
            if f.read(3) == b"" + bytes([0xEF, 0xBB, 0xBF]):
                bad.append(os.path.basename(p))
    assert not bad, "BOM 付きの入稿CSV: " + ", ".join(bad)
