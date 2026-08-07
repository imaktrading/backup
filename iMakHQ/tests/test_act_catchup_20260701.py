# -*- coding: utf-8 -*-
"""audit_catchup: headless Act 完了レポートの surface (2026-07-01)。

監査終了後 5-6分 BG 実行される Act の完了(ng_act_*.md)が対話中HQに届かず「ボーっと」に
見える問題の対策。marker より新しい ng_act_*.md のみ拾い、要点を抜粋することを検証。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import audit_catchup as m


def test_collect_fresh_act_reports_marker_gate(tmp_path):
    old = tmp_path / "ng_act_2026-06-30_tcg.md"
    new = tmp_path / "ng_act_2026-07-01_mercari.md"
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    # marker=1500 → new のみ
    fresh = m.collect_fresh_act_reports(str(tmp_path), 1500)
    assert [os.path.basename(f) for f in fresh] == ["ng_act_2026-07-01_mercari.md"]
    # marker=0 → 両方(mtime昇順)
    both = m.collect_fresh_act_reports(str(tmp_path), 0)
    assert [os.path.basename(f) for f in both] == [
        "ng_act_2026-06-30_tcg.md", "ng_act_2026-07-01_mercari.md"]


def test_collect_ignores_non_act_and_log(tmp_path):
    (tmp_path / "csv_auditor_2026-07-01_mercari.md").write_text("x", encoding="utf-8")
    (tmp_path / "ng_act_2026-07-01_mercari.log").write_text("x", encoding="utf-8")
    (tmp_path / "ng_act_2026-07-01_mercari.md").write_text("x", encoding="utf-8")
    fresh = m.collect_fresh_act_reports(str(tmp_path), 0)
    assert [os.path.basename(f) for f in fresh] == ["ng_act_2026-07-01_mercari.md"]


def test_summarize_prefers_youten_block():
    text = ("Warning: no stdin data received in 3s.\n"
            "Act phase 完了。要点:\n\n"
            "- ①CSV 12件 全OK\n"
            "- ③依頼0 / 誤検出12\n")
    out = m.summarize_act_report(text)
    assert out.startswith("Act phase 完了。要点:")
    assert "①CSV 12件 全OK" in out
    assert "no stdin" not in out  # 要点前のノイズは落とす


def test_summarize_caps_lines():
    text = "要点:\n" + "\n".join(f"- 行{i}" for i in range(50))
    out = m.summarize_act_report(text, max_lines=5)
    assert len(out.splitlines()) == 5


def test_act_marker_roundtrip(tmp_path):
    marker = tmp_path / "act_mk.txt"
    assert m._last_ts(str(marker)) == 0.0
    m._save_ts(999.0, str(marker))
    assert m._last_ts(str(marker)) == 999.0
