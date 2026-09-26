"""出品中の行の仕入元・補URL を集める (抽出段と入稿直前で同じ基準) (2026-09-26)。

m60630556837 (820161951633 の補URL) が 9/24〜9/26 に毎回枠を使ってから入稿直前で落ちていた。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import dup_guard as D  # noqa: E402


def _row(a="", b="", d="", aux=()):
    r = [""] * 40
    r[D.A], r[D.B], r[D.D] = a, b, d
    for k, u in enumerate(aux):
        r[D.AUX0 + k] = u
    return r


def test_aux_url_of_live_row_is_taken():
    rows = [["h"] * 40,
            _row("https://jp.mercari.com/item/m1", "820161951633",
                 aux=["https://jp.mercari.com/item/m60630556837"]),
            _row("https://jp.mercari.com/item/m60630556837")]          # 候補 (未出品)
    t = D.live_supply_urls(rows)
    assert D.norm_url("https://jp.mercari.com/item/m60630556837") in t
    assert t[D.norm_url("https://jp.mercari.com/item/m60630556837")] == {"820161951633"}


def test_unlisted_rows_do_not_claim_urls():
    rows = [["h"] * 40, _row("https://jp.mercari.com/item/m2")]
    assert D.live_supply_urls(rows) == {}
