"""再仕入れ候補の先読み(共有キャッシュ温め)の回帰テスト (2026-07-28).

「🛒 PSA 再仕入れ ① 探す」は押してから探すので待たされる。psa_research_cache を共有しているので
夜に温めれば即答になる。壊れやすい点を固定する:
  1. targets を渡した時に HIGH(スプシ)を読みに行かない = 温め経路が Sheets 障害に巻き込まれない
  2. 先読みは書込をしない (スプシ/補URL列に触らない。判定は有人ゲートのまま)
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_hoju_fill as P  # noqa: E402


def test_run_night_search_accepts_targets():
    assert "targets" in inspect.signature(P.run_night_search).parameters


def test_high_is_read_only_when_targets_not_given():
    src = inspect.getsource(P.run_night_search)
    assert "if targets is None:" in src
    # _read_high() の呼び出しがその分岐の中にあること
    head = src[:src.index("cache = ")]
    assert head.count("_read_high()") == 1


def test_restock_prefetch_cli_is_search_only():
    """search-restock は書込系を呼ばない (confirm/補URL書込を混ぜたら有人確証が飛ぶ)。"""
    src = inspect.getsource(P.main)
    i = src.index('"search-restock"')
    block = src[i:src.index('if "confirm" in sys.argv:', i)]
    assert "run_night_search(targets=" in block
    for ng in ("run_daytime_confirm", "write_aux", "update_cell", "batch_update"):
        assert ng not in block


def test_restock_targets_skips_rows_without_item_id(monkeypatch):
    """itemID が取れない行は skip (キャッシュは itemID キーなので、混ぜると別カードを汚染する)。"""
    class _MP:
        @staticmethod
        def _ebay_item_id(url):
            return "358800000001" if "good" in url else ""

    class _Gate:
        @staticmethod
        def _load_restock_psa10():
            return ([{"ebay_url": "https://www.ebay.com/itm/good", "title": "t1"},
                     {"ebay_url": "", "title": "t2"}], _MP)

    monkeypatch.setitem(sys.modules, "psa_resource_gate", _Gate)
    hdr = [""] * 41
    row = [""] * 41
    row[P.B] = "358800000001"
    row[P.KEY] = "pokemon_tcg:SV5a-083"
    row[P.CERT] = "123456"
    monkeypatch.setattr(P, "_read_high", lambda: [hdr, row])

    got = P.restock_targets()
    assert len(got) == 1
    assert got[0]["itemID"] == "358800000001"
    assert got[0]["key"] == "pokemon_tcg:SV5a-083"
