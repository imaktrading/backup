# -*- coding: utf-8 -*-
"""どのボタンも「残り何件 / 今回 何件」を同じ言い回しで出す (2026-09-06 ユーザー指示).

## なぜ
> どのボタンもそうだけど、そのボタンで、処理する件数が何件残っているか。
> が分かる表記にするべきでは？

ボタンごとに言い回しがバラバラ (「目視できる」「今すぐ照合できる」「CSVにできる」
「今夜の対象」…) で、しかも **1回で全部 終わらないボタン**があるのに総数だけ出していた。
押しても数字が減らないように見える。

もう1つ、PSA 補URL の ① と ② は **同じ badge を共有**していたので、
件数もヒントも色も完全に同じだった。①は出品直後に押すボタンなのに
「夜間に自動 (押す必要なし)」と出て、夜間が動いている限り一度も青にならなかった。
"""
from __future__ import annotations

import io
import os
import re
import sys

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = io.open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()

sys.path.insert(0, _HQ)


def _panel():
    import control_panel as cp
    return cp.ListingPanel


def _scripts():
    import control_panel as cp
    return cp.SCRIPTS


class TestTodoLine:
    def test_says_remaining_and_this_press(self):
        line = _panel().todo_line("hoju_confirm", 44, "目視します")
        assert "残り 44件" in line and "今回 15件" in line
        assert "あと約3回" in line, "1回で終わらないなら 何回で終わるかまで出す"

    def test_no_cap_means_all_at_once(self):
        line = _panel().todo_line("psa_gate", 5, "照合します")
        assert "残り 5件" in line and "今回 全部" in line
        assert "あと約" not in line

    def test_zero_says_pressing_does_nothing(self):
        assert _panel().todo_line("hoju_confirm", 0, "目視します").strip() == "※押しても0件"

    def test_broken_count_does_not_crash(self):
        """数えられなかった時に例外で描画ごと落とさない。"""
        assert _panel().todo_line("psa_gate", None, "照合します").strip() == "※押しても0件"
        assert _panel().todo_line("psa_gate", "?", "照合します").strip() == "※押しても0件"


class TestEveryButtonShowsIt:
    def test_every_badge_has_a_hint_entry(self):
        """badge を持つボタンは全部 by_kind に居る (= 残件が出る)。"""
        i = _SRC.index('by_kind = {"hoju_search"')
        body = _SRC[i:_SRC.index("act_kind = {", i)]
        for sc in _scripts():
            b = sc.get("badge")
            if not b or b == "hoju_status":       # 📊 件数感 は見るだけ
                continue
            assert '"%s"' % b in body, f"{b} ({sc['label']}) の残件が出ていない"

    def test_press_cap_matches_the_command(self):
        """「今回 15件」が cmd の --limit とずれないこと (ずれると回数が嘘になる)。"""
        caps = _panel().PRESS_CAP
        for sc in _scripts():
            b = sc.get("badge")
            if not b:
                continue
            m = re.search(r"--limit[= ](\d+)", " ".join(str(x) for x in sc.get("cmd", [])))
            if m:
                assert caps.get(b) == int(m.group(1)), \
                    f"{b}: PRESS_CAP={caps.get(b)} だが cmd は --limit={m.group(1)}"
            else:
                assert b not in caps or b == "cull_end", \
                    f"{b}: cmd に上限が無いのに PRESS_CAP を持っている"


class TestFirstButtonIsNotTheSecond:
    def test_they_do_not_share_a_badge(self):
        by_label = {sc["label"]: sc.get("badge") for sc in _scripts() if sc.get("badge")}
        one = by_label["🆕 PSA 補URL ① 当日分"]
        two = by_label["🔎 PSA 補URL ② 夜に探す"]
        assert one != two, "①と②が同じ badge だと 件数もヒントも色も同じになる"

    def test_today_count_exists_and_is_not_the_nightly_one(self):
        assert '"hoju_search_now": bool(s.get("today_can"))' in _SRC, \
            "①は夜間ルールから外す (今日出した分は夜まで無防備)"
        assert '"hoju_search": bool(s.get("can")) and not _auto' in _SRC


class TestConfirmHintDoesNotReadAsZero:
    def test_unjudged_only_never_leads_with_zero(self):
        """「目視できる 0件 / ※絵柄が未判定 44件」が誤解の元だった。"""
        i = _SRC.index('c_txt = self.todo_line("hoju_confirm"')
        body = _SRC[i:i + 700]
        assert 'todo_line("hoju_confirm", _rdy + _unj' in body, \
            "未判定も『押せば減る仕事』なので残件に含める"
        # 経緯を書いたコメントには残ってよい。**画面に出す文字列**に無いことを見る。
        shown = "\n".join(ln for ln in _SRC.splitlines()
                          if not ln.lstrip().startswith("#"))
        assert "目視できる 0件" not in shown


def test_count_workload_reports_today():
    """psa_hoju_fill 側が『今日 出した分』を返すこと (①の件数の出どころ)。"""
    src = io.open(os.path.join(_HQ, "tools", "psa_hoju_fill.py"), encoding="utf-8").read()
    assert '"today_can": s_today' in src
    assert 'if (t.get("listed_at") or "")[:10] == today:' in src


if __name__ == "__main__":                                        # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
