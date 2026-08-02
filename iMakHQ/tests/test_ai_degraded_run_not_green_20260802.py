"""AI 段が落ちた走行を「🟢 入稿OK」で終わらせない (2026-08-02).

実害 (2026-08-02 19:10 の走行):
  Anthropic API が credit 不足になり TitleAgent / Vision / AI総合レビューが**全カードで失敗**
  したのに、走行はそのまま続き、最後は緑の「🟢 CSV UPシグナル即発報: 6件 入稿OK → UPして」で
  終わった。落ちた事実は行間のログにしかなく、タイトルが3本 70字を割って初めて気づいた
  (short_titles 3件 / avg_title_len -7.2)。= degraded なのに正常と報告する fail-OPEN。

守りたいこと:
  - **呼べたのに失敗した**時は ⚠️ に倒す (クレジット不足 / レート制限 / 過負荷 / 認証)
  - **key 未設定**は環境設定なので倒さない (毎回 ⚠️ になると警告が意味を失う)
  - 通知本文も緑にしない
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import csv_auditor as ca  # noqa: E402
import notify_csv_ready as ncr  # noqa: E402

CREDIT_ERR = (
    "    Claude APIエラー: Error code: 400 - {'type': 'error', 'error': "
    "{'type': 'invalid_request_error', 'message': 'Your credit balance is too low "
    "to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.'}}"
)


def _log(tmp_path, text: str) -> str:
    p = tmp_path / "run.log"
    p.write_text(text, encoding="utf-8")
    return str(p)


class TestAiDegraded:
    def test_credit_shortage_is_detected(self, tmp_path):
        got = ca.ai_degraded(_log(tmp_path, CREDIT_ERR * 3))
        assert got and any("クレジット" in g for g in got)

    def test_counts_occurrences(self, tmp_path):
        got = ca.ai_degraded(_log(tmp_path, CREDIT_ERR + "\n" + CREDIT_ERR))
        assert "APIクレジット不足: 2件" in got

    def test_rate_limit_is_detected(self, tmp_path):
        assert ca.ai_degraded(_log(tmp_path, "rate_limit_error occurred"))

    def test_overloaded_is_detected(self, tmp_path):
        assert ca.ai_degraded(_log(tmp_path, "overloaded_error"))

    def test_missing_key_is_not_degraded(self, tmp_path):
        """key 未設定はその環境の正常状態。倒すと毎回 ⚠️ になり意味を失う."""
        txt = "⚠️ Claude APIキーなし。AI総合レビューをスキップします。"
        assert ca.ai_degraded(_log(tmp_path, txt)) == []

    def test_clean_log_is_not_degraded(self, tmp_path):
        assert ca.ai_degraded(_log(tmp_path, "✓ eBay API 接続OK\n完了")) == []

    def test_claude_exception_text_is_degraded(self):
        assert ca.ai_degraded("", "(Claude review skip: TimeoutError)")

    def test_missing_log_does_not_crash(self):
        assert ca.ai_degraded("C:/no/such/file.log", "") == []


class TestGenerationLogIsAlsoRead:
    """★今日の実ケース: 劣化は **生成側** で起き、監査くん自身のログには何も出ない。

    監査くんが自分のログしか見ないと、緑のまま入稿される (2026-08-02 の実害)。
    """

    def _logs(self, tmp_path, csv_name):
        gen = tmp_path / "gen_1900.log"
        gen.write_text(f"TitleAgent...\n{CREDIT_ERR}\n完了！出力: C:/out/{csv_name}\n",
                       encoding="utf-8")
        own = tmp_path / "audit_1910.log"          # 監査くん自身のログ (劣化の証拠なし)
        own.write_text(f"✓ eBay API 接続OK\n対象: C:/out/{csv_name}\n完了\n", encoding="utf-8")
        import os
        os.utime(own, (9 << 30, 9 << 30))          # 監査ログの方を新しくする
        return str(gen), str(own)

    def test_finds_every_log_touching_the_csv(self, tmp_path):
        gen, own = self._logs(tmp_path, "tcg_upload_X.csv")
        got = ca.generation_logs_for("C:/out/tcg_upload_X.csv", str(tmp_path))
        assert set(got) == {gen, own}, "1本に絞ると生成側を取り逃がす"

    def test_degraded_even_when_own_log_is_clean(self, tmp_path):
        _gen, own = self._logs(tmp_path, "tcg_upload_X.csv")
        assert ca.ai_degraded(own, "", "C:/out/tcg_upload_X.csv", str(tmp_path))

    def test_clean_generation_stays_green(self, tmp_path):
        (tmp_path / "gen.log").write_text("完了！出力: C:/out/ok.csv\n", encoding="utf-8")
        assert ca.ai_degraded("", "", "C:/out/ok.csv", str(tmp_path)) == []

    def test_no_csv_path_is_safe(self):
        assert ca.generation_logs_for("") == []


class TestSignalNotGreen:
    def _spy(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(ca, "_act_disabled", lambda dry: False)
        monkeypatch.setattr(ca, "_detached_spawn", lambda cmd: seen.setdefault("cmd", cmd))
        return seen

    def test_degraded_run_is_not_green(self, monkeypatch, capsys):
        self._spy(monkeypatch)
        r = ca._signal_csv_up("x.csv", 6, False, ["APIクレジット不足: 9件"])
        out = capsys.readouterr().out
        assert r == "fired_degraded"
        assert "🟢" not in out
        assert "⚠️" in out and "APIクレジット不足" in out

    def test_clean_run_stays_green(self, monkeypatch, capsys):
        self._spy(monkeypatch)
        r = ca._signal_csv_up("x.csv", 6, False, [])
        assert r == "fired"
        assert "🟢" in capsys.readouterr().out

    def test_reason_is_passed_to_notifier(self, monkeypatch):
        seen = self._spy(monkeypatch)
        ca._signal_csv_up("x.csv", 6, False, ["APIクレジット不足: 9件", "APIレート制限: 1件"])
        assert seen["cmd"][-1] == "APIクレジット不足: 9件 | APIレート制限: 1件"

    def test_clean_run_passes_no_extra_arg(self, monkeypatch):
        seen = self._spy(monkeypatch)
        ca._signal_csv_up("x.csv", 6, False, [])
        assert len(seen["cmd"]) == 4, "劣化なしなら従来どおり3引数 (python 含め4)"


class TestNotifyMessage:
    def test_degraded_message_is_not_green(self):
        m = ncr.build_message(6, "tcg_upload.csv", "APIクレジット不足: 9件")
        assert "🟢" not in m
        assert "⚠️" in m and "APIクレジット不足: 9件" in m

    def test_clean_message_is_green(self):
        assert "🟢" in ncr.build_message(6, "tcg_upload.csv")

    def test_main_reads_third_arg(self, monkeypatch):
        got = {}
        monkeypatch.setattr(ncr, "notify", lambda c, p, d="": got.update(c=c, p=p, d=d) or True)
        ncr.main(["6", "x.csv", "APIクレジット不足: 9件"])
        assert got["d"] == "APIクレジット不足: 9件"

    def test_main_without_third_arg(self, monkeypatch):
        got = {}
        monkeypatch.setattr(ncr, "notify", lambda c, p, d="": got.update(d=d) or True)
        ncr.main(["6", "x.csv"])
        assert got["d"] == ""
