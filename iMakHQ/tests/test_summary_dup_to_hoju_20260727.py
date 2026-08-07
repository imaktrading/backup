# -*- coding: utf-8 -*-
"""監査サマリーで「重複除外 → 補URL追加」をセットで報告する (2026-07-27)。

ユーザー指摘: 重複で弾いた分を「除外1件」とだけ報告すると**機会損失に見える**。
実際は `hoju_url_from_dupes` が **弾いた2枚目の仕入元URLを live primary の補URL に移して**おり、
出品は1枠に絞りつつ**供給を厚くしている**(在庫情報は捨てていない)。
実例(2026-07-27): EBB-045 Mewtwo-EX の2枚目 cert140142776 の mercari URL が
row1320(itemID 358790364617)の補URLへ 0本→1本 で登録された。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from control_panel import summarize_audit_log  # noqa: E402

LOG_DUP_AND_HOJU = """
  🟢 CSV UPシグナル即発報: 5件 入稿OK → UPして
  removed (真の重複・全て live 一致): 1
=== 補URL 追記 [実書込] (2枚目→primary補URL・既存保持+冪等) ===
シート行数 1520 / 追加対象primary 1行 / 追加URL 1
"""

LOG_DUP_NO_HOJU = """
  🟢 CSV UPシグナル即発報: 3件 入稿OK → UPして
  removed (真の重複・全て live 一致): 2
シート行数 1520 / 追加対象primary 0行 / 追加URL 0
"""

LOG_NO_DUP = """
  🟢 CSV UPシグナル即発報: 4件 入稿OK → UPして
  removed (真の重複・全て live 一致): 0
"""


def test_dup_exclusion_is_reported_with_hoju_addition():
    """★重複除外は「補URLに追加した」とセットで出す。"""
    s = summarize_audit_log(LOG_DUP_AND_HOJU)
    assert "♻ 重複除外 1件 → 補URL 1本 追加" in s
    assert "供給を厚くした" in s


def test_dup_without_hoju_is_stated_explicitly():
    """補URL に足せなかった時は、足せなかったと明示する(黙って除外だけ報告しない)。"""
    s = summarize_audit_log(LOG_DUP_NO_HOJU)
    assert "♻ 重複除外 2件 (補URL 追加なし" in s


def test_no_dup_no_line():
    s = summarize_audit_log(LOG_NO_DUP)
    assert "重複除外" not in s
    assert "入稿OK: 4件" in s
