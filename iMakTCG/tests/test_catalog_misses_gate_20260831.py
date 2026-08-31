# -*- coding: utf-8 -*-
"""catalog_misses (build_row の ID lookup miss) をゲート無しで missing_models.csv に
直書きしない (2026-08-31)。

何が起きていたか: `build_row` の `catalog_misses.append` は preflight の名前引きゲート
(`gap_queue_target`, 2026-08-28) を一度も通らず missing_models.csv に直書きしていた。
cert84299672 (ONE PIECE ENCORE PACK-004) は **同じ走行の入稿CSVに正しい値で載っている**
のに「catalog 未登録」と記録された (= 出品できている=引けているのに嘘の記録)。

出典: hq/requests/2026-08-31_act_code_proposals_tcg_response.md 提案1
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from psa_to_csv import gate_catalog_misses  # noqa: E402


def _miss(category="one_piece_tcg", model="ONE PIECE JAPANESE FILM RED: ENCORE PACK-004",
          subject="New Genesis", cert="84299672", brand="ONE PIECE JAPANESE FILM RED"):
    return (category, model, subject, cert, brand)


def test_cert_already_in_csv_is_dropped_entirely():
    """出品できた(=CSVに載った) cert は missing にも program にも積まない。"""
    miss = _miss()
    missing, program = gate_catalog_misses([miss], {"84299672"}, lambda *_: ["ST11-004_p1"])
    assert missing == []
    assert program == []


def test_name_hit_goes_to_program_not_missing():
    """cert が CSV に無いが、subject 名で catalog に行が見つかる → missing_models には書かない。"""
    miss = _miss(cert="999999999")
    missing, program = gate_catalog_misses([miss], set(), lambda *_: ["ST11-004_p1"])
    assert missing == []
    assert len(program) == 1
    assert program[0][:2] == ("one_piece_tcg", "ONE PIECE JAPANESE FILM RED: ENCORE PACK-004")
    assert program[0][4] == ["ST11-004_p1"]


def test_no_name_hit_still_goes_to_missing_models():
    """名前でも見つからない = 従来どおり missing_models へ (新たに断定を強めない)。"""
    miss = _miss(cert="999999999")
    missing, program = gate_catalog_misses([miss], set(), lambda *_: [])
    assert missing == [("one_piece_tcg", "ONE PIECE JAPANESE FILM RED: ENCORE PACK-004")]
    assert program == []


def test_lookup_exception_falls_back_to_missing_models():
    """名前引き自体が失敗しても記録は失われない (fail-closed: 判定不能は握り潰さない)。"""
    def _boom(*_a):
        raise RuntimeError("db error")
    miss = _miss(cert="999999999")
    missing, program = gate_catalog_misses([miss], set(), _boom)
    assert missing == [("one_piece_tcg", "ONE PIECE JAPANESE FILM RED: ENCORE PACK-004")]
    assert program == []


def test_multiple_misses_are_independent():
    a = _miss(cert="111", model="A-001", subject="Alpha")
    b = _miss(cert="222", model="B-002", subject="Beta")
    lookups = {"Alpha": ["hitA"], "Beta": []}
    missing, program = gate_catalog_misses(
        [a, b], set(), lambda category, subject, brand: lookups.get(subject, []))
    assert [p[1] for p in program] == ["A-001"]
    assert [m[1] for m in missing] == ["B-002"]
