# -*- coding: utf-8 -*-
"""先行出品(競合0件)価格の V8/V9 SSOT 統一 回帰テスト (2026-07-23)。

バグ: psa_to_csv / psa_restock_csv の「競合0件→先行出品」分岐だけ pricing_engine を
呼ばず、インラインのレガシー式 (get_tier_params(100) + NET_RATIO 定数) で価格を計算
→ V9 SSOT と数ドルずれる (実害: DON-EB04-002 が $186.98、V9 正解 $190.98 = $4 過小)。
通常経路(市場価格あり)は compute_listing_price 使用で一致済み。

psa_to_csv は module-level 副作用が重く import 不可のため、ソース構造で固定する
(レガシー式の不在 + エンジン呼び出しの存在を両ファイルで検証)。
"""
import io
import os
import re

_BASE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakTCG"))


def _pioneer_branch(fname):
    """「競合0件」コメントから CSV価格更新までの branch 部分を切り出す。"""
    with io.open(os.path.join(_BASE, fname), encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"# 競合0件.*?# CSVの価格を更新", src, re.DOTALL)
    assert m, f"{fname}: 先行出品 branch が見つからない"
    return m.group(0)


def test_psa_to_csv_pioneer_uses_engine():
    """★本命: psa_to_csv の先行出品価格が pricing_engine 経由。"""
    b = _pioneer_branch("psa_to_csv.py")
    assert "compute_listing_price" in b, "エンジン未使用 (SSOT 違反)"
    assert "NET_RATIO - tier_profit" not in b, "レガシー式が残存"
    assert "get_tier_params(100)" not in b, "レガシー tier 参照が残存"


def test_psa_restock_pioneer_uses_engine():
    """fork (psa_restock_csv) にも同修正が入っていること。"""
    b = _pioneer_branch("psa_restock_csv.py")
    assert "compute_listing_price" in b, "エンジン未使用 (SSOT 違反)"
    assert "NET_RATIO - tier_profit" not in b, "レガシー式が残存"


def test_floor_100_preserved():
    """$100 フロア (市場未形成の最低ライン) は両ファイルで維持。"""
    for fname in ("psa_to_csv.py", "psa_restock_csv.py"):
        b = _pioneer_branch(fname)
        assert "100.98" in b and "100.00" in b, f"{fname}: $100 フロア欠落"
