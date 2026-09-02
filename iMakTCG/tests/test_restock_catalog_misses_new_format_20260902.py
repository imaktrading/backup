# -*- coding: utf-8 -*-
"""RESTOCK fork (psa_restock_csv.py) の catalog_misses を psa_to_csv と同じ
`cert{N} {brand} [{subject}] #{cardno} (missing_models: catalog未登録)` 書式に揃える (2026-09-02)。

何が起きていたか: psa_restock_csv.build_row の catalog_misses.append は5箇所とも旧書式
`f"{brand}-{card_number}"` のままで、cert を持たない2要素タプルだった。gundam の
架空ID (PSA ラベルの CardNumber が prefix 無し "001" で catalog の EXBP-001/RP-001 と
完全一致しない) のような miss が、psa_to_csv 側 (09-01 に統一済) と別書式のまま
missing_models.csv / pdca queue に乗り続けていた。

出典: hq/requests/2026-09-01_catalog_missing_models_bogus_id_response.md
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psa_restock_csv  # noqa: E402
from psa_restock_csv import build_row  # noqa: E402


def test_gundam_prefixless_card_number_miss_uses_new_format(monkeypatch):
    """prefix 無し CardNumber ("001") の gundam miss が cert{N} 書式で1行だけ出る。"""
    monkeypatch.setattr(psa_restock_csv.catalog_psa, "lookup_gundam", lambda *a, **k: None)
    monkeypatch.setenv("TCG_USE_NEW_GEN", "1")  # PSA9 で早期return させ、Claude/画像呼出を回避

    catalog_misses = []
    data = {
        "Subject": "Freedom Gundam",
        "CardNumber": "001",
        "Brand": "GUNDAM EX BASE SET",
        "Year": 2025,
        "Grade": "MINT 9",  # PSA10のみ出品ゲートで build_row が None を返す = Claude/画像処理前で止まる
    }

    result = build_row("99999999", 100.0, data, "desc", driver=None, catalog_misses=catalog_misses)

    assert result is None  # PSA9ゲートで弾かれる (今回の検証には無関係、早期returnを使っているだけ)
    assert len(catalog_misses) == 1
    category, model, subject, cert, brand = catalog_misses[0]
    assert category == "gundam_tcg"
    assert model == "cert99999999 GUNDAM EX BASE SET [Freedom Gundam] #001 (missing_models: catalog未登録)"
    assert subject == "Freedom Gundam"
    assert cert == "99999999"
    assert brand == "GUNDAM EX BASE SET"
