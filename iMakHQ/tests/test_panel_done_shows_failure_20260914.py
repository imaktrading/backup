# -*- coding: utf-8 -*-
"""処理が落ちたのに「🎉 全 process 完了 — 入稿準備 OK」と出ていた (2026-09-14)。

実例: 🔁 売れた分を補充 が ValueError で returncode=1 で終わった直後に「🎉 全 process 完了」。
returncode が 0 / None 以外なら締めを「❌ 失敗しました」にする。
"""
import os

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()


def test_nonzero_returncode_is_not_reported_as_complete():
    i_fail = SRC.index("elif returncode not in (0, None):")
    i_ok = SRC.index('append_log("🎉 全 process 完了 — 入稿準備 OK\\n")')
    assert i_fail < i_ok
    assert "❌ 失敗しました (returncode={returncode})" in SRC[i_fail:i_ok]


def test_failure_check_is_inside_the_after_run():
    """2026-09-16: 後処理は after_run() に抜き出した (旧パネルと新 Console が同じ物を呼ぶ)。

    締めの判定は after_run の中にあり、走り終わりの分岐から必ず呼ばれる。
    """
    i_run = SRC.index("def after_run(script, returncode, append_log")
    i_fail = SRC.index("elif returncode not in (0, None):")
    i_next_def = SRC.index("\ndef ", i_run + 1)
    assert i_run < i_fail < i_next_def
    i_done = SRC.index('if isinstance(item, tuple) and item[0] == "__done__":')
    i_call = SRC.index("after_run(_script_now, item[1], self.append_log", i_done)
    assert i_call < SRC.index("\n    def ", i_done)
