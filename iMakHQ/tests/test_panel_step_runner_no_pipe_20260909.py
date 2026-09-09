# -*- coding: utf-8 -*-
"""出品くんが後処理で固まらないこと (2026-09-09 ユーザー報告).

> PSAの自動、固まってない?

2晩続けて **同じ場所** (CSV完成 → 締めの4手に入る手前) で止まった。
CPU 0 / 子プロセス無し / 応答無しのまま朝まで動かない。

原因: `subprocess.run(capture_output=True)` が作るパイプは、書き込み側が
**孫プロセス (Selenium の chrome 等) にも受け継がれる**。子を timeout で殺しても
孫が生きている限り読み終わりが来ず、run はそこで永久に待つ。
→ パイプをやめて一時ファイルに受け、時間切れは孫まで止める。
"""
import os
import subprocess
import sys
import time

import pytest

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HQ)

import control_panel as CP          # noqa: E402


def test_returns_output_and_returncode():
    r = CP._run_step([sys.executable, "-c", "print('hello')"], timeout=60,
                     encoding="utf-8")
    assert r.returncode == 0
    assert "hello" in r.stdout


def test_bytes_when_no_encoding_given():
    """subprocess.run と同じ約束: text/encoding 無しなら bytes で返す。

    schtasks は cp932 で出すので、呼び手が自分で decode している所がある。
    ここを勝手に str にすると、その所が壊れる (2026-09-09 に踏んだ)。
    """
    r = CP._run_step([sys.executable, "-c", "print('hello')"], timeout=60)
    assert isinstance(r.stdout, bytes) and b"hello" in r.stdout


def test_stderr_is_separate():
    r = CP._run_step([sys.executable, "-c",
                      "import sys; sys.stderr.write('boom')"], timeout=60,
                     encoding="utf-8")
    assert "boom" in r.stderr
    assert "boom" not in r.stdout


def test_nonzero_returncode_is_reported_not_raised():
    r = CP._run_step([sys.executable, "-c", "raise SystemExit(3)"], timeout=60)
    assert r.returncode == 3


@pytest.mark.skipif(sys.platform != "win32", reason="孫の生存はプラットフォーム依存")
def test_timeout_does_not_hang_when_a_grandchild_outlives_the_child():
    """★これが本体。孫が生き残っても **時間切れで必ず戻る**。

    子はすぐ終わるが、孫 (別プロセス) が居座る。パイプで受けていると、この
    孫が書き込み側を握ったままなので run は永久に返ってこなかった。
    """
    code = (
        "import subprocess,sys;"
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
        "import time; time.sleep(30)"
    )
    t0 = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        CP._run_step([sys.executable, "-c", code], timeout=3)
    took = time.time() - t0
    assert took < 45, "時間切れで戻らず固まっている (%.1f秒)" % took


def test_post_chain_does_not_use_raw_subprocess_run():
    """後処理チェーンが素の subprocess.run に戻っていないこと (taskkill だけ例外)。"""
    src = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    hits = [ln for ln in src.splitlines()
            if "subprocess.run(" in ln and "taskkill" not in ln]
    assert not hits, hits


def test_step_headers_are_mirrored_into_run_log():
    """工程の見出しが run log にも残る (次に固まった時どこか判るように)。"""
    src = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    assert 'text.lstrip().startswith("▶")' in src
    assert 'self._run_log.write("[%s] %s"' in src
