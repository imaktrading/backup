# -*- coding: utf-8 -*-
"""目視で確定した product_id を、次回以降ちゃんと再利用する (2026-08-09).

なぜ (真因):
    同定を **毎回ゼロからやり直す** 設計になっていた。PSA の英語ラベルを解析 →
    失敗したら人に聞く → **人の答えはその回の出品にしか使われず捨てられる**。

    ところが答えは実際には保存されていた: `verified_certs.json` に 601件
    (うち 593件が product_id 付き)。読み手が居なかっただけ。

    実害: 出品できなかった DON!! 14件のうち **13件は既に人が選び終わっており、
    catalog にも実在**していた。
      cert149436895 → DON-PRB02-001 / cert152887215 → DON-PRB01-024
      cert154699036 → DON-EB03-007  / cert158444644 → DON-PRB01-027 …
    それを「catalog に無い(GAP)」と報告し、カタログに要らない依頼を出しかけた。

固定する挙動:
  1. choice が CHOSEN / OK の時だけ採用 (NONE / NG は採用しない)
  2. product_id 空・台帳が壊れている・ファイル無し → None (推測しない)
  3. 台帳をそのまま信じない。**catalog に実在する時だけ**レコードを返す
  4. resolver を先に試し、外した時の最後の手段として使う (順番)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"C:\dev\iMak\iMakHQ\tools")
import psa_preflight as PF  # noqa: E402

TCG = Path(r"C:\dev\iMak\iMakTCG\psa_to_csv.py")


def _load_helpers():
    """psa_to_csv 本体を import せずに、対象の純関数だけ取り出す。

    (本体 import は catalog/Chrome 系を引きずり、他テストと衝突するため)
    """
    import types
    src = TCG.read_text(encoding="utf-8")
    start = src.index("VERIFIED_CERTS_PATH =")
    end = src.index("def don_treatment_subject")
    mod = types.ModuleType("_don_helpers")
    mod.__dict__["json"] = json
    exec(compile(src[start:end], str(TCG), "exec"), mod.__dict__)
    return mod


H = _load_helpers()


def _ledger(tmp_path, data):
    p = tmp_path / "verified_certs.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


# ---- 1. choice の扱い --------------------------------------------------------


@pytest.mark.parametrize("choice,expected", [
    ("CHOSEN", "DON-PRB02-001"),
    ("OK", "DON-PRB02-001"),
    ("chosen", "DON-PRB02-001"),      # 大小無視
    ("NONE", None),
    ("NG", None),
    ("", None),
])
def test_only_confirmed_choices_are_reused(tmp_path, choice, expected):
    p = _ledger(tmp_path, {"149436895": {"choice": choice, "product_id": "DON-PRB02-001"}})
    assert H.confirmed_product_id("149436895", p) == expected


# ---- 2. 壊れた入力は None (推測しない) ---------------------------------------


def test_empty_product_id_is_none(tmp_path):
    p = _ledger(tmp_path, {"1": {"choice": "CHOSEN", "product_id": "  "}})
    assert H.confirmed_product_id("1", p) is None


def test_missing_file_is_none():
    assert H.confirmed_product_id("1", r"C:\nope\missing.json") is None


def test_broken_json_is_none(tmp_path):
    p = tmp_path / "v.json"
    p.write_text("{ broken", encoding="utf-8")
    assert H.confirmed_product_id("1", str(p)) is None


def test_unknown_cert_is_none(tmp_path):
    p = _ledger(tmp_path, {"999": {"choice": "CHOSEN", "product_id": "X-1"}})
    assert H.confirmed_product_id("111", p) is None


def test_non_dict_entry_is_none(tmp_path):
    p = _ledger(tmp_path, {"1": "DON-PRB02-001"})
    assert H.confirmed_product_id("1", p) is None


# ---- 3. catalog 実在確認つきでしか返さない ------------------------------------


def test_record_returned_only_when_catalog_has_it(tmp_path):
    p = _ledger(tmp_path, {"1": {"choice": "CHOSEN", "product_id": "DON-PRB02-001"}})
    rec = {"product_id": "DON-PRB02-001", "name": "DON!! Card"}
    got = H.confirmed_catalog_record("1", "one_piece_tcg", p, lookup_fn=lambda c, i: rec)
    assert got == rec


def test_record_is_none_when_catalog_lost_the_id(tmp_path):
    """台帳に有っても catalog から消えていたら出品しない (人の入力を鵜呑みにしない)。"""
    p = _ledger(tmp_path, {"1": {"choice": "CHOSEN", "product_id": "GONE-001"}})
    assert H.confirmed_catalog_record("1", "one_piece_tcg", p, lookup_fn=lambda c, i: None) is None


def test_record_is_none_when_lookup_raises(tmp_path):
    p = _ledger(tmp_path, {"1": {"choice": "CHOSEN", "product_id": "X-1"}})

    def boom(c, i):
        raise RuntimeError("catalog 落ちてる")
    assert H.confirmed_catalog_record("1", "one_piece_tcg", p, lookup_fn=boom) is None


def test_category_is_passed_through(tmp_path):
    """カテゴリ跨ぎで拾わない (別ゲームの同 ID を掴まない)。"""
    p = _ledger(tmp_path, {"1": {"choice": "CHOSEN", "product_id": "ST02-010"}})
    seen = {}

    def fn(cat, pid):
        seen["cat"] = cat
        return None
    H.confirmed_catalog_record("1", "gundam_tcg", p, lookup_fn=fn)
    assert seen["cat"] == "gundam_tcg"


# ---- 4. 順番: resolver が先、台帳は最後の手段 --------------------------------


def test_don_branch_tries_resolver_before_ledger():
    """`confirmed_catalog_record` は lookup_don が None を返した後にだけ呼ばれる。"""
    src = TCG.read_text(encoding="utf-8")
    i_lookup = src.index("catalog_psa.lookup_don(")
    i_ledger = src.index("confirmed_catalog_record(cert_number")
    assert i_lookup < i_ledger, "台帳を resolver より先に見ている (catalog 修正が上書きされる)"


# ---- preflight 側も同じ台帳を読む --------------------------------------------


def test_preflight_reads_the_same_ledger():
    assert PF.VERIFIED_CERTS.name == "verified_certs.json"
    PF._VERIFIED_CACHE = {"1": {"choice": "CHOSEN", "product_id": "DON-PRB02-001"},
                          "2": {"choice": "NONE", "product_id": ""}}
    try:
        assert PF._confirmed_pid("1") == "DON-PRB02-001"
        assert PF._confirmed_pid("2") is None
        assert PF._confirmed_pid("nope") is None
    finally:
        PF._VERIFIED_CACHE = None
