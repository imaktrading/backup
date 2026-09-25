"""押した後の件数比較は、走行が終わってから数え直した数字で行う (2026-09-24)。
走行中に始まった定期の数え直しとぶつかると古い数字で「減りませんでした (139→139)」と誤報していた。"""
import os

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "console", "server.py"),
           encoding="utf-8").read()


def test_waits_for_running_count_then_counts_again():
    body = SRC[SRC.index("def refresh_counts(wait=False"):SRC.index("BACKUP_STATUS")]
    assert body.index('while STATE["counting"]') < body.index('STATE["counting"] = True')
    assert 'STATE["counts_fresh"] = time.time()' in body


def test_drift_warning_only_with_fresh_counts():
    assert "refresh_counts(wait=True" in SRC          # 2026-09-25: keys= (押したボタンの分だけ) が付いた
    assert 'STATE.get("counts_fresh", 0) >= _t_done' in SRC
