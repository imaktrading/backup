# -*- coding: utf-8 -*-
"""PSA Review verify→build の promo 配線 回帰テスト (2026-06-24)。

確定 cert のうち promo 系のみ per-card override に書込/誤書込防止 を固定。
- is_promo フラグの無い行は書かない
- confirmed の product_id が promo variant でなければ書かない (CHOSEN 誤選択ガード)
- 空入力 = レビュー済・promo無し として記録
catalog 参照は実 products.sqlite (P-001=promo / OP06-106=非promo を利用)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "iMakTCG")))

import post_psa_review as pr  # noqa: E402
import tcg_promo_store as ps  # noqa: E402

_PROMO_PID = "P-001_OTHER PRODUCT CARD"
_NORMAL_PID = "OP06-106"
_CAT = "one_piece_tcg"


def test_write_promo_for_confirmed_promo(tmp_path):
    store = str(tmp_path / "promo.json")
    results = [{"cert": "111", "choice": "OK", "expected": _PROMO_PID, "category": _CAT,
                "is_promo": True, "promo": "Ichiban Kuji Purchase Bonus"}]
    confirmed = {"111": _PROMO_PID}
    n = pr._write_promo_overrides(results, confirmed, store_path=store)
    assert n == 1
    assert ps.get_promo(_PROMO_PID, path=store) == "Ichiban Kuji Purchase Bonus"
    assert ps.is_reviewed(_PROMO_PID, path=store)


def test_blank_promo_is_reviewed_not_flagged(tmp_path):
    """空入力(消す) = レビュー済・promo無し → 次回 needs_review False。"""
    store = str(tmp_path / "promo.json")
    results = [{"cert": "111", "choice": "OK", "expected": _PROMO_PID, "category": _CAT,
                "is_promo": True, "promo": ""}]
    pr._write_promo_overrides(results, {"111": _PROMO_PID}, store_path=store)
    assert ps.is_reviewed(_PROMO_PID, path=store)
    assert ps.get_promo(_PROMO_PID, path=store) == ""
    assert not ps.needs_review({"variant_type": "other_product"}, _PROMO_PID, path=store)


def test_non_promo_confirmed_not_written(tmp_path):
    """CHOSEN で非promo product_id を確定した行は書かない (誤書込ガード)。"""
    store = str(tmp_path / "promo.json")
    results = [{"cert": "222", "choice": "CHOSEN", "selected_pid": _NORMAL_PID, "category": _CAT,
                "is_promo": True, "promo": "Bogus"}]
    n = pr._write_promo_overrides(results, {"222": _NORMAL_PID}, store_path=store)
    assert n == 0
    assert not ps.is_reviewed(_NORMAL_PID, path=store)


def test_row_without_is_promo_skipped(tmp_path):
    store = str(tmp_path / "promo.json")
    results = [{"cert": "333", "choice": "OK", "expected": _PROMO_PID, "category": _CAT}]
    n = pr._write_promo_overrides(results, {"333": _PROMO_PID}, store_path=store)
    assert n == 0


def test_promo_for_detects_and_proposes():
    """_promo_for: promo variant 検出 + Subject から下書き / 通常カードは False。"""
    isp, prop = pr._promo_for(_CAT, _PROMO_PID, "MONKEY D. LUFFY ICHIBAN KUJI PURCHASE BONUS")
    assert isp and prop == "Ichiban Kuji Purchase Bonus"
    assert pr._promo_for(_CAT, _NORMAL_PID, "KOZUKI HIYORI")[0] is False
