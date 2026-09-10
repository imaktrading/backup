# -*- coding: utf-8 -*-
"""確証画面: 送信失敗を黙らせない / 入力を失わない (2026-09-10 実害).

サーバが先に落ちた後、20件を目視して確定を押したが **無反応** だった
(fetch に .catch が無く、失敗が画面に出ない)。同じポートで受け口を立て直して
拾えたが、ページを閉じられていたら20件の判断が消えていた。

- 送信の前にブラウザ側へ下書きを残す
- 失敗したら赤帯で知らせ、結果をファイルに保存できるようにする
- 次に開いた時、未送信の下書きがあれば知らせる
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import newcand_confirm as N          # noqa: E402


def test_failure_is_not_silent():
    """fetch の失敗が握りつぶされないこと。"""
    assert ".catch(function(e){_sendFailed(p,e);})" in N.SAVE_JS
    assert "送信できませんでした" in N.SAVE_JS


def test_draft_is_saved_before_sending():
    assert "_saveDraft(p);" in N.SAVE_JS
    assert "localStorage.setItem" in N.SAVE_JS


def test_draft_is_cleared_only_on_success():
    i = N.SAVE_JS.index("function _send(")
    body = N.SAVE_JS[i:]
    assert body.index("_clearDraft();") > body.index("if(!r.ok)"), "成功した時だけ消すこと"


def test_result_can_be_saved_to_a_file():
    """画面を閉じる前に結果を持ち出せること (今回の救出手段)。"""
    assert 'download="confirm_result.json"' in N.SAVE_JS


def test_both_screens_include_it():
    src = open(os.path.join(TOOLS, "newcand_confirm.py"), encoding="utf-8").read()
    assert src.count("SAVE_JS") >= 3, "目視画面と証明番号画面の両方に入れること"
    assert "fetch('/',{method:'POST'" not in src.replace(N.SAVE_JS, ""), (
        "画面側に素の fetch が残っている (_send を通すこと)")
