"""出品一覧の取得を1本化 (総点検 10番・2026-10-01)。

itemID 書き戻しの確認と重複チェックが、それぞれ全件 (約24呼出) を取り直していた。
取った一覧から重複チェック用の形を作る関数が、従来の dup_guard の取り方と同じ結果を返すこと。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import itemid_writeback_audit as ia  # noqa: E402


def test_titles_skus_from_live_keeps_us_only():
    live = {
        "1": {"cur": "USD", "title": "PSA10 Pikachu", "sku": "PSA10-123"},
        "2": {"cur": "GBP", "title": "PSA10 Pikachu", "sku": "PSA10-123"},   # ミラー
        "3": {"cur": "USD", "title": "Tee", "sku": ""},
    }
    titles, skus = ia.titles_skus_from_live(live)
    assert titles == {"1": "PSA10 Pikachu", "3": "Tee"}
    assert skus == {"1": "PSA10-123"}
    assert ia.titles_skus_from_live({}) == ({}, {})
