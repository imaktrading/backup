# -*- coding: utf-8 -*-
"""3つの追加サイレント落ち穴を可視化 (2026-08-31 横展開)。

ユーザー「こういうのちょいちょいあるねんけど、どうなってるの？」への回答で洗った、
cert152976751 と同じ形 (ガード/検査が発動するが、記録した内容を誰も読まない) の穴。

1. dup_guard.py の pre_upload_stripped* → 何度も同じ物が弾かれ続けているかを見る
2. listing_common.py の HOLDキュー → 監査くんは件数しか出さず、中身は非表示だった
   (副産物: test_listing_rules.py が本物の HOLDキューを pytest のたびに汚染していた)
3. auto_catalog_add_request.py の入口検査ログ → 書く側はあったが読む側が無かった
"""
import io
import json
import os
import sys

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import status_now as SN  # noqa: E402

NL = chr(10)


# ── ① dup_guard.py: 慢性的な pre_upload_stripped ────────────────────
def _write_ledger(tmp_path, recs):
    p = tmp_path / "dup_guard_ledger.jsonl"
    p.write_text(NL.join(json.dumps(r, ensure_ascii=False) for r in recs) + NL, encoding="utf-8")
    return str(p)


def test_single_strip_is_not_flagged_as_chronic(tmp_path, monkeypatch):
    """1回だけの発動は正常動作。毎回全部出すとノイズで慢性化した1件が埋もれる。"""
    recs = [{"ts": "2026-08-01T00:00:00", "kind": "pre_upload_stripped",
             "same_cert": [{"label": "a", "cert": "999", "title": "t"}]}]
    monkeypatch.setattr(SN, "DUP_GUARD_LEDGER", _write_ledger(tmp_path, recs))
    assert SN._chronic_dup_guard_strips() == []


def test_repeated_strip_of_same_cert_is_flagged(tmp_path, monkeypatch):
    recs = [
        {"ts": "2026-08-01T00:00:00", "kind": "pre_upload_stripped",
         "same_cert": [{"label": "a", "cert": "999", "title": "t"}]},
        {"ts": "2026-08-02T00:00:00", "kind": "pre_upload_stripped",
         "same_cert": [{"label": "a", "cert": "999", "title": "t"}]},
    ]
    monkeypatch.setattr(SN, "DUP_GUARD_LEDGER", _write_ledger(tmp_path, recs))
    got = SN._chronic_dup_guard_strips()
    assert any("999" in ln for ln in got)


def test_three_strip_kinds_are_all_read(tmp_path, monkeypatch):
    recs = [
        {"ts": "t1", "kind": "pre_upload_stripped_shared_url",
         "taken": [{"label": "a", "cert": "111", "url": "u", "owner": "o"}]},
        {"ts": "t2", "kind": "pre_upload_stripped_shared_url",
         "taken": [{"label": "a", "cert": "111", "url": "u", "owner": "o"}]},
        {"ts": "t3", "kind": "pre_upload_stripped_samekey",
         "dups": [{"label": "L1", "cert": "222", "card_key": "k", "existing": "e"}]},
        {"ts": "t4", "kind": "pre_upload_stripped_samekey",
         "dups": [{"label": "L1", "cert": "222", "card_key": "k", "existing": "e"}]},
    ]
    monkeypatch.setattr(SN, "DUP_GUARD_LEDGER", _write_ledger(tmp_path, recs))
    got = " ".join(SN._chronic_dup_guard_strips())
    assert "111" in got and "L1" in got


def test_missing_ledger_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(SN, "DUP_GUARD_LEDGER", str(tmp_path / "no_such_file.jsonl"))
    assert SN._chronic_dup_guard_strips() == []


# ── ② listing_common.py: HOLDキューの中身を出す ────────────────────
def test_hold_queue_shows_real_detail_not_just_count(tmp_path, monkeypatch):
    p = tmp_path / "csv_hold_queue.jsonl"
    rec = {"ts": "2026-08-01T00:00:00", "category": "gshock", "sku": "m1",
           "title": "some title", "violations": [{"field": "*StartPrice",
           "issue": "Price too high", "severity": "error"}]}
    p.write_text(json.dumps(rec, ensure_ascii=False) + NL, encoding="utf-8")
    monkeypatch.setattr(SN, "CSV_HOLD_QUEUE", str(p))
    got = " ".join(SN._csv_hold_queue())
    assert "m1" in got and "Price too high" in got


def test_hold_queue_filters_out_the_test_fixture_sku(tmp_path, monkeypatch):
    """test_listing_rules.py が書き込む固定SKUは本物のHOLDと混ぜて数えない。"""
    p = tmp_path / "csv_hold_queue.jsonl"
    recs = [
        {"ts": "t1", "sku": "GATE-BLOCK-TEST", "title": "t", "violations": []},
        {"ts": "t2", "sku": "TEST_FAIL", "title": "t", "violations": []},
        {"ts": "t3", "sku": "real_sku_1", "title": "t", "violations": []},
    ]
    p.write_text(NL.join(json.dumps(r, ensure_ascii=False) for r in recs) + NL, encoding="utf-8")
    monkeypatch.setattr(SN, "CSV_HOLD_QUEUE", str(p))
    got = SN._csv_hold_queue()
    assert "計 1件" in got[0]
    assert any("real_sku_1" in ln for ln in got)


def test_test_file_no_longer_writes_to_the_real_hold_queue():
    """iMakeBayAPI/listing_common.py._HOLD_QUEUE_PATH を tmp に退避しているか (source確認)。"""
    _tests_root = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(_tests_root, "test_listing_rules.py"), encoding="utf-8").read()
    i = src.index("def _check_gate_blocks_alert")
    body = src[i:i + 2200]
    assert "_listing_common._HOLD_QUEUE_PATH = os.path.join(" in body
    assert "_listing_common._HOLD_QUEUE_PATH = _orig_path" in body


# ── ③ auto_catalog_add_request.py: 入口検査ログを読む ───────────────
def test_rejected_missing_models_reads_tab_separated_lines(tmp_path, monkeypatch):
    p = tmp_path / "missing_models_rejected.log"
    line = "\t".join(["2026-08-01 09:00:00", "pokemon_tcg", "カテゴリ空", "model-x"])
    p.write_text(line + "\n", encoding="utf-8")
    monkeypatch.setattr(SN, "REJECTED_MISSING_MODELS_LOG", str(p))
    got = " ".join(SN._rejected_missing_models())
    assert "model-x" in got and "カテゴリ空" in got


def test_rejected_missing_models_missing_file_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(SN, "REJECTED_MISSING_MODELS_LOG", str(tmp_path / "none.log"))
    assert SN._rejected_missing_models() == []


# ── 画面配線: 現在地に出ているか ─────────────────────────────────
def test_all_three_are_wired_into_the_report():
    src = open(os.path.join(_TOOLS, "status_now.py"), encoding="utf-8").read()
    for fn in ("_chronic_dup_guard_strips()", "_csv_hold_queue()", "_rejected_missing_models()"):
        assert fn in src, f"{fn} が report に配線されていない"
