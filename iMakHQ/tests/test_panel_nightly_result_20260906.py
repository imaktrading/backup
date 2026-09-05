# -*- coding: utf-8 -*-
"""夜間の実績は「その夜の日付」で数える。暦日で数えると必ず0件になる (2026-09-06).

## なぜ
パネルは「夜間 2026-09-05 … 完走 (23段) / 探せた 0件」と出していた。完走したのに
1件も探せていない、と読める。

実際は 128件 探せていた。夜間は **23:30 開始**なので、書かれるキャッシュには
前日の日付が焼かれる。表示側は `done` (= 今日 探し済み) を出していたので、
朝に見ると **必ず 0件**。日付を跨ぐ仕事を暦日で数えたのが誤り。

## もう1つ
「🔁 売れた分を補充」は注文レポートが無いと数えられないが、それを `error` として
「(残件 取得できず: …)」と出していた。**数えられなかった失敗ではなく前提不足**なので、
何をすればいいか (レポートをDLする) が読み取れなかった。
`if not sr.get("report")` の分岐は書いてあったのに、`error` を先に見ていて死んでいた。
"""
from __future__ import annotations

import io
import os

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PANEL = io.open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()
_HOJU = io.open(os.path.join(_HQ, "tools", "psa_hoju_fill.py"), encoding="utf-8").read()


class TestNightlyResultIsCountedByThatNight:
    def test_counter_returns_counts_per_day(self):
        assert '"searched_by_date": dict(by_date)' in _HOJU
        # 両方揃った分だけを「探せた」と数える (片方欠けは再取得対象)。
        i = _HOJU.index("by_date = collections.Counter()")
        body = _HOJU[i:i + 400]
        assert '"mercari" in _e and "snkrdunk" in _e' in body

    def test_panel_uses_the_night_date_not_today(self):
        i = _PANEL.index("その夜に探せた")
        body = _PANEL[i - 400:i + 300]
        assert 'searched_by_date") or {}).get(_nl["date"]' in body, \
            "その夜の日付で引いていない"
        assert 's.get("done", 0)' not in body, \
            "done は暦日基準。夜間の実績には使えない"

    def test_zero_on_a_completed_night_is_flagged(self):
        """完走したのに0件なら、それは本当におかしいので警告を出す。"""
        i = _PANEL.index("その夜に探せた")
        assert "完走しているのに1件も探せていません" in _PANEL[i:i + 500]


class TestSoldRestockPrerequisite:
    def test_missing_report_is_not_reported_as_a_failure(self):
        i = _PANEL.index('sr = (w0.get("restock")')
        body = _PANEL[i:i + 900]
        assert 'if sr and not sr.get("report"):' in body, \
            "レポート未DL を error より先に見ていない (下の分岐が死ぬ)"
        # 何をすればいいかを書く
        j = body.index('if sr and not sr.get("report"):')
        assert "先に注文レポートをDL" in body[j:j + 300]

    def test_the_old_dead_branch_is_gone(self):
        assert "※注文レポート未DL (デスクトップに" not in _PANEL
