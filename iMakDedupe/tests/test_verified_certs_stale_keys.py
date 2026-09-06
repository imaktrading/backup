"""verified_certs.json の product_id が catalog に実在するかの回帰 test.

背景: `iMak_data/dedupe/verified_certs.json` は cert ごとの手動 verify 結果を
キャッシュする dedupe 管轄データ。catalog 側で product_id が rename (旧`_AN03`
suffix 廃止 → 公式 id 統一) されても、このキャッシュは追随せず古い id を持ち
続ける (2026-09-05 hq→dedupe: cert152977069 が `ST15-005_AN03` のまま残存、
正は `ST15-005_p2`)。fail-closed の ID 完全一致 lookup のため誤表示にはならない
が、そのcertが二度と候補に出なくなる (silent に死ぬ)。

本 test は非空 product_id が全て catalog 実在することを固定し、再発を検知する。
共有データ (`iMak_data/`) が無い環境では skip (fail-closed、CI 環境非依存)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dedupe import catalog_io

VERIFIED_CERTS_PATH = Path(r"C:/dev/iMak_data/dedupe/verified_certs.json")


def _require_shared_data():
    if not VERIFIED_CERTS_PATH.exists():
        pytest.skip(f"shared data not present: {VERIFIED_CERTS_PATH}")
    if not catalog_io.CATALOG_DB_PATH.exists():
        pytest.skip(f"shared data not present: {catalog_io.CATALOG_DB_PATH}")


def test_no_stale_product_id_in_verified_certs():
    _require_shared_data()
    data = json.loads(VERIFIED_CERTS_PATH.read_text(encoding="utf-8"))

    con = catalog_io.open_catalog_readonly()
    try:
        valid_pids = catalog_io.load_valid_product_ids(con)
    finally:
        con.close()

    stale = [
        (cert, entry.get("product_id"))
        for cert, entry in data.items()
        if entry.get("product_id")
        and entry["product_id"].upper() not in valid_pids
    ]
    assert stale == [], (
        f"verified_certs.json に catalog 未実在の product_id が {len(stale)} 件: "
        f"{stale[:10]} (catalog rename 後の書換え漏れ。cert→正しい product_id を "
        f"products.sqlite で再照会して書き換える)"
    )


def test_regression_cert152977069_uses_renamed_product_id():
    """2026-09-05 hq→dedupe 修正の固定回帰: cert152977069 は旧 `ST15-005_AN03` でなく
    rename 後の `ST15-005_p2` を持つ。"""
    _require_shared_data()
    data = json.loads(VERIFIED_CERTS_PATH.read_text(encoding="utf-8"))
    entry = data.get("152977069")
    assert entry is not None
    assert entry["product_id"] == "ST15-005_p2"
