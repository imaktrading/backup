# -*- coding: utf-8 -*-
"""2026-08-23 「一時エラーで止まったのに完了と出た」の回帰テスト。

何が起きたか:
  9件を出品中、3件目で eBay が `System error. Unable to process your request.`
  を返した。内容の不備ではなく eBay 側の一時的な不調で、**同じ行をそのまま
  出し直したら通った** (ItemID 820035999681)。ところが
    ・`--keep-going` が無いのでそこで停止 → 残り7件が未出品
    ・締めの表示は「🎉 全 process 完了 — 入稿準備 OK」「🟢 入稿OK: 9件」
  で、成功したようにしか見えなかった。

守ること:
  ① eBay の一時的な不調は **同じ走行の中で** 出し直す (次の走行に送らない)
  ② 内容の不備は出し直さない (何度出しても同じ)
  ③ 出せずに残った行は結果に必ず残す
  ④ 出し残しがあるうちは締めを「完了」と書かない
"""
import os
import sys

import pytest

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (HQ, os.path.join(HQ, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ebay_upload_csv as U  # noqa: E402

_SYSERR = "System error. Unable to process your request. Please try again later."


# ── ① / ② どれを出し直すか ────────────────────────────────────────
@pytest.mark.parametrize("ack,err,want", [
    ("Failure", _SYSERR, True),
    ("Failure", "Internal error", True),
    ("Failure", "Service Unavailable", True),
    # 内容の不備は出し直さない
    ("Failure", "値が足りない: *Title", False),
    ("Failure", "Grade (27502) is a required field", False),
    # 成功は当然出し直さない
    ("Success", "", False),
    ("Warning", _SYSERR, False),
])
def test_is_transient(ack, err, want):
    assert U.is_transient(ack, err) is want


def test_retry_recovers_within_the_same_run():
    """1回目が一時エラー → 待って出し直し → 2回目で通る。"""
    calls, slept = [], []

    def _post(call, inner, tok, site=None):
        calls.append(call)
        if len(calls) == 1:
            return f"<Ack>Failure</Ack><LongMessage>{_SYSERR}</LongMessage>"
        return "<Ack>Success</Ack><ItemID>820035999681</ItemID>"

    ack, iid, _ = U.send_with_retry(_post, "AddFixedPriceItem", "<Item/>", "tok", "0",
                                    sleep_fn=slept.append, log=lambda *_: None)
    assert (ack, iid) == ("Success", "820035999681")
    assert len(calls) == 2, "出し直していない"
    assert slept, "間を空けずに叩き直している"


def test_retry_gives_up_and_does_not_loop_forever():
    n = []

    def _post(call, inner, tok, site=None):
        n.append(1)
        return f"<Ack>Failure</Ack><LongMessage>{_SYSERR}</LongMessage>"

    ack, _, _ = U.send_with_retry(_post, "AddFixedPriceItem", "<Item/>", "tok", "0",
                                  tries=3, sleep_fn=lambda *_: None, log=lambda *_: None)
    assert ack == "Failure"
    assert len(n) == 3


def test_no_retry_for_content_error():
    """内容の不備は1回だけ。無駄に叩かない。"""
    n = []

    def _post(call, inner, tok, site=None):
        n.append(1)
        return "<Ack>Failure</Ack><LongMessage>Grade (27502) is a required field</LongMessage>"

    U.send_with_retry(_post, "AddFixedPriceItem", "<Item/>", "tok", "0",
                      sleep_fn=lambda *_: None, log=lambda *_: None)
    assert len(n) == 1


# ── ③ 出せずに残った行を結果に残す ────────────────────────────────
def test_result_carries_unlisted_rows():
    r = U.build_result("x.csv", True, 2, 1, [("m1", "111"), ("m2", "222")],
                       [("m3", "Failure")], stopped_early=True,
                       unlisted=["m3", "m4", "m5"])
    assert r["unlisted"] == ["m3", "m4", "m5"]
    assert r["stopped_early"] is True


def test_result_unlisted_defaults_empty():
    r = U.build_result("x.csv", True, 1, 0, [("m1", "111")], [])
    assert r["unlisted"] == []


# ── ④ 締めの表示 ──────────────────────────────────────────────────
def test_summary_flags_unlisted():
    import control_panel as C
    assert C.unlisted_from_result({"write": True, "unlisted": ["m3", "m4"]}) == ["m3", "m4"]


def test_summary_quiet_when_all_listed():
    import control_panel as C
    assert C.unlisted_from_result({"write": True, "unlisted": []}) == []


def test_summary_ignores_verify_only_run():
    """検証のみの走行は出品していないので「未出品」ではない。"""
    import control_panel as C
    assert C.unlisted_from_result({"write": False, "unlisted": ["m1"]}) == []


def test_summary_ignores_stale_result_file():
    """前回の走行が残した結果を今回の分と読み違えない。"""
    import control_panel as C
    got = C.unlisted_from_result({"write": True, "unlisted": ["m1"]},
                                 started_ts=1000.0, file_mtime=999.0)
    assert got == []
    got2 = C.unlisted_from_result({"write": True, "unlisted": ["m1"]},
                                  started_ts=1000.0, file_mtime=1001.0)
    assert got2 == ["m1"]
