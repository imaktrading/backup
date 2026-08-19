# -*- coding: utf-8 -*-
"""入稿の段で落ちた分もメールの内訳に入れる + 売り切れチェックの記録 (2026-08-19).

8/19 20:04 の走行: 20件処理 → 出品5 / 該当なし5 / 既に出品中8 = 18 にしかならなかった。
足りない2件は **入稿の段** で落ちていた:
    ・eBay に弾かれた 1件 (同じカードが既に出品中)
    ・その失敗で停止し、試行すらしなかった 1件
生成側の内訳しか見ていなかったので、どちらも表に出ていなかった。

同じ走行で、仕入元の在庫チェックが 180秒で kill されて **まるごと走っていなかった**
(内側の在庫チェックCLI は自前で 900秒 待つ)。売り切れた物を出品すると仕入れられず
キャンセル = Defect Rate なので、走らなかったこと自体を黙ってはいけない。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fn(*names):
    """control_panel は tkinter を import するので純関数だけ切り出す."""
    src = io.open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    ns = {"os": os, "sys": sys, "csv": csv,
          "CSV_CERT_COL": "CDA:Certification Number - (ID: 27503)"}
    for n in names:
        i = src.index("def %s" % n)
        exec(src[i:src.index("\ndef ", i + 1)], ns)             # noqa: S102
    return [ns[n] for n in names]


LOG = ("20件を処理します。（仕入値あり: 20件）\n"
       "  ⏭️ 目視で出品しなかった内訳 (引き算せず記録した理由):\n"
       "     ・該当なし (カタログに依頼): 5件 [#1, #2, #3, #4, #5]\n")
POST = {"drops": [{"cert": str(i), "reason": "live-dup", "title": "t%d" % i}
                  for i in range(8)]}
UPLOAD = {"rows": 7, "listed": 5, "failed": 1}


def _lines(post=POST, upload=UPLOAD):
    (build_exclusion_lines,) = _fn("build_exclusion_lines")
    return build_exclusion_lines(LOG, {"removed": 8}, {"added": 8}, post, upload)


def _batch_numbers(lines):
    i = lines.index("(枠に入る前に候補から外した分 — 上の内訳とは別勘定)") if \
        "(枠に入る前に候補から外した分 — 上の内訳とは別勘定)" in lines else len(lines)
    return [int(re.search(r"(\d+)件", x).group(1))
            for x in lines[:i] if x.startswith("・") and "件" in x]


class TestUploadFailuresAreCounted:
    """★これが無くて 20件が 18件にしかならなかった."""

    def test_rejected_by_ebay_is_listed(self):
        assert any("eBayに弾かれた 1件" in x for x in _lines())

    def test_rows_never_attempted_are_listed(self):
        assert any("途中で止まって出せなかった 1件" in x for x in _lines())

    def test_the_whole_batch_adds_up(self):
        """内訳 + 出品 = 処理件数 (5+8+1+1 + 出品5 = 20)."""
        assert sum(_batch_numbers(_lines())) + UPLOAD["listed"] == 20

    def test_a_clean_upload_adds_no_extra_lines(self):
        got = _lines(upload={"rows": 5, "listed": 5, "failed": 0})
        assert not any("弾かれた" in x or "途中で止まって" in x for x in got)

    def test_no_upload_info_is_not_guessed(self):
        got = _lines(upload=None)
        assert not any("弾かれた" in x or "途中で止まって" in x for x in got)

    def test_no_post_record_at_all_still_works(self):
        """記録が1つも無い走行 (post_drops=None) でも落ちない."""
        assert _lines(post=None, upload=None)


class TestSoldOutRowsAreCounted:
    def test_sold_out_drops_get_their_own_line(self):
        post = {"drops": POST["drops"] + [
            {"cert": "9", "reason": "sold-out", "title": "t9"}]}
        assert any("仕入元が売り切れ 1件" in x for x in _lines(post))

    def test_the_batch_still_adds_up_with_sold_out(self):
        post = {"drops": POST["drops"] + [
            {"cert": "9", "reason": "sold-out", "title": "t9"}]}
        # 売り切れで1行減るので入稿は6行 (出品5 + 失敗1 / 未実行0)
        got = _lines(post, {"rows": 6, "listed": 5, "failed": 1})
        assert sum(_batch_numbers(got)) + 5 == 20


class TestSkippedStockCheckIsNotSilent:
    """走らなかったことを黙ると、売り切れた物が入稿CSVに残る (キャンセル→BAN)."""

    def test_failure_is_reported(self):
        got = _lines({"drops": [], "soldcheck": "TimeoutExpired"})
        assert any("在庫チェックが走っていません" in x and "TimeoutExpired" in x
                   for x in got)

    def test_success_says_nothing(self):
        got = _lines({"drops": [], "soldcheck": "ok"})
        assert not any("在庫チェック" in x for x in got)


class TestRecordIsAppendedNotOverwritten:
    """工程ごとに呼ばれるので、前の工程の記録を消さない."""

    def test_second_call_keeps_the_first(self, tmp_path):
        write, drop_records, _row_cert = _fn(
            "_write_post_drops", "drop_records", "_row_cert")
        csv_path = str(tmp_path / "x.csv")
        header = ["*Title", "CustomLabel", "CDA:Certification Number - (ID: 27503)"]
        write(lambda *_: None, csv_path,
              drop_records(header, [["t1", "m1", "111"]], "live-dup"))
        write(lambda *_: None, csv_path,
              drop_records(header, [["t2", "m2", "222"]], "sold-out"),
              soldcheck="ok")
        rec = json.loads(io.open(csv_path + ".excluded.json", encoding="utf-8").read())
        assert [d["reason"] for d in rec["drops"]] == ["live-dup", "sold-out"]
        assert rec["soldcheck"] == "ok"

    def test_drop_records_carries_cert_and_title(self):
        drop_records, _row_cert = _fn("drop_records", "_row_cert")
        header = ["*Title", "CustomLabel", "CDA:Certification Number - (ID: 27503)"]
        got = drop_records(header, [["PSA 10 Ace", "m1", "111"]], "sold-out")
        assert got == [{"cert": "111", "title": "PSA 10 Ace", "reason": "sold-out"}]
