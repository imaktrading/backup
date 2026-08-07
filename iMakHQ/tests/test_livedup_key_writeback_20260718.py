# -*- coding: utf-8 -*-
"""live重複除外 cert への KEY 書込 — 浪費ループ対策の回帰テスト (2026-07-18)。

背景: 同一カードが既に live 出品済だと、2枚目の cert 行は KEY 空で抽出→生成→Step 4a が
live重複として物理除外→KEY書込(4b)は deduped CSV を見るので cert に KEY が付かない→
次回also抽出。1回10件の franchise 枠を毎回1つ浪費(Bloodmoon SV5a-091 が 2026-07-16/17 連続空振り)。

対策の肝(安全境界): KEY を書くのは **4a(live重複=出品済の兄弟あり)が消した cert のみ**。
intra-CSV間引き(4a-2=兄弟未出品)分に KEY を書くと orphan 化するので対象外。
このテストは pre/post CSV diff が 4a 除外分だけを正しく拾うことを固定する。
"""
import csv
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
import control_panel as cp  # noqa: E402

HEADER = ["Action", "CustomLabel", "*Title", "C:Game", "C:Set", "C:Card Number"]


def _row(label, num):
    return ["Add", label, f"PSA 10 X #{num}", "Pokemon", "Crimson Haze", num]


def test_row_label_uses_customlabel():
    assert cp._row_label(HEADER, _row("PSA10-126828515", "091")) == "PSA10-126828515"


def test_row_label_falls_back_to_col0_when_no_customlabel():
    assert cp._row_label(["A", "B"], ["x", "y"]) == "x"


def test_livedup_removed_detects_the_removed_row():
    """Bloodmoon が 4a で消えた → removed に1件だけ入る。"""
    pre = [_row("PSA10-111", "091"), _row("PSA10-222", "069"), _row("PSA10-333", "072")]
    post = [_row("PSA10-222", "069"), _row("PSA10-333", "072")]        # 091 が live重複除外
    removed = cp._livedup_removed_rows(pre, HEADER, post, HEADER)
    assert [cp._row_label(HEADER, r) for r in removed] == ["PSA10-111"]


def test_nothing_removed_returns_empty():
    pre = [_row("PSA10-222", "069")]
    assert cp._livedup_removed_rows(pre, HEADER, pre, HEADER) == []


def test_multiple_removed():
    pre = [_row("PSA10-1", "a"), _row("PSA10-2", "b"), _row("PSA10-3", "c")]
    post = [_row("PSA10-2", "b")]
    removed = {cp._row_label(HEADER, r) for r in cp._livedup_removed_rows(pre, HEADER, post, HEADER)}
    assert removed == {"PSA10-1", "PSA10-3"}


def test_roundtrip_read_csv(tmp_path):
    p = tmp_path / "t.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(HEADER)
        w.writerow(_row("PSA10-091", "091"))
    rows, header = cp._read_csv_rows(str(p))
    assert header == HEADER
    assert cp._row_label(header, rows[0]) == "PSA10-091"


def test_writer_skips_when_no_removed(tmp_path):
    """removed 0件なら temp CSV も subprocess も作らない(no-op)。"""
    p = tmp_path / "final.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        csv.writer(f, quoting=csv.QUOTE_NONNUMERIC).writerows([HEADER, _row("PSA10-A", "a")])
    logs = []
    # pre == post → removed空 → 何もしない・例外なし
    cp._write_keys_for_livedup_removed(logs.append, str(p),
                                       [_row("PSA10-A", "a")], HEADER, os.environ.copy())
    assert not os.path.exists(str(p) + ".livedup_removed.csv")
    assert logs == []
