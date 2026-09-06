# -*- coding: utf-8 -*-
"""タイトルから抽出した番号にも catalog 再チェックをかける (2026-09-05)。

`127/193 PSA10 レックウザ ボールミラー m2a` は M2a-127 として catalog に在ったのに、
再チェックが打鍵番号 (typed) の時だけで、抽出番号 (it["card_no"]) には効いていなかった。
分母つき/大小不一致のままでは当たらない。

依頼書: hq/requests/2026-09-05_act_code_proposals_tcg.md 提案4
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import newcand_confirm as N  # noqa: E402


def test_pokemon_printno_drops_denominator_and_finds_set_hint():
    cands = N.extraction_recheck_candidates(
        "127/193", "127/193 PSA10 レックウザ ボールミラー m2a")
    assert "127/193" in cands
    assert "127" in cands
    assert "M2a-127" in cands


def test_psa10_noise_word_is_not_used_as_set_hint():
    cands = N.extraction_recheck_candidates("127/193", "127/193 PSA10 レックウザ")
    assert not any(c.lower().startswith("psa10") for c in cands)


def test_hyphenated_id_case_is_normalized():
    cands = N.extraction_recheck_candidates("op05-002", "PSA10 ベロベティ op05-002")
    assert "OP05-002" in cands


def test_already_canonical_id_is_unchanged():
    cands = N.extraction_recheck_candidates("OP05-002", "PSA10 ベロベティ OP05-002")
    assert cands == ["OP05-002"]


def test_empty_card_no_returns_nothing():
    assert N.extraction_recheck_candidates("", "no number here") == []


def _item(idx, title, card_no):
    return {"idx": idx, "url": f"https://m/{idx}", "src": "補URL候補NG", "src_itemid": "358_1",
            "src_cert": "111", "price": 9000, "title": title, "card_no": card_no,
            "variants": []}


def test_save_skips_catalog_add_when_extracted_number_resolves_after_normalization(monkeypatch):
    sent = {}
    monkeypatch.setattr(N, "_append_tab", lambda *a: None)
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N, "live_key_set", lambda: set())
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab: [])
    monkeypatch.setattr(N.sheet_io, "write_rows_to_tab", lambda tab, rows: None)
    monkeypatch.setattr(N, "append_missing_models",
                        lambda rows, path=None: sent.setdefault("rows", rows) or len(rows))
    monkeypatch.setattr(N, "catalog_variants",
                        lambda no, db=None: ([{"pid": "M2a-127"}] if no == "M2a-127" else []))
    items = [_item(0, "127/193 PSA10 レックウザ ボールミラー m2a", "127/193")]
    res = N.save(items, {"picks": [], "catalog_reqs": [0], "outs": [], "holds": [],
                         "card_nos": []})
    assert "rows" not in sent, "catalog に実在するのに追加依頼を出した"
    assert res["catalog"] == 0


def test_save_still_requests_when_extracted_number_truly_absent(monkeypatch):
    sent = {}
    monkeypatch.setattr(N, "_append_tab", lambda *a: None)
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N, "live_key_set", lambda: set())
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab: [])
    monkeypatch.setattr(N.sheet_io, "write_rows_to_tab", lambda tab, rows: None)
    monkeypatch.setattr(N, "append_missing_models",
                        lambda rows, path=None: sent.setdefault("rows", rows) or len(rows))
    monkeypatch.setattr(N, "catalog_variants", lambda no, db=None: [])
    items = [_item(0, "999/999 PSA10 未知のカード zz9", "999/999")]
    res = N.save(items, {"picks": [], "catalog_reqs": [0], "outs": [], "holds": [],
                         "card_nos": []})
    assert "rows" in sent and len(sent["rows"]) == 1
    assert res["catalog"] == 1
