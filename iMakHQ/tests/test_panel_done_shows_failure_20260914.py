# -*- coding: utf-8 -*-
"""処理が落ちたのに「🎉 全 process 完了 — 入稿準備 OK」と出ていた (2026-09-14)。

実例: 🔁 売れた分を補充 が ValueError で returncode=1 で終わった直後に「🎉 全 process 完了」。
returncode が 0 / None 以外なら締めを「❌ 失敗しました」にする。
"""
import os

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()


def test_nonzero_returncode_is_not_reported_as_complete():
    i_fail = SRC.index("elif item[1] not in (0, None):")
    i_ok = SRC.index('self.append_log("🎉 全 process 完了 — 入稿準備 OK\\n")')
    assert i_fail < i_ok
    assert "❌ 失敗しました (returncode={item[1]})" in SRC[i_fail:i_ok]


def test_failure_check_is_inside_the_done_branch():
    i_done = SRC.index('if isinstance(item, tuple) and item[0] == "__done__":')
    i_fail = SRC.index("elif item[1] not in (0, None):")
    i_next_def = SRC.index("\n    def ", i_done)
    assert i_done < i_fail < i_next_def
