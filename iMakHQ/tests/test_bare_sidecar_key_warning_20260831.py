# -*- coding: utf-8 -*-
"""前置き無しの sidecar 鍵を黙って skip しない (2026-08-31 提案2)。

`catalog_expected_fields` は `category:product_id` 形式でない鍵 (前置き無し) を
`{}` で返し、その行の catalog 突合を素通りさせる。この判定自体は正しい
(前置きが無ければどのゲームか分からず突合できない) が、**黙って**素通りしていたため
fail-OPEN だった。`is_bare_sidecar_key` は同じ判定を監査くんの件数カウント側にも
使い、専用の1行で警告を出す。

出典: hq/requests/2026-08-31_act_code_proposals_tcg_response.md 提案2
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))

import csv_auditor as ca  # noqa: E402


def test_bare_key_is_flagged():
    assert ca.is_bare_sidecar_key("ST11-004_P") is True


def test_prefixed_key_is_not_flagged():
    assert ca.is_bare_sidecar_key("one_piece_tcg:ST11-004_P") is False


def test_empty_key_is_not_flagged():
    """空鍵は「無い」であって「前置き無し」ではない (別カテゴリの finding)。"""
    assert ca.is_bare_sidecar_key("") is False
    assert ca.is_bare_sidecar_key(None) is False


def test_predicate_matches_catalog_expected_fields_skip_condition():
    """is_bare_sidecar_key が真の鍵は catalog_expected_fields が {} を返す鍵と一致する。"""
    for key in ("ST11-004_P", "bare-id-123"):
        assert ca.is_bare_sidecar_key(key)
        assert ca.catalog_expected_fields(key) == {}
