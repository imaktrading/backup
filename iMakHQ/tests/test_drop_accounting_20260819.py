# -*- coding: utf-8 -*-
"""落ちた分の件数が合うこと (2026-08-19 ユーザー指摘「件数が合わないよね」).

8/19 の走行: 処理20 = 出品12 + 落ち8 なのに、メールの内訳は 1+2+4 = 7 しか出せず、
監査は 8件中5件を「未分類(要調査)」と報告した。原因は2つとも **記録していない物を
推測で書いていた** こと:

  1. 生成後の間引き (同じカードがCSVに2枚 → 1枚に絞る) は走行ログが閉じた後に走るため、
     どこにも記録が残らず、メールにも監査にも1件も出なかった
  2. 目視の理由を「見送り − 該当なし = 未回答」と **引き算** で作っていた。実際には
     viewer に出せなかった1件 (PSAデータが取れず) が「未回答」と表示され、
     人が「自分が答え忘れた」と読む状態になっていた

→ 落ちたら必ず cert 単位で記録する。理由は引き算で作らない。
"""
from __future__ import annotations

import csv
import io
import os
import re
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import drop_classifier as dc                                          # noqa: E402
from post_psa_review import render_skip_reasons, viewer_skip_reasons  # noqa: E402


def _fn(*names):
    """control_panel は tkinter を import するので純関数だけ切り出す."""
    src = io.open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
    ns = {"os": os, "sys": sys, "csv": csv,
          "CSV_CERT_COL": "CDA:Certification Number - (ID: 27503)"}
    for n in names:
        i = src.index("def %s" % n)
        exec(src[i:src.index("\ndef ", i + 1)], ns)                   # noqa: S102
    return [ns[n] for n in names]


HEADER = ["*Title", "CustomLabel", "CDA:Certification Number - (ID: 27503)"]


def _row(title, label, cert):
    return [title, label, cert]


class TestPostDropsAreRecorded:
    """生成後に落ちた行は cert 付きで記録される (= メールと監査が同じ物を数える)."""

    def test_both_steps_are_recorded_with_cert_and_reason(self):
        _row_cert, drop_records, build_post_drops = _fn(
            "_row_cert", "drop_records", "build_post_drops")
        live = [_row("PSA 10 Ace", "m1", "111111")]
        intra = [_row("PSA 10 Arbok", "m2", "222222")]
        got = build_post_drops(HEADER, live, HEADER, intra)
        assert [d["cert"] for d in got] == ["111111", "222222"]
        assert [d["reason"] for d in got] == ["live-dup", "intra-dup"]
        assert got[1]["title"] == "PSA 10 Arbok", "何が落ちたか分かるように中身も残す"

    def test_nothing_removed_records_nothing(self):
        _row_cert, drop_records, build_post_drops = _fn(
            "_row_cert", "drop_records", "build_post_drops")
        assert build_post_drops(HEADER, [], HEADER, []) == []

    def test_the_two_dedupe_steps_are_diffed_separately(self):
        """★8/19 の実体: 17行 → live重複4 → 13行 → CSV内重複1 → 12行."""
        _row_label, livedup, _row_cert, drop_records, build_post_drops = _fn(
            "_row_label", "_livedup_removed_rows", "_row_cert", "drop_records",
            "build_post_drops")
        pre = [_row("t%d" % i, "m%d" % i, "%06d" % i) for i in range(17)]
        mid = [r for r in pre if r[1] not in ("m3", "m4", "m8", "m16")]
        post = [r for r in mid if r[1] != "m14"]
        drops = build_post_drops(HEADER, livedup(pre, HEADER, mid, HEADER),
                                 HEADER, livedup(mid, HEADER, post, HEADER))
        assert len(drops) == 5
        assert sum(d["reason"] == "intra-dup" for d in drops) == 1
        assert len(post) + len(drops) == len(pre)


class TestAuditReadsTheRecord:
    """監査(問題提起)は記録を読む = 生成後の落ちが「未分類(要調査)」に化けない."""

    def test_recorded_reason_wins_over_log_guessing(self):
        extra = dc.post_drop_reasons({"drops": [
            {"cert": "111111", "reason": "live-dup", "title": "x"},
            {"cert": "222222", "reason": "intra-dup", "title": "y"}]})
        assert dc.drop_reason("", "111111", extra)["class"] == "正常(既に出品中)"
        assert dc.drop_reason("", "222222", extra)["class"] == "正常(今回2枚)"

    def test_without_the_record_it_stays_unclassified(self):
        """記録が無ければ「未分類(要調査)」のまま = 黙って正常扱いにしない."""
        assert dc.drop_reason("", "111111")["class"] == "未分類(要調査)"

    def test_cannot_show_is_not_catalog_missing(self):
        """★viewer に出せなかった分を「該当なし(catalog欠)」にしない (依頼先を間違える)."""
        log = ("  ⚠️ cert 146333918: cache miss/category不明/対象外 → 目視対象外 (build skip)\n"
               "スキップ(目視未確定): #146333918")
        assert dc.drop_reason(log, "146333918")["class"].startswith("目視に出せず")

    def test_normal_classes_are_not_reported_as_action_items(self):
        rep = dc.render_problem_report([
            {"item": "#1", "class": "正常(既に出品中)", "cause": "c", "act": "a"}])
        assert "正常(既に出品中)1" in rep and "・[正常" not in rep


class TestViewerReasonIsRecordedNotSubtracted:
    """目視で進まなかった理由は引き算で作らない (8/19 の「未回答1件」は誤表示だった)."""

    CERTS = ["1", "2", "3", "4", "5"]
    RESULTS = [{"cert": "2", "choice": "NONE"}, {"cert": "3", "choice": "PENDING"}]

    def test_cannot_show_is_not_unanswered(self):
        got = dict(viewer_skip_reasons(self.CERTS, {"1": "p"}, self.RESULTS,
                                       fixes=(), unavailable=["5"]))
        assert got["目視に出せなかった (PSAデータ/カテゴリ不明)"] == ["5"]
        assert got["未回答"] == ["4"], "答える機会が無かった分を未回答に混ぜない"
        assert got["該当なし (カタログに依頼)"] == ["2"]
        assert got["保留 (次の走行でまた出ます)"] == ["3"]

    def test_confirmed_certs_are_not_listed(self):
        assert viewer_skip_reasons(["1"], {"1": "pid"}, []) == []

    def test_every_skipped_cert_gets_exactly_one_reason(self):
        """理由の付かない cert を1件も作らない (= 引き算の余りが出ない)."""
        pairs = viewer_skip_reasons(self.CERTS, {"1": "p"}, self.RESULTS,
                                    fixes=[("4", "9")], unavailable=["5"])
        listed = [c for _, cs in pairs for c in cs]
        assert sorted(listed) == ["2", "3", "4", "5"] and len(listed) == len(set(listed))

    def test_rendered_lines_are_machine_readable(self):
        lines = render_skip_reasons(viewer_skip_reasons(["9"], {}, []))
        assert lines[1] == "     ・未回答: 1件 [#9]"


class TestMailCountsAddUp:
    """メールの内訳 + 出品数 = 処理件数 (8/19 は 12+1+2+4 = 19 で1件行方不明だった)."""

    LOG = ("20件を処理します。（仕入値あり: 20件）\n"
           "  ⏭️ 目視で出品しなかった内訳 (引き算せず記録した理由):\n"
           "     ・該当なし (カタログに依頼): 2件 [#78976849, #168157629]\n"
           "     ・目視に出せなかった (PSAデータ/カテゴリ不明): 1件 [#146333918]\n")
    POST = {"drops": [{"cert": "1", "reason": "live-dup", "title": "(KEY=x) PSA 10 Ace"},
                      {"cert": "2", "reason": "live-dup", "title": "(KEY=y) PSA 10 Luffy"},
                      {"cert": "3", "reason": "live-dup", "title": "(KEY=z) PSA 10 Pikachu"},
                      {"cert": "4", "reason": "live-dup", "title": "(KEY=w) PSA 10 Mew"},
                      {"cert": "5", "reason": "intra-dup", "title": "(KEY=v) PSA 10 Arbok"}]}

    def _lines(self):
        (build_exclusion_lines,) = _fn("build_exclusion_lines")
        return build_exclusion_lines(self.LOG, {"removed": 4}, {"added": 14}, self.POST)

    def test_the_breakdown_plus_listed_equals_the_batch(self):
        got = self._lines()
        n = [int(re.search(r"(\d+)件", x).group(1)) for x in got if x.startswith("・")]
        assert sum(n) == 8, "落ち8件 + 出品12件 = 処理20件"
        assert got[0] == "(今回の 20件 の内訳)"

    def test_the_intra_csv_duplicate_shows_up(self):
        """★これが丸ごと欠けていた1件."""
        assert "同じカードが今回2枚 1件" in "\n".join(self._lines())

    def test_reasons_come_from_the_record_not_subtraction(self):
        got = "\n".join(self._lines())
        assert "目視に出せなかった 1件" in got
        assert "未回答" not in got, "答える機会が無かった分を『未回答』と書かない"

    def test_old_logs_without_the_record_still_work(self):
        """記録の無い古い走行ログでも従来どおり読める (黙って空にしない)."""
        (build_exclusion_lines,) = _fn("build_exclusion_lines")
        old = ("10件を処理します\n  📨 NONE/NG 2 件 → catalog 宿題化 (2 件記録)\n"
               "🔎 目視未確定で出品見送り: 3 件 ['a']")
        got = "\n".join(build_exclusion_lines(old, {"removed": 1}, {}))
        assert "「該当なし」 2件" in got and "目視で未回答 1件" in got
