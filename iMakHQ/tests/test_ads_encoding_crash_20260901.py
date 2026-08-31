# -*- coding: utf-8 -*-
"""ads_add_new_listings.py が cp932 コンソールで絵文字 print に落ちない (2026-09-01)。

実害: Windows既定の cp932 コンソールで実行すると、追加予定を並べる print (絵文字
入り、create_ads の**手前**にあるプレビュー表示) で UnicodeEncodeError が起き、
「対象11件→追加11」と出た**直後**にクラッシュしていた。この行は計画件数の
表示でしかなく、実際の eBay 書込 (create_ads) には一度も到達していなかった。
=> ログだけ見ると成功に見えるが、広告は1件も追加されていない (silent failure)。
"""
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

_SRC = open(os.path.join(_TOOLS, "ads_add_new_listings.py"), encoding="utf-8").read()


def test_stdout_is_reconfigured_before_main_runs():
    """cp932 既定コンソールでの絵文字クラッシュを防ぐ再設定が入っていること。"""
    assert "sys.stdout.reconfigure(" in _SRC
    i_reconf = _SRC.index("sys.stdout.reconfigure(")
    i_main_def = _SRC.index("def main")
    assert i_reconf < i_main_def, "reconfigure が main() の定義より後 = 手遅れ"


def test_preview_print_precedes_the_real_write_call():
    """このテストの前提確認: プレビュー表示 (絵文字あり) は create_ads 呼出より前にある。

    順序が入れ替わっていたら「表示は死ぬが書込は済んでいる」に変わり、
    reconfigure の必要性の理屈も変わる。前提が崩れたらこの test で気付く。
    """
    i_preview_loop = _SRC.index("for lb, iid in to_add:")
    i_real_write = _SRC.index("create_ads(tok, to_add)")
    assert i_preview_loop < i_real_write
