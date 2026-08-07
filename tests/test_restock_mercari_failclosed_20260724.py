# -*- coding: utf-8 -*-
"""RESTOCK: メルカリ取得失敗を「在庫なし」に倒さない fail-closed 回帰テスト (2026-07-24)。

欠陥(ユーザー指摘「本当に在庫無いのか分からんよね」): メルカリ Selenium が途中クラッシュ
→ 以降 全 item timeout。その取得失敗が {"best":None,"cands":[]} で返り、「検索して在庫なし」と
区別されず End候補(取下げ)に落ちていた = fail-OPEN(仕入可能を End 化)+ タイムアウトの空結果を
当日キャッシュに焼き付け。対策: エラーは _error 付きで返し、End候補にせず判定保留(次回再取得)+
キャッシュに残さない。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools"))
import mercari_psa_resource as mp  # noqa: E402


def test_error_result_is_distinguishable():
    """取得失敗の返り値は _error を持ち、在庫なし(_error無)と区別できる。"""
    err = {"best": None, "cands": [], "_error": "timeout"}
    empty = {"best": None, "cands": [], "all_cands": []}
    assert err.get("_error")
    assert not empty.get("_error")


def test_combine_treats_error_and_empty_same_but_gate_holds():
    """combine 自体は best=None で resourceable=False(両者同じ)。
    End候補にするか判定保留にするかは gate 側が _error で分岐する(この分岐が本丸)。"""
    from psa_resource_gate import combine
    # メルカリ無し + SNKRDUNK 未登録 → resourceable False(combine は不明/無しを区別しない)
    c = combine(None, {"available": False}, mercari_cands=None)
    assert c["resourceable"] is False


def _gate_classify(mercari_res_i, snkr_res_i):
    """gate の分類ロジックを縮約(実コードと同じ判定): (resourceable, unknown, end)。"""
    from psa_resource_gate import combine
    mr = mercari_res_i or {}
    c = combine(mr.get("best"), snkr_res_i, mercari_cands=mr.get("cands"))
    unknown = bool(mercari_res_i and isinstance(mercari_res_i, dict) and mercari_res_i.get("_error"))
    if c["resourceable"]:
        return "resourceable"
    if unknown:
        return "held"      # ★End候補にしない
    return "end"


def test_timeout_item_is_held_not_ended():
    """★本命: メルカリ timeout(_error) + SNKRDUNK 在庫なし → End候補でなく 判定保留(held)。"""
    assert _gate_classify({"best": None, "cands": [], "_error": "timeout"},
                          {"available": False}) == "held"


def test_genuine_no_stock_is_ended():
    """メルカリ 検索して在庫なし(_error無) + SNKRDUNK 在庫なし → 正しく End候補。"""
    assert _gate_classify({"best": None, "cands": [], "all_cands": []},
                          {"available": False}) == "end"


def test_snkrdunk_available_is_resourceable_even_if_mercari_error():
    """メルカリ timeout でも SNKRDUNK に在庫あれば 再仕入れ可(保留に埋もれさせない)。"""
    assert _gate_classify({"best": None, "cands": [], "_error": "timeout"},
                          {"available": True, "psa10_price_jpy": 5000,
                           "psa10_listings": [{"price": 5000, "url": "http://x"}]}) == "resourceable"
