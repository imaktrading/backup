# -*- coding: utf-8 -*-
"""PSA 再仕入れ ① 目視 → ② 在庫を戻す → ③ 確認 を1回で (2026-10-04 ユーザー「ボタン分けずに」)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
sys.path.insert(0, os.path.join(HERE, ".."))
import psa_restock_chain as C  # noqa: E402


def test_runs_all_three_in_order():
    ran = []
    assert C.run_chain(run=lambda a: ran.append(a[0]) or 0) == 0
    assert ran == ["psa_resource_gate.py", "psa_restock_build.py", "psa_restock_writeback.py"]


def test_stops_when_step_fails():
    ran = []

    def run(a):
        ran.append(a[0])
        return 1 if a[0] == "psa_resource_gate.py" else 0
    assert C.run_chain(run=run) == 1
    assert ran == ["psa_resource_gate.py"]


def test_button_one_runs_the_chain():
    import control_panel as cp
    b = [s for s in cp.SCRIPTS if s["label"] == "🛒 PSA 再仕入れ ① 目視"][0]
    assert b["cmd"] == ["python", "psa_restock_chain.py"]
    assert any(s["label"].startswith("🛒 PSA 再仕入れ ②") for s in cp.SCRIPTS)   # やり直し用に残す


def test_chain_tells_step2_not_to_run_step3_itself():
    """② は単独だと最後に ③ を呼ぶ。chain の中では止めて、③ を chain が毎回1回だけ回す。"""
    src = open(os.path.join(HERE, "..", "tools", "psa_restock_build.py"), encoding="utf-8").read()
    assert 'not os.environ.get("PSA_RESTOCK_CHAIN")' in src
    chain = open(os.path.join(HERE, "..", "tools", "psa_restock_chain.py"), encoding="utf-8").read()
    assert 'PSA_RESTOCK_CHAIN="1"' in chain


def test_kamikaze_hides_steps_2_and_3():
    js = open(os.path.join(HERE, "..", "console", "static", "app.js"), encoding="utf-8").read()
    i = js.index("var HIDDEN_KINDS")
    assert '"restock_build", "restock_wb"' in js[i:i + 120]
    assert '["PSA", ["psa_gate", null, null]]' in js


def test_kamikaze_hides_sold_restock_button():
    """売れた分を補充は目視なし・毎晩自動 → 神風に押すボタンを出さない (2026-10-04)。"""
    js = open(os.path.join(HERE, "..", "console", "static", "app.js"), encoding="utf-8").read()
    i = js.index("var HIDDEN_KINDS")
    assert '"sold_restock"' in js[i:i + 300]
