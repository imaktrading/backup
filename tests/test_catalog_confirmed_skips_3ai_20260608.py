"""Regression: 2026-06-08 catalog ID hit/人手verify済 は 3AI を通さず決定論判定.

背景: 3AI 合議が API障害(Gemini ServerError/Claude JSONDecodeError)で valid card を誤BLOCK
(例 Mega Latias #079/063 secret rare)。catalog が ID 完全一致で身元確定済なら、flaky な AI に
身元を再判定させる必要はない → validate_row(決定論) を通れば PASS、3AI skip。

固定する不変条件:
  - catalog_confirmed=True かつ DETERMINISTIC_ON_CONFIRMED=True → 3AI(deliberate_3ai)を呼ばず PASS。
  - catalog_confirmed=False → 従来どおり 3AI に進む。
  - validate_row の error は confirmed でも reject (誤出品しない)。
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


def _setup(V):
    V.validate_row = lambda *a, **k: ([], [])          # error 無し
    V._check_acceptable = lambda *a, **k: (False, "")   # 許容ショートカット無効
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return {"final_verdict": "BLOCK", "history": "fake", "rounds": [{"round": 1, "opinions": {}}]}
    V.deliberate_3ai = fake
    return calls


_ARGS = dict(title="t", specs={}, model="", category=183454, condition_id=2750, price=1.0, pic_url="http://x")


def test_confirmed_skips_3ai():
    V = _load(); calls = _setup(V)
    r = V.validate_and_report("c1", **_ARGS, catalog_confirmed=True)
    assert r is True and calls["n"] == 0   # PASS / 3AI 呼ばない


def test_unconfirmed_uses_3ai():
    V = _load(); calls = _setup(V)
    r = V.validate_and_report("c2", **_ARGS, catalog_confirmed=False)
    assert r is False and calls["n"] == 1   # 従来どおり 3AI に進む


def test_confirmed_still_rejects_on_error():
    """confirmed でも validate_row が error なら reject (誤出品しない)。"""
    V = _load(); _setup(V)
    V.validate_row = lambda *a, **k: (["必須Item Specific 'X' が空"], [])
    r = V.validate_and_report("c3", **_ARGS, catalog_confirmed=True)
    assert r is False


def test_rollback_flag_off_uses_3ai():
    """DETERMINISTIC_ON_CONFIRMED=False で従来挙動 (confirmed でも 3AI) に戻る = rollback。"""
    V = _load(); calls = _setup(V)
    V.DETERMINISTIC_ON_CONFIRMED = False
    r = V.validate_and_report("c4", **_ARGS, catalog_confirmed=True)
    assert calls["n"] == 1   # flag off → 3AI に進む
