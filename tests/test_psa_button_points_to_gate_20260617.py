"""Regression: 2026-06-17 — 「PSA再仕入れ照合」ボタンは psa_resource_gate.py を起動する。

旧 mercari_psa_resource.py(Mercari単体・確認ゲート/PDCA無し)に張替わると、せっかくの
①現物=②catalog 目視確認ゲートも不一致PDCAも走らない。ボタンが gate を指すことを固定。
"""
from pathlib import Path

_SRC = (Path(__file__).resolve().parent.parent / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")


def test_psa_button_runs_gate_not_old_mercari_only():
    i = _SRC.index("🃏 PSA再仕入れ照合")
    block = _SRC[i:i + 600]
    assert '"psa_resource_gate.py"' in block, "PSA再仕入れ照合ボタンが gate を起動していない"
    assert '"mercari_psa_resource.py"' not in block, "旧Mercari単体スクリプトに戻っている"
