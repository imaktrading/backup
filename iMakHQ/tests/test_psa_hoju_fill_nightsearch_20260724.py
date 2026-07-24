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
    _card_no_from_key,
    _entry_complete,
    _entry_fresh,
    _mercari_errored,
    _merge_skip_rows,
    _skip_iids_from_tab,
    backfill_status,
    compute_backurl_additions,
    merge_search_result,
    select_backfill_targets,
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


def test_card_no_from_key_derives_number_when_title_lacks_it():
    # Pokemon 等 title に番号が出ない → KEY(SV8a-093/M2a-198)から番号を取る(gate 規約と同一)
    assert _card_no_from_key("SV8a-093") == "SV8A-093"
    assert _card_no_from_key("EB04-001_p1") == "EB04-001"      # 変種suffix除去
    assert _card_no_from_key("SV-P-241") == "SV-P-241"
    # fail-closed: url-key / 数字なし / 空 は "" (探索不能=cache汚染しない)
    assert _card_no_from_key("item:m12345") == ""
    assert _card_no_from_key("shops:abc") == ""
    assert _card_no_from_key("") == ""
    assert _card_no_from_key(None) == ""


# --- slice3: 昼確認→補URL冪等書込 の純関数 -------------------------------------

def test_compute_backurl_additions_appends_to_empty_slots():
    # 既存2本 + 新規2本(1本は既存重複) → 空き枠に未収載1本だけ足す
    existing = ["https://a", "https://b"]
    full, added = compute_backurl_additions(existing, ["https://b", "https://c"], max_slots=5)
    assert full == ["https://a", "https://b", "https://c"] and added == ["https://c"]


def test_compute_backurl_additions_caps_at_max_slots():
    existing = ["u1", "u2", "u3", "u4"]
    full, added = compute_backurl_additions(existing, ["u5", "u6"], max_slots=5)
    assert full == ["u1", "u2", "u3", "u4", "u5"] and added == ["u5"]   # 満杯で u6 は溢れ=書かない


def test_compute_backurl_additions_ignores_empty_and_dupes():
    full, added = compute_backurl_additions([], ["", "x", "x", "  "], max_slots=5)
    assert full == ["x"] and added == ["x"]


def test_compute_backurl_additions_no_new_returns_empty_added():
    full, added = compute_backurl_additions(["a"], ["a"], max_slots=5)
    assert added == []            # 追加ゼロ=書込不要のシグナル


def test_skip_iids_from_tab():
    rows = [["itemID", "cert"], ["358a", "1"], ["", "2"], ["358b", "3"]]
    assert _skip_iids_from_tab(rows) == {"358a", "358b"}
    assert _skip_iids_from_tab([]) == set()
    assert _skip_iids_from_tab([["itemID"]]) == set()


def test_merge_skip_rows_new_wins_on_dupe_itemid():
    existing = [["itemID", "cert", "title", "理由", "日付"], ["358a", "1", "t", "見送り", "d1"]]
    new = [["358a", "1", "t", "違う", "d2"]]     # 同itemID → 新規優先
    merged = _merge_skip_rows(existing, new, existing[0])
    assert merged == [["itemID", "cert", "title", "理由", "日付"], ["358a", "1", "t", "違う", "d2"]]


def test_entry_fresh_accepts_recent_window_for_daytime():
    e = {"mercari": None, "snkrdunk": {}, "date": "2026-07-22"}
    assert _entry_fresh(e, "2026-07-24", max_age_days=3)         # 2日前=窓内(夜検索→翌朝確認)
    assert not _entry_fresh(e, "2026-07-27", max_age_days=3)     # 5日前=窓超過
    assert not _entry_fresh({"mercari": None, "date": "2026-07-24"}, "2026-07-24")  # snkrdunk欠落
    assert not _entry_fresh({"mercari": None, "snkrdunk": {}, "date": "2026-07-25"}, "2026-07-24")  # 未来日付
    assert not _entry_fresh(None, "2026-07-24")


# --- slice4(HQ側): 件数感セグメント -------------------------------------------

def test_backfill_status_segments_by_backup_count():
    # HIGH schema と同じ _row ヘルパで補本数別に作る
    rows = [_H_hdr(),
            _row_bk(itemid="a", cert="1", backups=0),
            _row_bk(itemid="b", cert="2", backups=0),
            _row_bk(itemid="c", cert="3", backups=2),
            _row_bk(itemid="d", cert="4", backups=5)]
    st = backfill_status(rows)
    assert st["live_psa"] == 4 and st["b0"] == 2 and st["b1_4"] == 1 and st["full"] == 1
    assert st["by_count"][0] == 2 and st["by_count"][2] == 1 and st["by_count"][5] == 1


# backfill_status 用の行ヘルパ(targets test の _row と同形)
from psa_hoju_fill import AUX0 as _AUX0


def _H_hdr():
    return ["URL", "itemID", "タイトル", "売り切れ"] + [""] * 4 + ["Title"] + [""] * 8 + ["カテゴリ"] + [""] * 40


def _row_bk(itemid="", cert="", cat="TCG", sold="", key="K1", backups=0):
    r = [""] * 41
    r[1], r[3], r[8], r[17], r[34], r[2] = itemid, sold, cert, cat, key, "t"
    for k in range(backups):
        r[_AUX0 + k] = f"https://sup/{k}"
    return r
