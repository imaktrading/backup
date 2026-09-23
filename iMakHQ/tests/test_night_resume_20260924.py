"""夜間バッチを手順ごとに印を付けて走らせ、PC が落ちても続きから再開する (2026-09-24)。
ユーザー判断「落ちる前提でやるしかない。途中から再開できるようにしておけば」。"""
import io
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import night_step as S                                         # noqa: E402
import night_resume as R                                       # noqa: E402

NOW = datetime(2026, 9, 24, 2, 30)


def test_resume_within_window_else_new_run():
    st = {"started_at": "2026-09-23T23:30:00", "finished": False, "steps": {"a": {"status": "done"}}}
    st2, resumed = S.begin(st, NOW)
    assert resumed and st2["steps"]["a"]["status"] == "done"
    old = dict(st, started_at="2026-09-22T23:30:00")
    assert S.begin(old, NOW)[1] is False
    assert S.begin(dict(st, finished=True), NOW)[1] is False


def test_decide_skips_done_and_protects_ebay_steps():
    st = {"steps": {"done": {"status": "done"},
                    "crashed": {"status": "running", "attempts": 1},
                    "looped": {"status": "running", "attempts": 2},
                    "failed": {"status": "failed", "attempts": 1}}}
    assert S.decide(st, "done") == "skip_done"
    assert S.decide(st, "crashed") == "run"
    assert S.decide(st, "crashed", no_retry=True) == "skip_interrupted"
    assert S.decide(st, "looped") == "skip_loop"
    assert S.decide(st, "failed") == "run"
    assert S.decide(st, "new") == "run"


def test_check_and_done_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "STATE_DIR", str(tmp_path))
    d = str(tmp_path)
    S.load.__defaults__ = (d,)
    S.save.__defaults__ = (d,)
    assert S.main(["hoju", "--begin"]) == 0
    assert S.main(["hoju", "a", "--check"]) == 0          # 走らせてよい
    assert S.main(["hoju", "a", "--done", "0"]) == 0
    assert S.main(["hoju", "a", "--check"]) == 1          # 済んだので飛ばす
    assert S.main(["hoju", "b", "--check", "--no-retry"]) == 0
    # b の最中に落ちた → 次の走行で eBay 手順はやり直さない
    assert S.main(["hoju", "--begin"]) == 0
    assert S.main(["hoju", "b", "--check", "--no-retry"]) == 1


def test_resume_plan_skips_running_and_unknown():
    st = {"started_at": datetime.now().isoformat(timespec="seconds"), "finished": False, "steps": {}}
    assert R.plan({"hoju": st}, set()) == ["hoju"]
    assert R.plan({"hoju": st}, {"run_hoju_search.bat"}) == []
    assert R.plan({"hoju": st}, None) == []
    assert R.plan({"hoju": dict(st, finished=True)}, set()) == []


def _bat(name):
    return io.open(os.path.join(HERE, "..", "tools", name), encoding="ascii").read()


def test_every_top_level_step_is_guarded_and_ebay_steps_are_no_retry():
    b = _bat("run_hoju_search.bat")
    assert "night_step.py hoju --begin" in b and "night_step.py hoju --end" in b
    for s in ("mirror_promo_bestoffer", "sold_restock", "supply_card_mismatch"):
        line = next(l for l in b.splitlines() if "night_step.py hoju " + s in l and "--check" in l)
        assert "--no-retry" in line, s
    assert sum("--check" in l for l in b.splitlines() if l.startswith("python")) == b.count("--done %errorlevel%")
    w = _bat("run_psa_cache_warm.bat")
    assert "night_step.py psawarm psa_cache_warm --check" in w
