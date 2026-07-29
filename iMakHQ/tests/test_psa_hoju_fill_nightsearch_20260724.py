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


# --- 確証スキップの cooldown (2026-07-29) ---------------------------------
# 設計は「cooldown付きで一定期間だけ再表示しない」だったが、実装が期限なしだったため
# 一度「違う」を押した出品は **永久に補URLが付かない** 状態だった (= 丸腰のまま放置)。
# 「違う」の主因の一つは *その日* 正変種が売られていないことなので、時間で解決する。

_H = ["itemID", "cert", "title", "理由", "日付"]


def _skip_rows(*rows):
    return [_H] + [list(r) for r in rows]


def test_skip_cooldown_is_next_day():
    """ユーザー判断 (2026-07-29): 翌日には再挑戦する。寝かせない。"""
    rows = _skip_rows(["358a", "1", "t", "違う", "2026-07-01"])
    assert _skip_iids_from_tab(rows, today="2026-07-01") == {"358a"}   # 同日 = 伏せる
    assert _skip_iids_from_tab(rows, today="2026-07-02") == set()      # 翌日 = 復帰
    rows2 = _skip_rows(["358b", "1", "t", "見送り", "2026-07-01"])
    assert _skip_iids_from_tab(rows2, today="2026-07-02") == set()     # 見送りも翌日


def test_skip_unparseable_date_stays_hidden():
    """日付が読めない行は skip 継続 (判定材料なしで再表示すると毎回同じものが出る)。"""
    rows = _skip_rows(["358a", "1", "t", "違う", ""], ["358b", "1", "t", "違う", "こわれ"])
    assert _skip_iids_from_tab(rows, today="2026-07-09") == {"358a", "358b"}


def test_skip_without_today_keeps_legacy_behavior():
    """today 省略 = 従来どおり全行対象 (呼出側が明示した時だけ cooldown が効く)。"""
    rows = _skip_rows(["358a", "1", "t", "違う", "2020-01-01"])
    assert _skip_iids_from_tab(rows) == {"358a"}


# --- 新供給が出た時だけ出す (cooldown を翌日に縮めてもノイズにしない) ------------
# 2026-06-22 に「同じ3件が毎回出る」と指摘された経緯があるため、期間短縮だけだと再発する。

def test_new_supply_detected_when_unseen_url_appears():
    from psa_hoju_fill import _has_new_supply
    seen = ["https://jp.mercari.com/item/m1"]
    assert _has_new_supply(seen, ["https://jp.mercari.com/item/m1",
                                  "https://jp.mercari.com/item/m2"]) is True


def test_no_new_supply_when_same_urls():
    """前回と同じ候補しか無い = 見せても同じ判断になる → 出さない。"""
    from psa_hoju_fill import _has_new_supply
    seen = ["https://jp.mercari.com/item/m1?utm=x", "https://jp.mercari.com/item/m2/"]
    assert _has_new_supply(seen, ["https://jp.mercari.com/item/m2",
                                  "https://JP.mercari.com/item/m1"]) is False


def test_no_new_supply_when_no_candidates():
    from psa_hoju_fill import _has_new_supply
    assert _has_new_supply(["https://jp.mercari.com/item/m1"], []) is False


def test_legacy_row_without_record_is_reshown():
    """旧形式(候補URL列なし)の行は記録が無い → 出す (取りこぼしより再表示を選ぶ)。"""
    from psa_hoju_fill import _has_new_supply
    assert _has_new_supply([], ["https://jp.mercari.com/item/m1"]) is True


def test_seen_urls_by_iid_parses_ledger():
    from psa_hoju_fill import _seen_urls_by_iid
    rows = [_H + ["その時の候補URL"],
            ["358a", "1", "t", "違う", "2026-07-29", "https://a | https://b"],
            ["358b", "1", "t", "見送り", "2026-07-29"]]        # 旧形式(5列)
    got = _seen_urls_by_iid(rows)
    assert got["358a"] == ["https://a", "https://b"]
    assert got["358b"] == []


# --- 候補単位の「違う」を負例として貯める (2026-07-29) ---------------------
# それまで、出品自体が確定した場合は候補の「違う」が警告1行で消えており、
# 次回また同じ別カードが候補に並んでいた (人の1クリックが捨てられていた)。

def test_rejected_candidate_is_not_shown_again():
    from psa_hoju_fill import filter_candidates_rejected
    cands = [{"url": "https://jp.mercari.com/item/m1"},
             {"url": "https://jp.mercari.com/item/m2"}]
    keep, drop = filter_candidates_rejected(cands, {"https://jp.mercari.com/item/m1"})
    assert [c["url"] for c in keep] == ["https://jp.mercari.com/item/m2"]
    assert len(drop) == 1


def test_rejected_filter_normalizes_urls():
    """クエリ/末尾スラッシュ/大小文字が違うだけの同一出品も除く。"""
    from psa_hoju_fill import filter_candidates_rejected
    cands = [{"url": "https://JP.mercari.com/item/m1/?utm_source=x"}]
    keep, drop = filter_candidates_rejected(cands, {"https://jp.mercari.com/item/m1"})
    assert keep == [] and len(drop) == 1


def test_ng_urls_by_iid_groups_per_listing():
    """NG は **出品ごと**。別の出品では同じURLが正解になりうるので混ぜない。"""
    from psa_hoju_fill import _ng_urls_by_iid
    rows = [["itemID", "cert", "url", "title", "日付"],
            ["358a", "1", "https://jp.mercari.com/item/m1", "t", "2026-07-29"],
            ["358a", "1", "https://jp.mercari.com/item/m2", "t", "2026-07-29"],
            ["358b", "2", "https://jp.mercari.com/item/m1", "t", "2026-07-29"]]
    got = _ng_urls_by_iid(rows)
    assert len(got["358a"]) == 2
    assert got["358b"] == {"https://jp.mercari.com/item/m1"}


def test_merge_ng_rows_dedups_by_item_and_url():
    from psa_hoju_fill import _merge_ng_rows, NG_CAND_HEADER
    existing = [NG_CAND_HEADER, ["358a", "1", "https://jp.mercari.com/item/m1", "t", "d1"]]
    new = [["358a", "1", "https://jp.mercari.com/item/m1/", "t", "d2"]]   # 同一(正規化後)
    merged = _merge_ng_rows(existing, new, NG_CAND_HEADER)
    assert len(merged) == 2 and merged[1][4] == "d2"          # 新規優先で1件のまま


def test_cache_candidate_urls_reads_all_cands():
    from psa_hoju_fill import _cache_candidate_urls
    e = {"mercari": {"best": None, "cands": [], "all_cands": [[100, "https://x", "n"]]}}
    assert _cache_candidate_urls(e) == ["https://x"]
    assert _cache_candidate_urls({}) == []
    assert _cache_candidate_urls({"mercari": None}) == []


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
