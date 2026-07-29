"""完了報告 `_done.md` の機械検査 (2026-07-30).

dispatch を並列化したら、完了報告の検証が窓口(1人)に集中した。窓口は worktree 分離により
他 worktree のコードを読めない = 報告書を精読しても確度は上がらない。
→ **証拠の有無は機械で判定**し、窓口は異常だけ読む。
「証拠の無い完了報告は完了とみなさない」を機械で担保するのが目的。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import done_check as dc  # noqa: E402


def _mk(tmp_path, wt, name, body):
    d = tmp_path / wt / "requests"
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body, encoding="utf-8")
    return p


GOOD = """# 実装完了
- commit: 4d5b74e
- テスト: `python -m pytest -q` → 128 passed
- 変更: tools/foo.py:120
"""


def test_good_report_passes(tmp_path):
    p = _mk(tmp_path, "catalog", "x_response_done.md", GOOD)
    assert dc.check_one(p)["ok"] is True


def test_missing_commit_is_flagged(tmp_path):
    p = _mk(tmp_path, "catalog", "x_response_done.md", "テスト: 12 passed\n")
    r = dc.check_one(p)
    assert r["ok"] is False and any("commit" in x for x in r["reasons"])


def test_missing_test_result_is_flagged(tmp_path):
    """『テストした』の自己申告だけでは通さない。件数が要る。"""
    p = _mk(tmp_path, "catalog", "x_response_done.md", "commit: 4d5b74e\nテストしました\n")
    r = dc.check_one(p)
    assert r["ok"] is False and any("テスト" in x for x in r["reasons"])


def test_partial_implementation_is_surfaced(tmp_path):
    """『一部未実装』は証拠が揃っていても窓口が読む (黙って流さない)。"""
    p = _mk(tmp_path, "catalog", "x_response_done.md", GOOD + "\n一部は未実装です\n")
    r = dc.check_one(p)
    assert r["ok"] is False and any("要読解" in x for x in r["reasons"])


def test_scan_collects_all_worktrees(tmp_path):
    _mk(tmp_path, "catalog", "a_response_done.md", GOOD)
    _mk(tmp_path, "harvest", "b_response_done.md", "証拠なし")
    _mk(tmp_path, "harvest", "c_response.md", GOOD)          # _done でない = 対象外
    rows = dc.scan(root=tmp_path)
    assert {r["path"].name for r in rows} == {"a_response_done.md", "b_response_done.md"}
    assert sum(1 for r in rows if not r["ok"]) == 1


def test_scan_can_filter_by_date(tmp_path):
    _mk(tmp_path, "catalog", "2026-07-30_a_response_done.md", GOOD)
    _mk(tmp_path, "catalog", "2026-06-01_old_response_done.md", GOOD)
    rows = dc.scan(root=tmp_path, since_prefix="2026-07-30")
    assert len(rows) == 1
