# -*- coding: utf-8 -*-
"""回帰: 取下再出品②ボタンが post-process(重複くん/excluder) をスキップする設定を保持。

2026-06-07: ②ボタン経由で重複くんが走り、relist対象(取下げ前=管理シート上ACTIVE)を
「重複」誤判定して Add CSV から8件物理削除する事故。relist は同型番の意図的再出品なので
②ボタンは skip_postprocess=True で後処理をスキップする。本テストはその設定を守る。
"""
import os

_CP = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "control_panel.py"))


def test_relist_add_button_has_skip_postprocess():
    src = open(_CP, encoding="utf-8").read()
    assert "relist_add_from_pending.py" in src, "②ボタンの cmd が無い"
    idx = src.index("relist_add_from_pending.py")
    nearby = src[idx:idx + 500]
    assert "skip_postprocess" in nearby, "②ボタンに skip_postprocess フラグが無い (重複くんが relist を削除する)"


def test_poll_queue_guards_dedupe_with_skip_flag():
    src = open(_CP, encoding="utf-8").read()
    # poll_queue 側で _skip_pp により dedupe/excluder をガードしている
    assert "_skip_pp" in src
    assert "skip_postprocess" in src
    # dedupe 呼出が _skip_pp ガード配下にある (素朴な近接チェック)
    assert "_run_dedupe_for_latest_csv" in src
