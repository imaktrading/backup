# -*- coding: utf-8 -*-
"""`_routing/` の自動投入 回帰テスト (2026-08-09)。

なぜ必要か:
    窓口が手で `--inject` する設計だったため、**7日間 8件** 溜まっても誰も気づかなかった。
    `_routing/` は draft_triage (仕分け + 体制見直しライン) の対象外で、警告も鳴らない。
    ユーザー判断「そんな判断ラインいらない」= 仕分けも閾値も置かず全部流す。

ここで固定すること:
  - file 名から宛先が判れば **窓口を通さず投入**される
  - 宛先が判らないものは **捨てずに残る** (silent drop 禁止)
  - 投入した本文に「自動投入」と明記される (窓口が確認した、と偽らない)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import route_inbox as ri


def _setup(tmp_path, monkeypatch, names):
    routing = tmp_path / "_routing"
    routing.mkdir()
    for n in names:
        (routing / n).write_text(f"# {n}\n本文\n", encoding="utf-8")
    for t in ri.TARGETS:
        (tmp_path / t / "requests").mkdir(parents=True)
    monkeypatch.setattr(ri, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(ri, "ROUTING", routing)
    monkeypatch.setattr(ri, "ROUTED", routing / "_routed")
    return routing


# ----- 宛先判定 -----

def test_target_from_to_pattern(tmp_path):
    from pathlib import Path
    assert ri.target_of(Path("2026-08-03_catalog_to_hq_foo.md")) == "hq"
    assert ri.target_of(Path("2026-08-01_hq_to_catalog_bar.md")) == "catalog"
    assert ri.target_of(Path("2026-08-05_catalog_to_harvest_baz.md")) == "harvest"


def test_target_from_internal_pattern(tmp_path):
    """`<担当>_internal_<topic>` は自分宛 (実在: catalog_internal_promo_fallback_tighten)。"""
    from pathlib import Path
    assert ri.target_of(Path("2026-08-04_catalog_internal_promo_tighten.md")) == "catalog"


def test_target_unknown_returns_empty(tmp_path):
    from pathlib import Path
    assert ri.target_of(Path("2026-08-04_something_else.md")) == ""


# ----- 自動投入 -----

def test_auto_route_injects_every_resolvable_draft(tmp_path, monkeypatch):
    routing = _setup(tmp_path, monkeypatch, [
        "2026-08-03_catalog_to_hq_a.md",
        "2026-08-01_hq_to_catalog_b.md",
        "2026-08-04_catalog_internal_c.md",
    ])
    r = ri.auto_route()
    assert sorted(t for _, t in r["injected"]) == ["catalog", "catalog", "hq"]
    assert r["unknown"] == []
    assert (tmp_path / "hq" / "requests" / "2026-08-03_catalog_a.md").exists()
    assert not list(routing.glob("*.md"))            # 投入済みは _routed へ退避


def test_auto_route_keeps_unknown_target_instead_of_dropping(tmp_path, monkeypatch):
    """宛先不明を黙って捨てない (捨てると起案者は永久に気づけない)。"""
    routing = _setup(tmp_path, monkeypatch, ["2026-08-04_no_target_here.md"])
    r = ri.auto_route()
    assert r["injected"] == []
    assert r["unknown"] == ["2026-08-04_no_target_here.md"]
    assert (routing / "2026-08-04_no_target_here.md").exists()


def test_injected_body_says_it_was_automatic(tmp_path, monkeypatch):
    """『窓口が確認した』と偽らない。差し戻し方も本文に書く。"""
    _setup(tmp_path, monkeypatch, ["2026-08-03_catalog_to_hq_a.md"])
    ri.auto_route()
    body = (tmp_path / "hq" / "requests" / "2026-08-03_catalog_a.md").read_text(encoding="utf-8")
    assert "自動投入" in body
    assert "窓口(Advisor)が宛先を確認して投入しました" not in body
    assert "_question.md" in body                     # 差し戻し経路を案内している


def test_manual_inject_keeps_window_header(tmp_path, monkeypatch):
    """窓口が手で投入した時は従来どおりの表記 (経路が区別できること)。"""
    routing = _setup(tmp_path, monkeypatch, ["2026-08-03_catalog_to_hq_a.md"])
    ri.inject(routing / "2026-08-03_catalog_to_hq_a.md")
    body = (tmp_path / "hq" / "requests" / "2026-08-03_catalog_a.md").read_text(encoding="utf-8")
    assert "窓口(Advisor)が宛先を確認して投入しました" in body


def test_auto_route_dry_run_changes_nothing(tmp_path, monkeypatch):
    routing = _setup(tmp_path, monkeypatch, ["2026-08-03_catalog_to_hq_a.md"])
    r = ri.auto_route(dry_run=True)
    assert len(r["injected"]) == 1
    assert (routing / "2026-08-03_catalog_to_hq_a.md").exists()
    assert not (tmp_path / "hq" / "requests" / "2026-08-03_catalog_a.md").exists()


def test_auto_route_is_idempotent(tmp_path, monkeypatch):
    """2周目は投入対象ゼロ (watcher が毎周回呼ぶので二重投入しないこと)。"""
    _setup(tmp_path, monkeypatch, ["2026-08-03_catalog_to_hq_a.md"])
    assert len(ri.auto_route()["injected"]) == 1
    assert ri.auto_route() == {"injected": [], "unknown": []}
