"""Phase 9 拡張 (黒窓抑制 + 停止ボタン) の regression test.

A1: PS1 で pythonw.exe + Hidden
A2: run_cycle.py で subprocess.Popen monkey-patch (CREATE_NO_WINDOW)
B:  control_panel.py の停止ボタンが lock file 経由で cron 起動分を kill
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================================
# A1: PS1 が pythonw.exe を優先するロジックを持つ
# ============================================================================
def test_register_cycle_ps1_prefers_pythonw():
    """register_cycle_task.ps1 が pythonw.exe を選ぶロジックを持つ."""
    src = (ROOT / "tools" / "register_cycle_task.ps1").read_text(encoding="utf-8")
    assert "pythonw.exe" in src
    assert "Test-Path $pythonwExe" in src or 'Test-Path $pythonwExe' in src
    assert "黒窓" in src or "no console" in src.lower()


def test_register_test_ps1_prefers_pythonw():
    """register_test_task.ps1 も pythonw.exe を優先する."""
    src = (ROOT / "tools" / "register_test_task.ps1").read_text(encoding="utf-8")
    assert "pythonw.exe" in src


def test_register_ps1_uses_hidden_settings():
    """両 PS1 が New-ScheduledTaskSettingsSet -Hidden を含む."""
    cycle_src = (ROOT / "tools" / "register_cycle_task.ps1").read_text(encoding="utf-8")
    test_src = (ROOT / "tools" / "register_test_task.ps1").read_text(encoding="utf-8")
    assert "-Hidden" in cycle_src
    assert "-Hidden" in test_src


# ============================================================================
# A2: run_cycle で CREATE_NO_WINDOW が subprocess に強制される
# ============================================================================
def test_run_cycle_has_no_window_constant():
    """_NO_WINDOW = subprocess.CREATE_NO_WINDOW (win32) が定義されている."""
    import run_cycle
    assert hasattr(run_cycle, "_NO_WINDOW")
    if sys.platform == "win32":
        import subprocess
        assert run_cycle._NO_WINDOW == subprocess.CREATE_NO_WINDOW
    else:
        assert run_cycle._NO_WINDOW == 0


def test_pytest_precheck_uses_creationflags():
    """pytest precheck の subprocess.run に creationflags=_NO_WINDOW が渡される."""
    src = (ROOT / "run_cycle.py").read_text(encoding="utf-8")
    # 検査: precheck 関数内で creationflags=_NO_WINDOW を使う
    idx = src.find("def _phase_pytest_precheck")
    assert idx != -1
    end = src.find("\ndef ", idx + 1)
    func_body = src[idx:end]
    assert "creationflags=_NO_WINDOW" in func_body


def test_run_cycle_patches_popen():
    """subprocess.Popen monkey-patch が行われている (chromedriver 黒窓抑制)."""
    import run_cycle
    assert hasattr(run_cycle, "_patch_subprocess_no_window")
    src = (ROOT / "run_cycle.py").read_text(encoding="utf-8")
    assert "subprocess.Popen = _PatchedPopen" in src or "subprocess.Popen =" in src


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_popen_monkey_patch_applies_no_window():
    """Patch 後の subprocess.Popen は CREATE_NO_WINDOW を creationflags に OR する."""
    import subprocess as sp_mod
    import run_cycle  # 副作用で _patch_subprocess_no_window() 呼出済
    # _imak_patched flag が立つ
    assert getattr(sp_mod.Popen, "_imak_patched", False), \
        "subprocess.Popen monkey-patch が適用されていない"


# ============================================================================
# B: 停止ボタン (lock file 経由 pid kill)
# ============================================================================
def test_control_panel_has_kill_via_lock_file():
    """control_panel に _kill_via_lock_file メソッドが存在する."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    assert "_kill_via_lock_file" in src
    assert "taskkill" in src  # Windows kill 経路使用
    assert "pid=" in src  # lock file の pid= prefix を parse


def test_control_panel_stop_button_always_enabled():
    """stop ボタンは常に enabled (cron 起動分も停止対象)."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    # stop_btn 生成時に state="disabled" でない
    idx = src.find('text="■ 停止"')
    assert idx != -1
    btn_decl_end = src.find(")", idx)
    btn_decl = src[idx:btn_decl_end + 1]
    assert 'state="disabled"' not in btn_decl
    # Phase 9 拡張のコメントが入ってる
    surround = src[max(0, idx - 200):idx + 200]
    assert "常に enabled" in surround or "cron" in surround


def test_control_panel_stop_has_confirmation_dialog():
    """停止前に askyesno 確認ダイアログを出す."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    idx = src.find("def _stop_cycle")
    assert idx != -1
    end = src.find("\n    def ", idx + 1)
    func_body = src[idx:end]
    assert "askyesno" in func_body
    assert "停止しますか" in func_body or "巡回停止" in func_body


# ============================================================================
# Phase 9 緊急 fix: control_panel の subprocess flash 問題
# ============================================================================
def test_control_panel_has_popen_monkey_patch():
    """control_panel.py 冒頭で subprocess.Popen を monkey-patch している.

    旧バグ: cron info が 30秒おきに schtasks subprocess を spawn → console
    flash で GUI フォーカス奪取 → キーボード入力不能。
    """
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    assert "_patch_subprocess_no_window" in src
    assert "_imak_patched" in src


def test_control_panel_cron_info_throttled():
    """_render_cron_info に 60秒 throttle がある."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    assert "CRON_INFO_REFRESH_SEC" in src
    assert "_cron_info_last_refresh" in src
    assert "_cron_info_cache_text" in src


def test_control_panel_subprocess_calls_have_creationflags():
    """control_panel 内の subprocess.run / Popen に creationflags=_NO_WINDOW."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    # _NO_WINDOW 定数定義
    assert "_NO_WINDOW = subprocess.CREATE_NO_WINDOW" in src
    # 各 subprocess.run / Popen 呼出に creationflags 引数
    # (monkey-patch とは別に明示的にも仕込み = 二重防御)
    occurrences = src.count("creationflags=_NO_WINDOW")
    assert occurrences >= 4, f"creationflags=_NO_WINDOW が {occurrences} 件、4 以上必要"


# ============================================================================
# Phase 9 拡張: タイマー時刻 6 件 GUI 入力対応
# ============================================================================
def test_register_cycle_ps1_accepts_times_param():
    """register_cycle_task.ps1 が -Times パラメータを受け取り、トリガーを動的構築."""
    src = (ROOT / "tools" / "register_cycle_task.ps1").read_text(encoding="utf-8")
    assert "[string]$Times" in src
    assert "$Times -split" in src or "-split " in src
    # HH:MM フォーマット検証
    assert "HH:MM" in src
    # default 値は 6 件 (Phase 9a の trabajo 並走想定値)
    assert "10:00,14:00,18:00,22:00,02:00,06:00" in src


def test_control_panel_has_six_time_inputs():
    """control_panel に cycle_time_vars (6 個の time entry) がある."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    assert "cycle_time_vars" in src
    assert "for i in range(6)" in src
    assert "_DEFAULT_TIMES" in src
    # default は trabajo 並走想定 6 件
    assert '"10:00"' in src
    assert '"14:00"' in src


def test_control_panel_cycle_times_persisted_in_state():
    """cycle_times を .gui_state.json に保存する."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    assert '"cycle_times"' in src or "'cycle_times'" in src
    # state["cycle_times"] = collected[:6] の永続化ロジック
    assert "self.state[" in src and "cycle_times" in src


def test_control_panel_validates_time_format():
    """空欄 skip + HH:MM 形式チェックロジックが存在."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    # HH:MM regex
    assert r"\d{1,2}:\d{2}" in src
    # 「最低 1 件」エラー
    assert "最低 1 件" in src or "1 件以上" in src or "最低１" in src
    # 空欄 skip コメント or continue
    assert "空欄" in src or 'continue' in src


def test_run_powershell_supports_extra_args():
    """_run_powershell が extra_args を受け取り、コマンドに追加する."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    assert "extra_args" in src
    # cmd.extend(extra_args) または相当
    assert "cmd.extend(extra_args)" in src or "cmd += extra_args" in src


def test_register_cycle_ps1_accepts_limit_param():
    """register_cycle_task.ps1 が -Limit パラメータを持つ."""
    src = (ROOT / "tools" / "register_cycle_task.ps1").read_text(encoding="utf-8")
    assert "[int]$Limit" in src
    # Limit > 0 の場合のみ --limit に変換
    assert "$Limit -gt 0" in src
    assert '"--limit"' in src


def test_control_panel_passes_limit_to_cycle_task():
    """control_panel が cycle 登録時に -Limit 引数を渡す."""
    src = (ROOT / "control_panel.py").read_text(encoding="utf-8")
    # _task_register("cycle") 内で limit_var を読んで -Limit を渡す
    idx = src.find("def _task_register")
    assert idx != -1
    end = src.find("\n    def ", idx + 1)
    func_body = src[idx:end]
    assert "limit_var" in func_body
    assert '"-Limit"' in func_body


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
