"""PSA 補URL 能動充填 Phase1 slice2: 夜間検索の純関数テスト (2026-07-24)。

設計: discussion/2026-07-24_psa_hoju_url_replenishment_design.md。
検索プリミティブで対象を叩き psa_research_cache へ書込む slice2 の副作用なし部分:
  - _entry_complete / targets_needing_search: 当日 mercari+snkrdunk 揃いだけ再検索skip(レジューム耐性)
  - merge_search_result: fail-closed(errored メルカリはキャッシュに焼かない=次夜再取得)
純関数のみ (DB/network 非依存)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from psa_hoju_fill import (
    _entry_complete,
    _mercari_errored,
    merge_search_result,
    targets_needing_search,
)

TODAY = "2026-07-24"


def test_entry_complete_needs_both_keys_and_today():
    assert _entry_complete({"mercari": None, "snkrdunk": {}, "date": TODAY}, TODAY)
    # value=None(在庫なし確定)でもキー在れば完了
    assert not _entry_complete({"snkrdunk": {}, "date": TODAY}, TODAY)        # mercari 欠落
    assert not _entry_complete({"mercari": None, "snkrdunk": {}, "date": "2026-07-23"}, TODAY)  # 前日
    assert not _entry_complete(None, TODAY)


def test_mercari_errored():
    assert _mercari_errored({"_error": "timeout", "best": None})
    assert not _mercari_errored({"best": None})       # 在庫なし(確定)は errored でない
    assert not _mercari_errored(None)


def test_targets_needing_search_skips_completed_today():
    targets = [{"itemID": "A"}, {"itemID": "B"}, {"itemID": "C"}]
    cache = {
        "A": {"mercari": None, "snkrdunk": {"available": False}, "date": TODAY},   # 完了→skip
        "B": {"snkrdunk": {}, "date": TODAY},                                       # mercari欠落→残
    }
    need = targets_needing_search(targets, cache, TODAY)
    assert [t["itemID"] for t in need] == ["B", "C"]


def test_merge_search_result_fail_closed_drops_errored_mercari():
    cache = {}
    # errored メルカリ → mercari キーを付けない(= 次夜まだ未完了として再取得される)
    merge_search_result(cache, "A", {"_error": "timeout"}, {"available": False}, TODAY)
    assert "mercari" not in cache["A"] and cache["A"]["snkrdunk"] == {"available": False}
    assert not _entry_complete(cache["A"], TODAY)     # 未完了のまま(再検索対象)


def test_merge_search_result_success_completes_entry():
    cache = {}
    merge_search_result(cache, "A", {"best": (1000, "u", "n")}, {"available": True}, TODAY)
    assert cache["A"]["mercari"]["best"][0] == 1000
    assert _entry_complete(cache["A"], TODAY)


def test_merge_search_result_no_itemid_is_noop():
    cache = {"X": 1}
    assert merge_search_result(cache, "", {"best": None}, {}, TODAY) == {"X": 1}
