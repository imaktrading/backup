"""担当→担当の依頼は **窓口を必ず通す** (2026-07-30).

担当は worktree 分離により他担当の領域を読めないため、相手の状況を知らないまま依頼する
ことになる。さらに相互に投入できると A→B→A の往復や無限ループが起きて誰も止められない。
→ 草案は共有の `_routing/` に置かせ、**投入は窓口だけ**が行う。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dispatch_worktree as dw  # noqa: E402
import route_inbox as ri  # noqa: E402


def _setup(tmp_path, monkeypatch, name, body="# 依頼\n本文\n"):
    routing = tmp_path / "_routing"
    routing.mkdir(parents=True)
    (tmp_path / "catalog" / "requests").mkdir(parents=True)
    monkeypatch.setattr(ri, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(ri, "ROUTING", routing)
    monkeypatch.setattr(ri, "ROUTED", routing / "_routed")
    p = routing / name
    p.write_text(body, encoding="utf-8")
    return p


def test_target_is_parsed_from_filename(tmp_path, monkeypatch):
    p = _setup(tmp_path, monkeypatch, "2026-07-30_dedupe_to_catalog_promo_sets.md")
    assert ri.target_of(p) == "catalog"


def test_unknown_target_is_rejected(tmp_path, monkeypatch):
    """宛先が読めない草案を勝手に配らない (誤配は無駄な作業を生む)。"""
    p = _setup(tmp_path, monkeypatch, "2026-07-30_something.md")
    r = ri.inject(p)
    assert r["ok"] is False and "宛先" in r["reason"]
    assert p.exists(), "失敗時に草案を消してはいけない"


def test_inject_writes_to_target_and_marks_origin(tmp_path, monkeypatch):
    """投入時に『窓口が確認して投入した』と起案元を明記する (責任の所在を残す)。"""
    p = _setup(tmp_path, monkeypatch, "2026-07-30_dedupe_to_catalog_x.md")
    r = ri.inject(p)
    assert r["ok"] is True and r["target"] == "catalog"
    body = r["dest"].read_text(encoding="utf-8")
    assert "窓口(Advisor)が宛先を確認して投入" in body
    assert "直接投入は禁止" in body
    assert not p.exists() and (tmp_path / "_routing" / "_routed" / p.name).exists(), \
        "投入済みは _routed に移して履歴を残す"


def test_explicit_to_overrides_filename(tmp_path, monkeypatch):
    p = _setup(tmp_path, monkeypatch, "2026-07-30_x_to_dedupe_y.md")
    (tmp_path / "catalog" / "requests").mkdir(parents=True, exist_ok=True)
    assert ri.inject(p, to="catalog")["target"] == "catalog"


def test_dispatch_prompts_forbid_direct_cross_posting():
    """下書き/実装 どちらの prompt でも『相手の requests に直接置くな』を明示すること。"""
    from pathlib import Path
    for p in (dw._build_prompt("catalog", [Path("x.md")]),
              dw._build_implement_prompt("catalog", [Path("x_response.md")])):
        assert "_routing" in p
        assert "直接置くのは禁止" in p
