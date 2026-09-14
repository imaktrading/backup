"""Regression: 2026-09-14 act_code_proposals_mercari 提案3.

背景: Groq のモデル "llama-3.3-70b-versatile" は既に Groq のモデル一覧から消えていて
毎回 ABSTAIN (NotFoundError) になっていた。合意判定は ABSTAIN を除外するため、
Claude/Gemini の2票だけで「3AI合意」と表示されていた (黙って人数が減る = 一番困るパターン)。

固定する不変条件:
  - Groq の model 引数は現存する GROQ_MODEL 定数を使う (退役モデル文字列のハードコード禁止)。
  - ABSTAIN が混じった合意は agreement_label に実数 (例 "2AI合意") を出し、
    ABSTAIN したAI名も添える。「3AI合意」と偽らない。
  - 全員が回答した通常ケースは従来どおり "3AI合意" 相当 ("3AI合意") のまま。
"""
import importlib.util
import sys
from pathlib import Path

_API = Path(__file__).resolve().parent.parent / "iMakeBayAPI"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


def _load():
    spec = importlib.util.spec_from_file_location("listing_validator", str(_API / "listing_validator.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_groq_model_is_not_the_retired_id():
    """Groq に渡す model 文字列が retire 済みの llama-3.3-70b-versatile ではない。"""
    src = (_API / "listing_validator.py").read_text(encoding="utf-8")
    assert 'model="llama-3.3-70b-versatile"' not in src
    assert src.count("GROQ_MODEL") >= 3  # 定義1 + 呼び出し2箇所


def test_groq_abstain_does_not_claim_full_agreement():
    V = _load()
    V._ask_claude = lambda *a, **k: {"verdict": "PASS", "reason": "ok"}
    V._ask_gemini = lambda *a, **k: {"verdict": "PASS", "reason": "ok"}
    V._ask_groq = lambda *a, **k: {"verdict": "ABSTAIN", "reason": "Groq利用不可"}

    result = V.deliberate_3ai("title", {})
    assert result["final_verdict"] == "PASS"
    assert result["agreement_label"] == "2AI合意 (Groq: 利用不可)"
    assert "3AI合意" not in result["agreement_label"]


def test_all_ai_respond_reports_full_count():
    V = _load()
    V._ask_claude = lambda *a, **k: {"verdict": "PASS", "reason": "ok"}
    V._ask_gemini = lambda *a, **k: {"verdict": "PASS", "reason": "ok"}
    V._ask_groq = lambda *a, **k: {"verdict": "PASS", "reason": "ok"}

    result = V.deliberate_3ai("title", {})
    assert result["final_verdict"] == "PASS"
    assert result["agreement_label"] == "3AI合意"


def test_validate_and_report_prints_actual_agreement_label(capsys):
    V = _load()
    V.validate_row = lambda *a, **k: ([], [])
    V._check_acceptable = lambda *a, **k: (False, "")
    V.deliberate_3ai = lambda *a, **k: {
        "final_verdict": "PASS", "history": "h", "rounds": [],
        "agreement_label": "2AI合意 (Groq: 利用不可)",
    }
    args = dict(title="t", specs={}, model="", category=15687, condition_id=1000,
                price=1.0, pic_url="http://x")
    r = V.validate_and_report("c1", **args, catalog_confirmed=False)
    assert r is True
    out = capsys.readouterr().out
    assert "2AI合意 (Groq: 利用不可)" in out
    assert "✅ 3AI合意" not in out
