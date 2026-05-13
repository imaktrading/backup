"""upload_health の regression test (事故 2026-05-05 再発防止).

検証範囲:
- not_logged_in / session_expired は 1 回目で即時アラート発火
- flaky (popup 検出 false negative) は連続 3 回で発火
- generic 失敗は連続 2 回で発火
- success で全 streak リセット
- skipped は履歴のみ追加、streak 変えず
- 通知関数 (toast / desktop file) を mock して fire_alert 呼出回数だけチェック
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def isolated_health(tmp_path, monkeypatch):
    """upload_health.HEALTH_FILE を tmp に隔離 + DESKTOP も tmp に向ける."""
    import upload_health

    monkeypatch.setattr(upload_health, "HEALTH_FILE", tmp_path / "upload_health.json")
    monkeypatch.setattr(upload_health, "DECISION_LOG_DIR", tmp_path)
    desk = tmp_path / "desktop"
    monkeypatch.setattr(upload_health, "DESKTOP_DIR", desk)
    monkeypatch.setattr(upload_health, "DESKTOP_DIR_FALLBACK", desk)

    # toast を mock (テスト中は実機通知させない)
    fired = []
    monkeypatch.setattr(upload_health, "_toast", lambda title, body: fired.append((title, body)))

    return upload_health, fired


def test_not_logged_in_immediate_alert(isolated_health):
    """error="not_logged_in" は 1 回目で即時アラート発火."""
    uh, fired = isolated_health
    res = uh.record_upload_result(
        {"success": False, "error": "not_logged_in"},
        csv_path="x.csv", csv_lines=3, cycle_ts="2026-05-05T17:30:00",
    )
    assert res["alert_fired"] is True
    assert res["reason"] == "critical_error_immediate"
    assert res["health"]["not_logged_in_streak"] == 1
    assert len(fired) == 1
    assert "ログイン" in fired[0][0] or "not_logged_in" in fired[0][1]


def test_session_expired_also_critical(isolated_health):
    """session_expired_and_relogin_failed も即時アラート."""
    uh, fired = isolated_health
    res = uh.record_upload_result(
        {"success": False, "error": "session_expired_and_relogin_failed"},
        csv_path="x.csv", csv_lines=1, cycle_ts="t",
    )
    assert res["alert_fired"] is True
    assert res["health"]["not_logged_in_streak"] == 1


def test_flaky_under_threshold_no_alert(isolated_health):
    """flaky は閾値未満ならアラート発火しない."""
    uh, fired = isolated_health
    for i in range(uh.FLAKY_THRESHOLD - 1):
        res = uh.record_upload_result(
            {"success": False, "error": "upload result not detected (popup + history both inconclusive)"},
            csv_path=f"x{i}.csv", csv_lines=1, cycle_ts=f"t{i}",
        )
        assert res["alert_fired"] is False
    assert len(fired) == 0


def test_flaky_threshold_triggers_alert(isolated_health):
    """flaky 連続 FLAKY_THRESHOLD (=3) 回で発火."""
    uh, fired = isolated_health
    for i in range(uh.FLAKY_THRESHOLD):
        res = uh.record_upload_result(
            {"success": False, "error": "upload result not detected (popup + history both inconclusive)"},
            csv_path=f"x{i}.csv", csv_lines=1, cycle_ts=f"t{i}",
        )
    assert res["alert_fired"] is True
    assert res["reason"] == "flaky_streak_threshold"
    assert res["health"]["flaky_streak"] == uh.FLAKY_THRESHOLD


def test_generic_threshold_triggers_alert(isolated_health):
    """flaky でも critical でもない失敗は GENERIC_THRESHOLD (=2) 回で発火."""
    uh, fired = isolated_health
    for i in range(uh.GENERIC_THRESHOLD):
        res = uh.record_upload_result(
            {"success": False, "error": "some other unknown failure"},
            csv_path=f"x{i}.csv", csv_lines=1, cycle_ts=f"t{i}",
        )
    assert res["alert_fired"] is True
    assert res["reason"] == "generic_failure_threshold"


def test_success_resets_all_streaks(isolated_health):
    """success=True で全 streak リセット."""
    uh, fired = isolated_health
    # まず flaky を 2 回貯める
    for i in range(2):
        uh.record_upload_result(
            {"success": False, "error": "upload result not detected (popup + history both inconclusive)"},
            csv_path=f"x{i}.csv", csv_lines=1, cycle_ts=f"t{i}",
        )
    health = uh._load_health()
    assert health["flaky_streak"] == 2

    # 成功で reset
    res = uh.record_upload_result(
        {"success": True}, csv_path="ok.csv", csv_lines=1, cycle_ts="ok",
    )
    assert res["alert_fired"] is False
    assert res["health"]["flaky_streak"] == 0
    assert res["health"]["not_logged_in_streak"] == 0
    assert res["health"]["generic_failure_streak"] == 0
    assert res["health"]["last_success_ts"] == "ok"


def test_skipped_does_not_change_streak(isolated_health):
    """skipped は履歴のみ追加、streak は変えない (newly_sold=0 等は健全)."""
    uh, fired = isolated_health
    # 最初に flaky 1 回
    uh.record_upload_result(
        {"success": False, "error": "upload result not detected (popup + history both inconclusive)"},
        csv_path="x.csv", csv_lines=1, cycle_ts="t1",
    )
    h1 = uh._load_health()
    assert h1["flaky_streak"] == 1

    # skipped → flaky_streak 維持
    res = uh.record_upload_result(
        {"skipped": "no csv"}, csv_path=None, csv_lines=None, cycle_ts="t2",
    )
    assert res["alert_fired"] is False
    h2 = uh._load_health()
    assert h2["flaky_streak"] == 1  # 変わらず


def test_critical_streak_keeps_alerting(isolated_health):
    """critical は 2 回目, 3 回目も毎回アラート (silently fail させない)."""
    uh, fired = isolated_health
    for i in range(3):
        res = uh.record_upload_result(
            {"success": False, "error": "not_logged_in"},
            csv_path="x.csv", csv_lines=1, cycle_ts=f"t{i}",
        )
        assert res["alert_fired"] is True, f"iter {i}"
    assert len(fired) == 3
    assert uh._load_health()["not_logged_in_streak"] == 3


def test_desktop_alert_file_created(isolated_health, tmp_path):
    """通知発火時にデスクトップアラートファイルが作成される (toast 見逃し対策)."""
    uh, _ = isolated_health
    desk = tmp_path / "desktop"
    res = uh.record_upload_result(
        {"success": False, "error": "not_logged_in"},
        csv_path="x.csv", csv_lines=1, cycle_ts="t",
    )
    assert res["alert_fired"] is True
    files = list(desk.glob("ALERT_iMakInventory_*.txt"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert "not_logged_in" in body
    assert "x.csv" in body


def test_history_capped(isolated_health):
    """履歴は max_keep (20) 件で打ち切り."""
    uh, _ = isolated_health
    for i in range(25):
        uh.record_upload_result(
            {"success": True}, csv_path=f"x{i}.csv", csv_lines=1, cycle_ts=f"t{i}",
        )
    h = uh._load_health()
    assert len(h["history"]) == 20


def test_assess_recent_cycles_warn_on_consecutive_failures(tmp_path, monkeypatch):
    """assess_recent_cycles が連続失敗を warn=True で返す."""
    import upload_health
    monkeypatch.setattr(upload_health, "DECISION_LOG_DIR", tmp_path)

    # 直近 3 cycle に 2 件 failure
    for i, success in enumerate([True, False, False]):
        path = tmp_path / f"cycle_2026{i:03d}_120000.jsonl"
        path.write_text(json.dumps({
            "phases": {"upload": {"success": success}},
        }), encoding="utf-8")

    res = upload_health.assess_recent_cycles(n=3)
    assert res["recent_n"] == 3
    assert res["failure"] == 2
    assert res["success"] == 1
    assert res["warn"] is True


def test_action_needed_failure_uses_distinct_title(isolated_health):
    """action_needed_failure は「ログイン切れ」と誤誘導しない (= 別 title)."""
    uh, fired = isolated_health
    uh.record_upload_result(
        {"success": False, "error": "action_needed_failure: 1 件 (safe=0, warning=0)"},
        csv_path="x.csv", csv_lines=1, cycle_ts="2026-05-11T22:21:00",
    )
    assert len(fired) == 1
    title, body = fired[0]
    # 「ログイン切れ」が title に含まれないこと
    assert "ログイン切れ" not in title
    # 適切な title (= eBay 拒否 / listing 個別対応)
    assert "取下げ拒否" in title or "個別対応" in title
    # body に listing 個別問題の説明があること
    assert "再ログイン" in body and "解消しません" in body


def test_not_logged_in_uses_login_title(isolated_health):
    """not_logged_in は「真のログイン切れ」title (= 既存挙動維持)."""
    uh, fired = isolated_health
    uh.record_upload_result(
        {"success": False, "error": "not_logged_in"},
        csv_path="x.csv", csv_lines=1, cycle_ts="2026-05-11T22:21:00",
    )
    assert len(fired) == 1
    title, _ = fired[0]
    assert "真のログイン切れ" in title


def test_not_logged_in_streak_resets_on_other_errors(isolated_health):
    """真のログイン切れの後に別 error (503 等) が来たら not_logged_in_streak リセット.

    bug fix (2026-05-14): 旧版は generic_failure や action_needed_failure でも
    not_logged_in_streak が増分されないまま「2」のまま固定 → メールで「ログイン切れ
    連続 2 回」と誤誘導された。
    """
    uh, _ = isolated_health
    # 1. 真のログイン切れ 2 連発で streak=2
    uh.record_upload_result(
        {"success": False, "error": "not_logged_in"},
        csv_path="x.csv", csv_lines=1, cycle_ts="2026-05-12T21:30:00",
    )
    uh.record_upload_result(
        {"success": False, "error": "not_logged_in"},
        csv_path="x.csv", csv_lines=1, cycle_ts="2026-05-13T01:30:00",
    )
    health = uh._load_health()
    assert health["not_logged_in_streak"] == 2

    # 2. 503 (= result_csv_download_failed、login とは無関係) で streak リセット
    uh.record_upload_result(
        {"success": False, "error": "result_csv_download_failed: HTTPError: 503"},
        csv_path="x.csv", csv_lines=1, cycle_ts="2026-05-13T13:30:00",
    )
    health = uh._load_health()
    assert health["not_logged_in_streak"] == 0   # ← bug fix の核心


def test_action_needed_failure_does_not_increment_login_streak(isolated_health):
    """action_needed_failure (= 画像要件等) は CRITICAL だが not_logged_in_streak は増えない."""
    uh, _ = isolated_health
    uh.record_upload_result(
        {"success": False, "error": "action_needed_failure: 1 件"},
        csv_path="x.csv", csv_lines=1, cycle_ts="2026-05-14T01:30:00",
    )
    health = uh._load_health()
    assert health["not_logged_in_streak"] == 0   # action_needed では増えない


def test_result_not_in_history_uses_distinct_title(isolated_health):
    """result_not_in_history は別 title (= 履歴確認誘導)."""
    uh, fired = isolated_health
    uh.record_upload_result(
        {"success": False, "error": "result_not_in_history"},
        csv_path="x.csv", csv_lines=1, cycle_ts="2026-05-11T22:21:00",
    )
    assert len(fired) == 1
    title, _ = fired[0]
    assert "ログイン切れ" not in title
    assert "履歴" in title


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
