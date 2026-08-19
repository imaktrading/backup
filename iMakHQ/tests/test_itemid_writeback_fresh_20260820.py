# -*- coding: utf-8 -*-
"""出品した直後の itemID を、取り直さずに書き戻す (2026-08-19 の走行停止の根本).

何が起きたか:
    18:20 に12件出品 → 直後の書き戻しが **1件も書かなかった** → B列が空のまま。
    19:16 の抽出は「B列が空 = まだ出していない」と判断して同じ行をもう一度候補に入れ、
    20:04 に二重出品しようとして eBay に弾かれ、そこで走行が停止した
    (20件処理して新規5件。残り1件は試行すらされず)。

なぜ書けなかったか:
    書き戻しが見る live 一覧は **2時間キャッシュ**(API 上限を使い切らないための仕組み)。
    出品した直後に走らせても、たった今出した分が入っていない。

直し方:
    itemID は出品の応答 (`last_upload_result.json`) に **既に入っている**。
    取り直さず、それを live 一覧に足してから突合する (API 消費ゼロ・冪等)。
"""
from __future__ import annotations

import json
import os
import sys
import time

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import itemid_writeback_audit as w                              # noqa: E402

CERT_COL = "CDA:Certification Number - (ID: 27503)"
RESULT = {"csv": "tcg_upload.csv", "ok": 2, "listed": [
    {"label": "m58189632398", "item_id": "820021818681"},
    {"label": "m72537356433", "item_id": "820021818516"}]}
ROWS = [{"CustomLabel": "m58189632398", CERT_COL: "167781053", "*Title": "PSA 10 One Piece Luffy"},
        {"CustomLabel": "m72537356433", CERT_COL: "156326694", "*Title": "PSA 10 Pokemon Psyduck"}]


class TestFreshListingsAreUsable:
    def test_response_becomes_a_live_shaped_record(self):
        got = w.just_listed_live(RESULT, ROWS)
        assert set(got) == {"820021818681", "820021818516"}
        assert got["820021818681"] == {
            "avail": 1, "cur": "USD", "sku": "PSA10-167781053",
            "title": "PSA 10 One Piece Luffy"}

    def test_the_index_finds_them_by_cert(self):
        """★これが空だったので、B列に何も書かれなかった."""
        by_cert, _ = w.build_live_index(w.just_listed_live(RESULT, ROWS))
        assert by_cert == {"167781053": "820021818681", "156326694": "820021818516"}

    def test_supply_id_is_used_when_there_is_no_cert(self):
        rows = [{"CustomLabel": "m58189632398", CERT_COL: "", "*Title": "t"}]
        _, by_supply = w.build_live_index(w.just_listed_live(RESULT, rows))
        assert by_supply["m58189632398"] == "820021818681"

    def test_the_sheet_row_gets_filled(self):
        """B列が空の行が、応答由来の索引だけで埋まること (= 走行停止の根本)."""
        by_cert, by_supply = w.build_live_index(w.just_listed_live(RESULT, ROWS))
        sheet = [["url", "itemID"] + [""] * 20,
                 ["https://jp.mercari.com/item/m58189632398", ""] + [""] * 6
                 + ["167781053"] + [""] * 9 + ["TCG"]]
        miss = w.find_missing(sheet, by_cert, by_supply, "HIGH")
        assert [(m["row"], m["item_id"]) for m in miss] == [(2, "820021818681")]

    def test_rows_that_already_have_an_itemid_are_left_alone(self):
        by_cert, by_supply = w.build_live_index(w.just_listed_live(RESULT, ROWS))
        sheet = [["url", "itemID"] + [""] * 20,
                 ["https://jp.mercari.com/item/m58189632398", "820021818681"] + [""] * 6
                 + ["167781053"] + [""] * 9 + ["TCG"]]
        assert w.find_missing(sheet, by_cert, by_supply, "HIGH") == []


class TestNeverInvents:
    def test_nothing_listed_gives_nothing(self):
        assert w.just_listed_live({"listed": []}, ROWS) == {}
        assert w.just_listed_live({}, []) == {}

    def test_rows_without_an_item_id_are_skipped(self):
        got = w.just_listed_live({"listed": [{"label": "m1", "item_id": ""}]}, [])
        assert got == {}

    def test_a_stale_result_file_is_ignored(self, tmp_path):
        """古い結果は使わない (取り下げ済みを『販売中』として復活させない)."""
        f = tmp_path / "last_upload_result.json"
        f.write_text(json.dumps(RESULT), encoding="utf-8")
        old = time.time() - 48 * 3600
        os.utime(f, (old, old))
        assert w._load_just_listed(tmp_path) == {}

    def test_a_fresh_result_file_is_used(self, tmp_path):
        import csv
        (tmp_path / "last_upload_result.json").write_text(
            json.dumps(RESULT), encoding="utf-8")
        with (tmp_path / "tcg_upload.csv").open("w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=["CustomLabel", CERT_COL, "*Title"])
            wr.writeheader()
            wr.writerows(ROWS)
        got = w._load_just_listed(tmp_path)
        assert set(got) == {"820021818681", "820021818516"}

    def test_missing_files_are_not_an_error(self, tmp_path):
        assert w._load_just_listed(tmp_path) == {}
