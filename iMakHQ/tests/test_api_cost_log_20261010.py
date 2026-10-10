# -*- coding: utf-8 -*-
"""有料 API の呼び出しを記録する (2026-10-10 ユーザー「API コストを減らさないと」)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import api_cost_log as A  # noqa: E402


def test_cost_by_model_prefix():
    u = {"input_tokens": 1_000_000, "output_tokens": 100_000}
    assert A.cost_usd("claude-sonnet-4-6", u) == 4.5
    assert A.cost_usd("claude-haiku-4-5-20251001", u) == 1.5
    assert A.cost_usd("claude-opus-5-5", u) is None          # 単価不明は金額を出さない
    assert A.cost_usd("claude-haiku-4-5", {"cache_read_input_tokens": 1_000_000}) == 0.1


def test_summarize_by_program():
    rows = [{"at": "2026-10-10T10:00:00", "prog": "a.py", "usd": 0.5},
            {"at": "2026-10-10T11:00:00", "prog": "a.py", "usd": None},
            {"at": "2026-10-01T11:00:00", "prog": "b.py", "usd": 9.0}]
    assert A.summarize(rows, "2026-10-10") == {"a.py": [2, 0.5, 1]}


def test_record_never_raises(tmp_path, monkeypatch):
    p = str(tmp_path / "x" / "log.jsonl")
    monkeypatch.setattr(A, "LOG", p)
    A.record("claude-haiku-4-5", {"input_tokens": 10, "output_tokens": 2}, 0.3)
    assert A.load(p)[0]["input_tokens"] == 10
    monkeypatch.setattr(A, "LOG", "\0bad")
    A.record("m", {})                                         # 書けなくても例外を出さない


def test_install_wraps_create_once():
    import anthropic.resources.messages as m
    A.install()
    assert getattr(m.Messages.create, "_imak_cost", False)
    first = m.Messages.create
    A.install()
    assert m.Messages.create is first


def test_caller_and_images():
    def my_job():
        return A.caller_of()
    assert my_job().endswith(":my_job")
    msgs = [{"role": "user", "content": [{"type": "image", "source": {}}, {"type": "text", "text": "x"},
                                         {"type": "image", "source": {}}]}]
    assert A.count_images(msgs) == 2 and A.count_images(None) == 0
