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
    p = _write(tmp_path, ["Wristwatches", "Wristwatches", "Reels"])
    c = rap.categories_in(p)
    assert c["Wristwatches"] == 2
    assert c["Reels"] == 1


def test_dispatch_covers_known_categories():
    # 既知カテゴリ(Wristwatches/Reels)は dispatch に登録、cmd に --relist と {pending} を含む
    for cat in ("Wristwatches", "Reels"):
        assert cat in rap.CATEGORY_DISPATCH
        cwd, cmd = rap.CATEGORY_DISPATCH[cat]
        assert "--relist" in cmd
        assert "{pending}" in cmd
        assert os.path.basename(cwd) in ("iMakG-shock", "iMakMercari")


def test_unknown_category_not_in_dispatch():
    # 未対応カテゴリは dispatch に無い → main() で警告スキップされる
    assert "Figure" not in rap.CATEGORY_DISPATCH
    assert "T-Shirts" not in rap.CATEGORY_DISPATCH
