# -*- coding: utf-8 -*-
"""取下再出品② オーケストレータ (relist_add_from_pending) のカテゴリ振り分けロジック。"""
import csv
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import relist_add_from_pending as rap  # noqa: E402


def _write(tmp_path, cats):
    p = tmp_path / "relist_pending_x.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["sku", "old_item_id", "category", "supply_url", "price", "title"])
        w.writeheader()
        for i, c in enumerate(cats):
            w.writerow({"sku": f"s{i}", "old_item_id": str(i), "category": c,
                        "supply_url": f"https://x/u{i}", "price": "100", "title": "T"})
    return str(p)


def test_categories_in_counts(tmp_path):
    # category 列は商品管理 col17 の正本カテゴリ (2026-06-23 ASIN/col17 統一)
    p = _write(tmp_path, ["G-shock", "G-shock", "リール"])
    c = rap.categories_in(p)
    assert c["G-shock"] == 2
    assert c["リール"] == 1


def test_dispatch_covers_known_categories():
    # 既知カテゴリ(col17: G-shock/リール/一番くじ/バッグ/tomica)は dispatch 登録、cmd に --relist と {pending}
    for cat in ("G-shock", "リール", "一番くじ", "バッグ", "tomica"):
        assert cat in rap.CATEGORY_DISPATCH
        cwd, cmd = rap.CATEGORY_DISPATCH[cat]
        assert "--relist" in cmd
        assert "{pending}" in cmd
        assert os.path.basename(cwd) in ("iMakG-shock", "iMakMercari")


def test_unknown_category_not_in_dispatch():
    # 未対応カテゴリ(col17)は dispatch に無い → main() で警告スキップされる
    assert "フィギュア" not in rap.CATEGORY_DISPATCH
    assert "グッズ" not in rap.CATEGORY_DISPATCH
    assert "Tシャツ" not in rap.CATEGORY_DISPATCH   # Phase B で追加予定
