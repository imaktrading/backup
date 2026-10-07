"""after_kagoya (KAGOYA 本番の受け取り) — 送れていない日は家で送る."""
import revise.after_kagoya as ak


def test_waits_until_live_status_then_returns():
    seq = iter([{}, {}, {"mode": "live", "result": "ok", "sent_ok": True}])
    sleeps = []
    st = ak.wait_for_kagoya("20261008", None, sleep_fn=sleeps.append, pull_fn=lambda d, p: next(seq))
    assert st["result"] == "ok" and len(sleeps) == 2


def test_gives_up_after_max_wait():
    sleeps = []
    st = ak.wait_for_kagoya("20261008", None, sleep_fn=sleeps.append, pull_fn=lambda d, p: {})
    assert st == {} and len(sleeps) == ak.WAIT_MAX_SEC // ak.WAIT_STEP_SEC


def test_falls_back_to_home_when_kagoya_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(ak, "CSV_DIR", tmp_path)
    monkeypatch.setattr(ak, "wait_for_kagoya", lambda d, p: {"mode": "live", "result": "send_failed"})
    monkeypatch.setattr(ak, "_log", lambda line: None)
    called = []
    import revise.run_daily as rd
    monkeypatch.setattr(rd, "run_daily", lambda dry_run: called.append(dry_run) or 0)
    assert ak.main() == 0 and called == [False]


def test_falls_back_when_nothing_arrived(monkeypatch, tmp_path):
    monkeypatch.setattr(ak, "CSV_DIR", tmp_path)
    monkeypatch.setattr(ak, "wait_for_kagoya", lambda d, p: {})
    monkeypatch.setattr(ak, "_log", lambda line: None)
    called = []
    import revise.run_daily as rd
    monkeypatch.setattr(rd, "run_daily", lambda dry_run: called.append(dry_run) or 0)
    ak.main()
    assert called == [False]
