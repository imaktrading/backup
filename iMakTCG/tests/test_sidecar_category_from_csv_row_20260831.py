# -*- coding: utf-8 -*-
"""目視で確定した PID が category 前置きを失わない (2026-08-31 提案2)。

何が起きていたか: `cert84299672` (`ST11-004_P`) は build_row の lookup が None だった
(= `pid_by_cert` に控えが無い / `recorded` が空) ため、人が viewer で確定した PID が
`"ST11-004_P"` のまま裸で sidecar に残った。監査くんの `catalog_expected_fields` は
前置きの無い鍵を照合しない (`":" not in key`) ため、この行だけ catalog 突合が
黙って skip されていた。

直し方: `recorded` が空でも、CSV 行が既に持っている確定値 (PSA Brand → franchise) から
`category_by_cert` を渡せば前置きを補える。

出典: hq/requests/2026-08-31_act_code_proposals_tcg_response.md 提案2
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.abspath(os.path.dirname(__file__))
_TCG = os.path.abspath(os.path.join(_HERE, ".."))
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

import canonical_pid_sidecar as S  # noqa: E402


def test_keep_category_uses_row_category_when_recorded_is_empty():
    """recorded が空 (build_row lookup miss) でも、渡した category で前置きを補う。"""
    assert S._keep_category("", "ST11-004_P", category="one_piece_tcg") == \
        "one_piece_tcg:ST11-004_P"


def test_keep_category_prefers_recorded_over_passed_category():
    """recorded に既に category が付いていればそちらを優先 (推測で上書きしない)。"""
    assert S._keep_category("gundam_tcg:ST11-004_D", "ST11-004_P",
                            category="one_piece_tcg") == "gundam_tcg:ST11-004_P"


def test_keep_category_without_category_arg_is_unchanged():
    """category を渡さない既存呼び出しは今までどおり (後方互換)。"""
    assert S._keep_category("", "ST11-004_P") == "ST11-004_P"


def test_write_sidecar_applies_category_by_cert(tmp_path):
    """write_sidecar 経由でも category_by_cert が前置きを補う (実際の cert84299672 相当)。"""
    csv_p = str(tmp_path / "tcg_upload_x.csv")
    open(csv_p, "w").close()
    out = S.write_sidecar(
        csv_p,
        pid_by_cert={},                              # build_row の lookup は None (miss)
        confirmed_pids={"84299672": "ST11-004_P"},   # 人が viewer で確定
        category_by_cert={"84299672": "one_piece_tcg"},
    )
    got = json.load(open(out, encoding="utf-8"))["by_cert"]["84299672"]
    assert got == "one_piece_tcg:ST11-004_P", f"前置きが補われていない: {got}"
