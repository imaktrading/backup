# -*- coding: utf-8 -*-
"""HQ が渡した仕入元URL 135件 (UNIQLO 101 / GU 30) が catalog に入っていることの回帰 (2026-09-12).

回答書 `requests/2026-09-09_ut_supply_urls_for_catalog_response.md`:
「公式URLの母集団はこの135件で全部です」「催告があれば取りに行く」に対して、
catalog は CSV の品番を全件 取り込んだ (uniqlo_ut 101件 / gu 30件、廃盤は official_gone_at)。
新しい migration/取り込みが古い行を消したり enrich し忘れたりしたら、ここで検知する。
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api  # noqa: E402

CSV_PATH = Path("C:/dev/iMak_data/catalog/requests/_uniqlo_gu_supply_urls_dump.csv")
PID_RE = re.compile(r"/products/([A-Z0-9-]+)/0[01]")


def _pids_by_host():
    uniqlo, gu = set(), set()
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            url = row["supply_url"]
            m = PID_RE.search(url)
            if not m:
                continue
            pid = m.group(1)
            if "gu-global.com" in url:
                gu.add(pid)
            elif "uniqlo.com" in url:
                uniqlo.add(pid)
    return uniqlo, gu


def _rows_by_pid(category: str):
    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT product_id, specs FROM products WHERE category=?", (category,)
    ).fetchall()
    db.close()
    return {r["product_id"]: json.loads(r["specs"] or "{}") for r in rows}


def _assert_ingested_and_enriched(pids, category, label):
    have = _rows_by_pid(category)
    missing = sorted(pids - have.keys())
    assert not missing, f"{label}: catalog に無い品番 {len(missing)}件: {missing[:10]}"
    not_enriched = []
    no_size_info = []
    for pid in sorted(pids):
        s = have[pid]
        if s.get("official_gone_at"):
            continue  # 廃盤は enrich 対象外 (正しい状態)
        if not s.get("enriched_at"):
            not_enriched.append(pid)
        if not s.get("size_chart") and not s.get("size_chart_absent_at"):
            no_size_info.append(pid)
    assert not not_enriched, f"{label}: enrich されていない品番: {not_enriched}"
    assert not no_size_info, f"{label}: 実寸表も absent マークも無い品番: {no_size_info}"


def test_uniqlo_pids_from_supply_dump_are_ingested_and_enriched():
    if not CSV_PATH.exists():
        import pytest
        pytest.skip("依頼書添付CSVが無い環境")
    uniqlo, _gu = _pids_by_host()
    assert len(uniqlo) == 101
    _assert_ingested_and_enriched(uniqlo, "uniqlo_ut", "UNIQLO")


def test_gu_pids_from_supply_dump_are_ingested_and_enriched():
    if not CSV_PATH.exists():
        import pytest
        pytest.skip("依頼書添付CSVが無い環境")
    _uniqlo, gu = _pids_by_host()
    assert len(gu) == 30
    _assert_ingested_and_enriched(gu, "gu", "GU")
