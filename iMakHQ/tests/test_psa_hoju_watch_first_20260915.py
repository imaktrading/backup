# -*- coding: utf-8 -*-
"""補URL③: 同じ補の本数ならウォッチの多い出品を先に出す (2026-09-15)。

ユーザー「watchが多いのは、PSA補URL③でより安い仕入値を見つけたら売れそうだね」→「うん、そうしよう」。
実測 (9/15 ファネル・在庫あり US): 落とす候補の PSA 177件のうちウォッチ3以上が16件。
並び順は 補が少ない順 (丸腰が死ぬ) → ウォッチ多い順 → 新規出品順。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import psa_hoju_fill as H  # noqa: E402


def _row(iid, aux=0, listed="2026-09-01"):
    r = [""] * 41
    r[H.B] = iid
    r[H.CERT] = "123456"
    r[H.CATEGORY] = "TCG"
    r[H.KEY] = "pokemon_tcg:X-001"
    r[H.LISTED_AT] = listed
    r[2] = f"title {iid}"
    for k in range(aux):
        r[H.AUX0 + k] = f"https://example.com/{iid}/{k}"
    return r


def _vals(rows):
    return [[""] * 41] + rows


def test_more_watchers_first_within_same_backup_count():
    vals = _vals([
        _row("111", aux=1, listed="2026-09-10"),
        _row("222", aux=1, listed="2026-08-01"),
        _row("333", aux=0, listed="2026-07-01"),
    ])
    ids = [t["itemID"] for t in H.select_backfill_targets(vals, max_backups=5,
                                                          watch={"222": 50, "111": 2})]
    assert ids == ["333", "222", "111"], ids           # 丸腰が先、その次にウォッチ50


def test_same_watch_keeps_newest_first():
    vals = _vals([_row("111", listed="2026-08-01"), _row("222", listed="2026-09-01")])
    ids = [t["itemID"] for t in H.select_backfill_targets(vals, max_backups=5, watch={"111": 3, "222": 3})]
    assert ids == ["222", "111"], ids


def test_no_watch_data_keeps_old_order():
    vals = _vals([_row("111", listed="2026-08-01"), _row("222", listed="2026-09-01")])
    assert [t["itemID"] for t in H.select_backfill_targets(vals, max_backups=5)] == ["222", "111"]
    assert [t["itemID"] for t in H.select_backfill_targets(vals, max_backups=5, watch={})] == ["222", "111"]


def test_watch_from_funnel_rows():
    rows = [{"item_id": "358712610416", "watch": "50"}, {"item_id": "1", "watch": "0"},
            {"item_id": "x", "watch": "3"}, {"item_id": "2", "watch": "?"}]
    assert H.watch_by_item_from_rows(rows) == {"358712610416": 50}


def test_night_search_and_confirm_pass_watch():
    src = open(H.__file__, encoding="utf-8").read()
    assert src.count("watch=load_watch_by_item()") == 2


def test_swap_screen_orders_by_watch_not_backup_count():
    """入れ替え (補4〜5本) は本数で並べない。補5本でもウォッチが多ければ先。"""
    vals = _vals([_row("444", aux=4), _row("555", aux=5)])
    ids = [t["itemID"] for t in H.select_backfill_targets(vals, max_backups=6, min_backups=4,
                                                          watch={"555": 10, "444": 2})]
    assert ids == ["555", "444"], ids
