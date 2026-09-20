# -*- coding: utf-8 -*-
"""直した後もカタログへ送り続ける穴を塞ぐ (2026-09-20)。

依頼書: hq/requests/2026-09-20_act_code_proposals_tcg.md 提案1 / 2 / 3

実測: cert160479905 は 9/19 に真因 (②引き方) を直したのに 9/20 もまた層Aに載った。
  提案1 `finding_type='resolver_gap'` が発行直前の再確認をすり抜けていた
  提案2 cert 引き直しが `RESOLVED` のときしか閉じず、`REVIEW`(候補在り=カタログに在る)
        を「未収録」として送っていた
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import sqlite3  # noqa: E402

import pdca_store as P  # noqa: E402


def _empty_catalog(tmp_path):
    """products が空の catalog (= product_id では当たらない状態)。"""
    db = str(tmp_path / "products.sqlite")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE products (category TEXT, product_id TEXT, "
                "alias_of TEXT, images TEXT)")
    con.commit()
    con.close()
    return db


def _row(finding_type):
    return {"finding_type": finding_type, "category": "pokemon_tcg",
            "item_id": "cert160479905", "target_field": "catalog_add",
            "identity": "", "evidence": ""}


def test_resolver_gap_row_is_closed_too():
    hit = lambda cert: True                                    # noqa: E731
    assert P.row_solved_in_catalog(_row("resolver_gap"), cert_fn=hit)
    assert P.row_solved_in_catalog(_row("catalog_gap"), cert_fn=hit)


def test_unrelated_finding_type_is_still_sent():
    """catalog では判定できない行は従来どおり触らない (fail-closed)。"""
    assert not P.row_solved_in_catalog(_row("program_fix"), cert_fn=lambda c: True)


def test_review_with_candidates_counts_as_present_in_catalog(tmp_path):
    (tmp_path / "160479905.json").write_text("{}", encoding="utf-8")
    seen = {}

    def _classify(cert, meta, con):
        seen["cert"] = cert
        return {"status": "REVIEW", "candidates": ["SM3H-053"]}

    v = P.make_pre_emit_verifier(_empty_catalog(tmp_path), classify_fn=_classify,
                                certs_dir=str(tmp_path))
    assert v(_row("resolver_gap")) is True
    assert seen["cert"] == "160479905"


def test_review_without_candidates_is_still_sent(tmp_path):
    (tmp_path / "160479905.json").write_text("{}", encoding="utf-8")
    v = P.make_pre_emit_verifier(
        _empty_catalog(tmp_path),
        classify_fn=lambda *a: {"status": "REVIEW", "candidates": []},
        certs_dir=str(tmp_path))
    assert v(_row("resolver_gap")) is False


def test_queue_table_shows_act_verdict():
    rows = P._queue_table([{"priority": 15.0, "item_id": "cert160479905",
                            "identity": "HO-OH GX #053", "target_field": "catalog_add",
                            "suggested_value": "", "confidence": 1.0,
                            "act_verdict": "誤検出 (②引き方)", "evidence": "今日も除外"}])
    assert "Act判定" in rows[0]
    assert "誤検出 (②引き方)" in rows[-1]
