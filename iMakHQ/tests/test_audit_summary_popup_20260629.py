# -*- coding: utf-8 -*-
"""control_panel.summarize_audit_log: CSV監査くん完走時のサマリー抽出 回帰テスト
(2026-06-29)。出品くんが GUI で能動報告する用(対話セッションは外部から起こせないため)。"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))

import importlib.util
_CP = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "control_panel.py"))
_spec = importlib.util.spec_from_file_location("control_panel", _CP)
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)


_REAL_LOG = """
  ❌ 除外(出品しない): 0件 (行 [])
  🏁 市場ゲート: GO 0 / RELAX 4 / 保留HOLD 1 / ❌NO-GO 0
  📨 カタログ修正依頼: 1件 → C:\\dev\\...\\2026-06-29_audit_catalog_fix_tcg.md
  🛠 プログラム修正依頼: 0件
  🟢 CSV UPシグナル即発報: 7件 入稿OK → UPして(headless③は裏で継続)
  🔁 再発finding(catalog依頼/修正で消えない) 22件 → 構造/コード疑い
  🛠️ 未対応 program修正 backlog 1件 (実装=HQ / done で閉じる):
"""


def test_summary_extracts_key_points():
    s = cp.summarize_audit_log(_REAL_LOG)
    assert "入稿OK: 7件" in s
    assert "catalog依頼: 1件" in s
    assert "program backlog: 1件" in s
    assert "再発: 22件" in s
    # 0件のものは出さない
    assert "出品除外" not in s
    assert "市場NO-GO" not in s
    assert "program修正NG" not in s


def test_empty_log_returns_empty():
    assert cp.summarize_audit_log("") == ""
    assert cp.summarize_audit_log("無関係なログ") == ""


def test_nogo_and_exclusion_surface_when_present():
    log = ("❌ 除外(出品しない): 3件 (行 [1,2,3])\n"
           "🏁 市場ゲート: GO 1 / RELAX 0 / 保留HOLD 0 / ❌NO-GO 2\n"
           "🟢 CSV UPシグナル即発報: 5件 入稿OK → UPして")
    s = cp.summarize_audit_log(log)
    assert "出品除外: 3件" in s
    assert "市場NO-GO: 2件" in s
    assert "入稿OK: 5件" in s
