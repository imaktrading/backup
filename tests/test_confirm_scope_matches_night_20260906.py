# -*- coding: utf-8 -*-
"""目視の対象は「夜間が実際に探している広さ」を超えてはいけない (2026-09-06)。

超えると、探されていない行が **画面に一生出てこない残** として積み上がる。
実害: 9/5 に目視だけ 補<5 に広げた結果、対象398件のうち **325件が「キャッシュ未取得」**。
「①目視で片づく残り 0件 / ②出てこない残 375件」となり、押しても減らないボタンになっていた。
"""
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools")))

import psa_hoju_fill as hf   # noqa: E402

BAT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools",
                                    "run_hoju_search.bat"))


def _night_max_backups():
    """夜間バッチが実際に探している上限 (--max-backups の最大値。既定は1=補0本)。"""
    txt = open(BAT, encoding="utf-8", errors="replace").read()
    found = [hf.SEARCH_MAX_BACKUPS]
    for m in re.finditer(r"psa_hoju_fill\.py\s+search\b([^\r\n]*)", txt):
        arg = re.search(r"--max-backups=(\d+)", m.group(1))
        found.append(int(arg.group(1)) if arg else hf.SEARCH_MAX_BACKUPS)
    return max(found)


def test_confirm_scope_is_covered_by_night_search():
    """目視の閾値 ≤ 夜間の閾値。広げたい時は **夜間も一緒に広げる**こと。"""
    night = _night_max_backups()
    assert hf.CONFIRM_MAX_BACKUPS <= night, (
        f"目視 補<{hf.CONFIRM_MAX_BACKUPS} > 夜間 補<{night}。"
        "差分は永久に『キャッシュ未取得』で画面に出ない残になる"
    )


def test_night_batch_has_enough_slots_for_the_confirm_scope():
    """夜間の枠が、目視の対象を3日で1周できる数あるか。

    目視が使えるキャッシュは3日以内 (_entry_fresh の既定)。対象398件なら1晩133件要る。
    枠が足りないと、余った分は「キャッシュ未取得」= 押しても出てこない残になる。
    """
    txt = open(BAT, encoding="utf-8", errors="replace").read()
    slots = [int(m.group(1)) for m in
             re.finditer(r"psa_hoju_fill\.py\s+search\b[^\r\n]*--limit=(\d+)", txt)]
    assert sum(slots) >= 130, f"夜間の枠 {sum(slots)}件/晩 では 補<5 の対象を3日で回れない"


def test_night_batch_still_searches_zero_backup_first():
    """1段目は補0本のまま (丸腰=仕入元が1本も無い出品が最優先)。"""
    txt = open(BAT, encoding="utf-8", errors="replace").read()
    assert "psa_hoju_fill.py search --limit=" in txt


def test_target_shrinks_with_threshold():
    """閾値を下げると対象が減る (select_backfill_targets の素の挙動)。"""
    header = ["A"] * 40
    def row(item_id, aux):
        r = [""] * 40
        r[1] = item_id                 # B列: itemID
        r[8] = "12345"                 # I列: cert (PSA判定)
        for k in range(aux):
            r[hf.AUX0 + k] = f"https://x/{item_id}/{k}"
        return r
    rows = [header, row("1", 0), row("2", 1), row("3", 4)]
    assert len(hf.select_backfill_targets(rows, max_backups=5)) >= \
           len(hf.select_backfill_targets(rows, max_backups=2)) >= \
           len(hf.select_backfill_targets(rows, max_backups=1))
