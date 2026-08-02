"""失敗した実装は再試行される。ただし hot loop にはしない (2026-08-03).

実害 (2026-08-02 20:27→20:57):
  BRAVO が HQ に渡した offer_calc の実装が **30分 timeout** で失敗。ログには
  「⚠️ 失敗のため処理済にしない (次の周回で再試行)」と出たのに、**10時間経っても
  再試行されなかった**。実装キューは `impl_done` へ **走らせる前に** 登録しており、
  `_run_one` の「成功時だけ done」は既に入った印を消していなかった。
  = 8/1 に新規キューで潰した fail-OPEN が、実装キュー側に残っていた。

守りたいこと:
  - 失敗したら印を **取り消す** (次に拾える)
  - ただし即再投入はしない。30分 timeout を15秒ごとに繰り返すと課金と CPU を焼く
  - 成功したら印は残す (二度実装しない)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import dispatch_watch as dwatch  # noqa: E402


class _Lock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run(status, done, fail_at, monkeypatch, names=("x_response.md",)):
    monkeypatch.setattr(dwatch.dw, "acquire_lock", lambda wt: True)
    monkeypatch.setattr(dwatch.dw, "release_lock", lambda wt: None)
    monkeypatch.setattr(dwatch.dw, "_dispatch",
                        lambda wt, dry_run, mode: {"status": status, "summary": ""})
    dwatch._run_one("hq", ", ".join(names), done, list(names), set(), _Lock(),
                    "implement", fail_at)


class TestRetryOnFailure:
    def test_timeout_clears_the_done_mark(self, monkeypatch):
        """★これが 8/2 の実害。timeout でも印が残り、二度と拾われなかった."""
        done = {"hq": {"x_response.md"}}          # 走らせる前に入れた印
        fail_at = {}
        _run("timeout", done, fail_at, monkeypatch)
        assert "x_response.md" not in done["hq"], "失敗したら印を取り消すこと"

    def test_failure_is_remembered_for_cooldown(self, monkeypatch):
        done = {"hq": {"x_response.md"}}
        fail_at = {}
        _run("timeout", done, fail_at, monkeypatch)
        assert ("hq", "x_response.md") in fail_at
        assert time.time() - fail_at[("hq", "x_response.md")] < 5

    def test_exit1_also_clears(self, monkeypatch):
        done = {"hq": {"x_response.md"}}
        _run("exit1", done, {}, monkeypatch)
        assert not done["hq"]

    def test_success_keeps_the_mark(self, monkeypatch):
        done = {"hq": set()}
        fail_at = {}
        _run("ok", done, fail_at, monkeypatch)
        assert done["hq"] == {"x_response.md"}, "成功したら二度実装しない"
        assert fail_at == {}

    def test_multiple_names_all_cleared(self, monkeypatch):
        done = {"hq": {"a.md", "b.md"}}
        fail_at = {}
        _run("timeout", done, fail_at, monkeypatch, names=("a.md", "b.md"))
        assert done["hq"] == set()
        assert set(fail_at) == {("hq", "a.md"), ("hq", "b.md")}

    def test_fail_at_is_optional(self, monkeypatch):
        """draft キューは fail_at を渡さない。None でも落ちないこと."""
        done = {"hq": {"x_response.md"}}
        _run("timeout", done, None, monkeypatch)
        assert not done["hq"]


class TestCooldown:
    def test_cooldown_is_long_enough_to_avoid_hot_loop(self):
        """poll は15秒。冷却がそれ未満だと 30分 timeout を焼き続ける."""
        assert dwatch.RETRY_COOLDOWN_SEC >= 10 * 60
        assert dwatch.RETRY_COOLDOWN_SEC > dwatch.POLL_SEC * 4

    def test_cooldown_filter_skips_recent_failure(self):
        """main の絞り込みと同じ式を、境界で確かめる (純粋な時間計算)."""
        fail_at = {("hq", "x.md"): 1000.0}
        cd = dwatch.RETRY_COOLDOWN_SEC

        def eligible(now):
            return now - fail_at.get(("hq", "x.md"), 0) >= cd

        assert not eligible(1000.0 + cd - 1), "冷却中は拾わない"
        assert eligible(1000.0 + cd), "冷却が明けたら拾う"

    def test_unknown_file_is_eligible_immediately(self):
        fail_at = {}
        assert time.time() - fail_at.get(("hq", "new.md"), 0) >= dwatch.RETRY_COOLDOWN_SEC
