# -*- coding: utf-8 -*-
"""再仕入れ照合の先読みを夜のうちに全件やる (2026-09-03)。

## なぜ
「🛒 PSA 再仕入れ ① 探す」は押してから仕入れ先を探すので待たされる。夜間バッチは同じ
キャッシュを共有しているので、夜に温めておけば朝は待たずに出る。
ところが枠が 20件 固定で、実測 2026-09-03 の対象は **82件**。62件は結局その場で
探すことになり、待ち時間が残っていた。ユーザー指示「全件やれば」。

`--limit=0` を「全件」と読む。当日済 skip と空振り台帳が効くので、実際に叩く数は
対象数より少なくなる (夜間バッチはコツコツが原則なので、上限を外しても総当たりにはしない)。
"""
import os
import re

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def _cli_limit_of(src):
    """search-restock の CLI が --limit=0 を「全件(None)」に読むか (ソース検査)。"""
    return "limit = None if limit == 0 else limit" in src


def test_limit_zero_means_all():
    src = open(os.path.join(_TOOLS, "psa_hoju_fill.py"), encoding="utf-8").read()
    assert _cli_limit_of(src), "--limit=0 を全件として扱う分岐が無い"


def test_night_batch_asks_for_all():
    """夜間バッチが 20件 固定に戻っていないこと。"""
    bat = open(os.path.join(_TOOLS, "run_hoju_search.bat"), encoding="ascii",
               errors="replace").read()
    m = re.search(r"psa_hoju_fill\.py search-restock --limit=(\d+)", bat)
    assert m, "夜間バッチに search-restock の行が無い"
    assert m.group(1) == "0", f"先読みが {m.group(1)}件 に戻っている (0 = 全件)"


def test_bat_stays_ascii_only():
    """.bat は cmd の codepage で読まれる。日本語を入れると全部壊れる (2026-07-30 実害)。"""
    raw = open(os.path.join(_TOOLS, "run_hoju_search.bat"), "rb").read()
    assert all(b < 0x80 for b in raw), "run_hoju_search.bat に非ASCIIが混入している"
