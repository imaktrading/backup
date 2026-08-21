# -*- coding: utf-8 -*-
"""csv_auditor — Act の二重起動を止める / logシグナルが0件の行を数えない (2026-08-21).

回答書:
  - `2026-08-20_hq_act_proposals_ebay_norm_and_act_lock_response.md` (B)
  - `2026-08-19_psa_preflight_scope_ssot_gap_response.md` (2件目)

B の実害 (2026-08-20 実測):
    18:52 と 18:55 に headless Act が2プロセス起動し、両方が同じ CSV /
    同じ missing_models.csv / 同じ ng_act_*.md を触った。両方が同じ .md に書くので
    **後勝ちで片方の記録が消える**。

    ただ lock を置くだけだと、Act や PC が落ちた時に lock が残り、以後その CSV の NG が
    誰にも処理されない = **黙って止まる**。有効なのは「pid が生きている **かつ**
    30分以内」だけにして、それ以外は奪って起動する。

2件目の実害 (2026-08-19 18:04 実測):
    digest の `logシグナル 2件` は 3ヒットとも中身が **0件の行**だった
    (`❌ 除外(出品しない): 0件` 等)。ラベルの絵文字を数えていたため。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import csv_auditor as A  # noqa: E402


# ── B: Act の single-flight ────────────────────────────────────────────────
class TestActLock:
    def test_second_acquire_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(A, "REVIEW_DIR", str(tmp_path))
        csv = str(tmp_path / "tcg_upload_20260820_184616.csv")
        first, why = A._acquire_act_lock(csv)
        assert first and not why
        second, why2 = A._acquire_act_lock(csv)
        assert second is None, "同じ CSV に対して2本目が lock を取れてしまった"
        assert why2, "取れなかった理由を残していない (無言 skip は禁止)"

    def test_different_csv_is_independent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(A, "REVIEW_DIR", str(tmp_path))
        a, _ = A._acquire_act_lock(str(tmp_path / "tcg_a.csv"))
        b, _ = A._acquire_act_lock(str(tmp_path / "tcg_b.csv"))
        assert a and b, "別 CSV まで止めてはいけない"

    def test_expired_lock_is_stolen(self, tmp_path, monkeypatch):
        """★30分を超えた lock は奪う。奪えないと NG が誰にも処理されず黙って止まる。"""
        monkeypatch.setattr(A, "REVIEW_DIR", str(tmp_path))
        csv = str(tmp_path / "tcg_c.csv")
        path, _ = A._acquire_act_lock(csv)
        info = json.load(open(path, encoding="utf-8"))
        info["ts"] = info["ts"] - (A.ACT_LOCK_TTL_SEC + 60)
        json.dump(info, open(path, "w", encoding="utf-8"))
        again, why = A._acquire_act_lock(csv)
        assert again, f"期限切れ lock を奪えていない: {why}"

    def test_dead_pid_lock_is_stolen(self, tmp_path, monkeypatch):
        """Act / PC が落ちて pid が消えた lock も奪う。"""
        monkeypatch.setattr(A, "REVIEW_DIR", str(tmp_path))
        monkeypatch.setattr(A, "_pid_alive", lambda pid: False)
        csv = str(tmp_path / "tcg_d.csv")
        assert A._acquire_act_lock(csv)[0]
        assert A._acquire_act_lock(csv)[0], "死んだ pid の lock を奪えていない"

    def test_unreadable_lock_is_stolen(self, tmp_path, monkeypatch):
        monkeypatch.setattr(A, "REVIEW_DIR", str(tmp_path))
        csv = str(tmp_path / "tcg_e.csv")
        open(A._act_lock_path(csv), "w", encoding="utf-8").write("これは JSON ではない")
        assert A._acquire_act_lock(csv)[0], "壊れた lock で永久に止まってはいけない"

    def test_lock_live_needs_both_alive_and_fresh(self, monkeypatch):
        """有効 = pid が生きている **かつ** 期限内。片方でも外れたら無効。"""
        import time as _t
        monkeypatch.setattr(A, "_pid_alive", lambda pid: True)
        now = _t.time()
        assert A._act_lock_live({"pid": 1, "ts": now}, now=now)
        assert not A._act_lock_live({"pid": 1, "ts": now - A.ACT_LOCK_TTL_SEC - 1}, now=now)
        monkeypatch.setattr(A, "_pid_alive", lambda pid: False)
        assert not A._act_lock_live({"pid": 1, "ts": now}, now=now)

    def test_pid_alive_is_true_for_self(self):
        """自分の pid は生きている。判定不能を「死んだ」に倒すと二重起動が復活する。"""
        assert A._pid_alive(os.getpid())
        assert not A._pid_alive(0)
        assert not A._pid_alive("")

    def test_signal_act_spawns_only_once(self, tmp_path, monkeypatch):
        """★回答書の検収条件: 同じ csv_path で2回呼んで、起動が1回だけになること。"""
        spawned = []
        monkeypatch.setattr(A, "REVIEW_DIR", str(tmp_path))
        monkeypatch.setattr(A, "_act_disabled", lambda dry_run: False)
        monkeypatch.setattr(A, "_resolve_claude_exe", lambda p: sys.executable)
        monkeypatch.setattr(A, "_build_act_prompt",
                            lambda *a, **k: "prompt")
        monkeypatch.setattr(A, "_detached_spawn",
                            lambda argv, stdout_path=None, lock_path=None: spawned.append(argv))
        csv = str(tmp_path / "tcg_upload_20260820_184616.csv")
        assert A._signal_claude_act("tcg", csv, "", False) == "spawned"
        assert A._signal_claude_act("tcg", csv, "", False) == "locked"
        assert len(spawned) == 1, f"Act が {len(spawned)} 回起動した"


# ── logシグナル: 0件の行を数えない ─────────────────────────────────────────
class TestLogSignal:
    ZERO_LINES = ["  ❌ 除外(出品しない): 0件 (行 [])",
                  "  ❌ エラー: 0件"]

    def test_zero_count_lines_are_not_signals(self):
        for ln in self.ZERO_LINES:
            assert not A.line_is_signal(ln, A._SCAN_PATS[1][1]), ln
        assert A.scan_log_lines("\n".join(self.ZERO_LINES)) == []

    def test_nonzero_count_lines_are_signals(self):
        txt = "  ❌ 除外(出品しない): 3件 (行 [4, 9, 12])"
        assert A.scan_log_lines(txt) == ["error: 1件"]

    def test_line_without_count_is_still_a_signal(self):
        """素の Traceback / ERROR は件数表記が無いのでそのまま数える。"""
        assert A.scan_log_lines("Traceback (most recent call last):") == ["error: 1件"]

    def test_catalog_miss_counts_only_the_write_log_line(self):
        """パスやコメントに `missing_models` と出るだけでは数えない。"""
        noise = ("  # GAP は missing_models 経由で catalog へ\n"
                 "  出力: C:/dev/iMak_data/catalog/missing_models.csv\n"
                 "  ⚠️ Catalog 未登録カード 0 件\n")
        assert A.scan_log_lines(noise) == []
        real = noise + "⚠️ Catalog 未登録カード 4 件 (Catalog Claude に追加依頼してください)\n"
        assert A.scan_log_lines(real) == ["catalog miss: 1件"]

    def test_the_20260819_run_reports_nothing(self):
        """2026-08-19 18:04 の走行 = 3ヒット全部が誤検出だった。今は0件になる。"""
        txt = ("  ❌ 除外(出品しない): 0件 (行 [])\n"
               "  ❌ エラー: 0件\n"
               "  # GAP は missing_models 経由で catalog へ\n")
        assert A.scan_log_lines(txt) == []
