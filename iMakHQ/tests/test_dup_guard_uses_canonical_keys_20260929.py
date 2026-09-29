# -*- coding: utf-8 -*-
"""入稿直前の重複チェックは、出品を作った時の KEY の控え (.canonical.json) も使う (2026-09-29)。

実害: シートへの KEY 書込が「決められず」で飛ばした行は、タイトルの番号 (`t:OP09-051`) で照らしていた。
出品中の側は KEY で並んでいるので番号どうしは一致せず、OP09-051 が 9/24〜27 に4つ、
ウタ OP02-120_p2 が 9/22・9/23 に2つ出品された。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import dup_guard as D  # noqa: E402


def test_canonical_keys_are_read_next_to_the_csv(tmp_path):
    csv_path = tmp_path / "tcg_upload_x.csv"
    csv_path.write_text("a\n", encoding="utf-8")
    (tmp_path / "tcg_upload_x.canonical.json").write_text(
        json.dumps({"by_cert": {"97805202": "one_piece_tcg:OP09-051"}}), encoding="utf-8")
    assert D.canonical_keys_for_csv(str(csv_path)) == {"97805202": "one_piece_tcg:OP09-051"}
    assert D.canonical_keys_for_csv(str(tmp_path / "none.csv")) == {}


def test_second_copy_is_caught_with_the_generation_key():
    header = [D.CSV_LABEL, D.CSV_CERT, D.CSV_TITLE]
    rows = [["m1", "97805202", "PSA 10 One Piece #OP09-051 Nami"]]
    index = {D.group_key("one_piece_tcg:OP09-051"): ["820165775241"]}
    assert D.dup_candidates(rows, header, index, {}) == []            # 番号だけでは一致しない (元の穴)
    got = D.dup_candidates(rows, header, index, {"97805202": "one_piece_tcg:OP09-051"})
    assert [c["existing"] for c in got] == [["820165775241"]]
    assert not got[0]["card_key"].startswith("t:")                    # 完全一致 = 物理除外の対象


def test_generation_key_wins_over_sheet_key():
    import inspect
    src = inspect.getsource(D.pre_upload)
    # 控えの KEY はシートにある cert でも上書きする (c not in cert_to_key の条件が無い)
    assert "canonical_keys_for_csv(csv_path).items()" in src
    assert "c not in cert_to_key" not in src


def test_sheet_key_is_aligned_to_the_reviewed_key():
    def row(b, cert, key):
        r = [""] * 40
        r[D.B], r[D.CERT], r[D.KEY] = b, cert, key
        return r
    sheet = [["h"] * 40,
             row("", "174855277", "one_piece_tcg:EB03-026"),       # 目視は _p1 → 直す
             row("", "111", "one_piece_tcg:OP01-001"),              # 一致 → そのまま
             row("820000000001", "222", "x:old")]                   # 出品済の行は触らない
    gen = {"174855277": "one_piece_tcg:EB03-026_p1", "111": "one_piece_tcg:OP01-001", "222": "x:new"}
    assert D.keys_to_fix(sheet, gen) == [(2, "174855277", "one_piece_tcg:EB03-026", "one_piece_tcg:EB03-026_p1")]


def test_panel_runs_the_alignment_after_write_keys():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "control_panel.py"), encoding="utf-8").read()
    assert src.index("--write-keys-from-csv") < src.index("--keys-from-canonical")
