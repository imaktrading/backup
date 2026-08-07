#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV監査くん PDCA 台帳 — 監査結果を時系列蓄積し、前回比トレンドと再発を出す。

これが無いと監査は「検出して終わり(Check止まり)」= スパイラルアップしない ([[pdca_spiral_up_expectation]])。
台帳に毎回のサマリ(KPI)と finding キーを追記 → 次回実行時に:
  - 前回比トレンド (短タイトル率↓ / 平均長↑ / 形式逸脱↓ / 整合不一致↓ など改善/悪化)
  - 再発検知 (前回と同じ item×種別の finding が残ってる = まだ直ってない / REGRESSION)
  - 解消検知 (前回有った finding が消えた = 改善された)
を返す。csv_auditor がこれを表示し、PDCA の Act/測定を回す。
"""
import datetime
import json
import os

LEDGER_DIR = r"C:/dev/iMak_data/audit"
LEDGER_PATH = os.path.join(LEDGER_DIR, "ledger.jsonl")


def _read_all():
    if not os.path.exists(LEDGER_PATH):
        return []
    out = []
    with open(LEDGER_PATH, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def last_run(category, entries=None):
    """同 category の直近エントリ (無ければ None)。"""
    entries = entries if entries is not None else _read_all()
    for e in reversed(entries):
        if e.get("category") == category:
            return e
    return None


def record_run(category, summary, finding_keys, stamp=None, write=True):
    """1 監査実行を台帳化。
    summary: {metric: number} (KPI)。finding_keys: list[str] (item×種別の安定キー)。
    返り: {previous, trend, recurring, new, resolved}。dry-run は write=False で追記しない。"""
    prev = last_run(category)
    trend = {}
    if prev:
        psum = prev.get("summary", {})
        for k, v in summary.items():
            pv = psum.get(k)
            if isinstance(v, (int, float)) and isinstance(pv, (int, float)):
                trend[k] = round(v - pv, 4)
    prev_keys = set(prev.get("finding_keys", [])) if prev else set()
    cur_keys = set(finding_keys)
    result = {
        "previous": prev,
        "trend": trend,
        "recurring": sorted(cur_keys & prev_keys),  # 前回も今回も有る = まだ直ってない
        "new": sorted(cur_keys - prev_keys),        # 今回新規
        "resolved": sorted(prev_keys - cur_keys),   # 前回有→今回無 = 解消
    }
    if write:
        entry = {
            "date": stamp or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "category": category,
            "summary": summary,
            "finding_keys": sorted(cur_keys),
        }
        os.makedirs(LEDGER_DIR, exist_ok=True)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return result


# 改善方向 (down=小さいほど良い KPI / up=大きいほど良い KPI)。トレンド矢印の向き判定用。
KPI_BETTER_WHEN = {
    "rows": None, "excluded": "down", "program": "down", "seo_weak": "down",
    "short_titles": "down", "format_violations": "down", "consistency_mismatch": "down",
    "avg_title_len": "up",
}


def trend_arrow(metric, delta):
    """delta の符号と KPI 方向から 改善(↑良)/悪化(↓悪)/横ばい の記号を返す。"""
    if delta == 0:
        return "→"
    better = KPI_BETTER_WHEN.get(metric)
    if better is None:
        return "+" if delta > 0 else "-"
    good = (delta < 0) if better == "down" else (delta > 0)
    return "✅改善" if good else "⚠️悪化"
