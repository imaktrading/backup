# -*- coding: utf-8 -*-
"""「柄の記録」(Fashion Press 由来) が **出品の KEY と混ざらない** ことの回帰テスト (2026-09-13).

ユーザー指摘:「出品くんや抽出くんとの受け渡しの KEY は、問題ないの?」
受け渡しの KEY は `product_id`。柄の記録は **公式の品番を持たない** (FP<記事ID>-<連番>) ので、
出品や在庫・実寸表の対象に混ざると事故になる。

守ること:
  1. 柄の記録には `data_level='fp_design'` と `not_for_listing=True` が必ず付く
  2. product_id は `FP` で始まり、**公式の品番の形 (E######-###) ではない**
  3. 実寸表 / 在庫 / 仕上げ の対象から外れる
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))

import api  # noqa: E402

OFFICIAL_PID = re.compile(r"^E\d{6}-\d{3}$")


def _fp_rows():
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    rows = [(r["product_id"], json.loads(r["specs"] or "{}"))
            for r in db.execute("SELECT product_id, specs FROM products "
                                "WHERE category='uniqlo_ut' AND source='fashion_press_design'")]
    db.close()
    return rows


def test_fp_design_rows_are_marked_and_not_official_pid():
    rows = _fp_rows()
    if not rows:
        import pytest
        pytest.skip("柄の記録がまだ無い環境")
    for pid, s in rows:
        assert s.get("data_level") == "fp_design", pid
        assert s.get("not_for_listing") is True, pid
        assert pid.startswith("FP"), pid
        assert not OFFICIAL_PID.match(pid), f"公式の品番の形をしている: {pid}"


def test_internal_steps_skip_fp_design():
    """実寸表 / 在庫 / 仕上げ の対象取りが柄の記録を外すこと (コードの条件を見る)."""
    for f, needle in (("scrapers/uniqlo_ut_sizechart.py", 'data_level") == "fp_design"'),
                      ("scrapers/uniqlo_ut_stock.py", 'data_level") == "fp_design"'),
                      ("scrapers/uniqlo_ut_enrich.py", 'data_level") == "fp_design"')):
        assert needle in (ROOT / f).read_text(encoding="utf-8"), f
