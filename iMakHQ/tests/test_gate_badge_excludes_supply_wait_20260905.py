# -*- coding: utf-8 -*-
"""①のラベルが押しても減らなかった件 (2026-09-05)。

ユーザー報告:「PSA再仕入れ①を押して目視したけど、ラベルの件数も減らないし、②も増えない」

実測 (2026-09-05):
    ラベル      : 今すぐ照合できる **44件**
    実際に出た件数: **0件** (照合対象なし)
    44件の内訳  : 待ち(供給なし) 43件 / 復活可 1件

= メルカリにもスニダンにも在庫が無い行を「今すぐ照合できる」に数えていた。
在庫が出れば台帳が自動で「復活可」に変わるので、**人が押しても動かせない**。
押しても減らないのは当然で、ラベルの定義が実態と違っていた。
"""
import os
import sys

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import psa_resource_gate as G  # noqa: E402
import psa_restock_wait as W  # noqa: E402

_GATE_SRC = open(os.path.join(_TOOLS, "psa_resource_gate.py"), encoding="utf-8").read()
_PANEL_SRC = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()


def test_supply_wait_statuses_are_the_ones_we_subtract():
    """差し引くのは「供給なし」と「在庫不明」。復活可 は照合できるので残す。"""
    assert W.ST_WAIT == "待ち(供給なし)"
    assert W.ST_UNKNOWN.startswith("在庫不明")
    assert "ST_WAIT, _prw.ST_UNKNOWN" in _GATE_SRC
    assert "_prw.ST_REVIVED" not in _GATE_SRC       # 復活可は差し引かない


def test_actionable_excludes_supply_wait():
    assert "and i not in supply_wait" in _GATE_SRC
    assert '"supply_wait":' in _GATE_SRC


def test_supply_wait_is_not_subtracted_when_the_tab_cannot_be_read():
    """台帳が読めない時は差し引かない (少なく言って見落とすより、多めのまま出す)。"""
    i = _GATE_SRC.index("supply_wait = set()")
    blk = _GATE_SRC[i:i + 600]
    assert "except Exception" in blk
    assert "読めない時は差し引かない" in blk


def test_label_shows_supply_wait_separately():
    assert "仕入元の在庫待ち %s件" in _PANEL_SRC
    assert "押しても動かせない" in _PANEL_SRC


def test_label_no_longer_blames_only_the_funnel():
    """0件の理由を「ファネル更新待ち」だけにしない (実際は在庫待ちが主因)。"""
    assert "仕入元に在庫が出るか、ファネルが更新されるまで増えません" in _PANEL_SRC
