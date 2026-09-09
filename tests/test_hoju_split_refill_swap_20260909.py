# -*- coding: utf-8 -*-
"""補URL③を「補充」と「入れ替え」に分ける (2026-09-09 ユーザー指示)。

    「補が少ない物の補充と / 補がほぼ満タンで最安の入れ替えと」
    「入れ替えは、毎日しなくても2日おきとかで貯まった中から最安を選ぶから効率が良くないかな？」

目的が別。混ざっていると **丸腰(補0本)の補充が、もう足りている出品の値下げに埋もれる**。
入れ替えは急がない。候補が薄いうちに選び直すと、翌日もっと安いものが来てまた入れ替えになる。

実測 (2026-09-09 / 出品中 PSA 471件):
    補0本 60 / 補1本 112 / 補2本 77 / 補3本 73 / 補4本 67 / 補5本 82
    → 補充 (補0〜3本) 312件 / 入れ替え (補4〜5本) 159件
"""
import os
import re
import sys

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools"))
sys.path.insert(0, _TOOLS)

import psa_hoju_fill as hf   # noqa: E402

PANEL = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ",
                                      "control_panel.py"))
N = 40


def _row(iid, aux):
    r = [""] * N
    r[hf.B], r[hf.CERT], r[hf.CATEGORY] = iid, "123456", "TCG"
    r[hf.KEY] = "one_piece_tcg:OP01-001"
    for i in range(aux):
        r[hf.AUX0 + i] = f"https://x/{iid}/{i}"
    return r


VALS = [["h"] * N] + [_row(str(100 + n), n) for n in range(6)]   # 補0〜5本を1件ずつ


def _ids(**kw):
    return sorted(t["itemID"] for t in hf.select_backfill_targets(VALS, **kw))


def test_refill_takes_the_thin_ones():
    """補充 = 補0〜3本。"""
    assert _ids(max_backups=4) == ["100", "101", "102", "103"]


def test_swap_takes_the_full_ones():
    """入れ替え = 補4〜5本。補充と **重ならない**。"""
    assert _ids(min_backups=4, max_backups=6) == ["104", "105"]


def test_the_two_buckets_cover_everything_once():
    """全部どちらかに入り、二重に出ない (どちらにも出ないと放置される)。"""
    refill = set(_ids(max_backups=4))
    swap = set(_ids(min_backups=4, max_backups=6))
    assert refill & swap == set()
    assert refill | swap == {str(100 + n) for n in range(6)}


def test_default_is_unchanged():
    """既定 (下限なし) は従来どおり = 他の呼び出しに影響しない。"""
    assert _ids(max_backups=1) == ["100"]


def test_panel_has_both_buttons():
    s = open(PANEL, encoding="utf-8").read()
    assert "PSA 補URL ③ 補充" in s and "PSA 補URL ③ 入れ替え" in s
    assert '"--max-backups=4", "--limit=15"' in s          # 補充
    assert '"--min-backups=4", "--max-backups=6"' in s      # 入れ替え


def test_panel_shows_a_count_for_the_swap_button():
    """件数が出ないボタンは押し時が分からない。0件の時も理由を出す。"""
    s = open(PANEL, encoding="utf-8").read()
    assert '"hoju_swap": sw_txt' in s
    assert "2日おきに押せば候補が貯まっています" in s


def test_confirm_cli_accepts_the_lower_bound():
    s = open(os.path.join(_TOOLS, "psa_hoju_fill.py"), encoding="utf-8").read()
    assert '--min-backups=' in s
    assert re.search(r"run_daytime_confirm\([^)]*min_backups", s)
