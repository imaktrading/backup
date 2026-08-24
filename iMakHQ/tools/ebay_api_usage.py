#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ebay_api_usage — eBay API を1日に何回叩いたか (2026-08-24 監視くん依頼)。

## なぜ
8/24 11:00 に eBay の1日上限 (エラー518) に当たり、16:00 の回復まで **取下げが1件も
送れなかった**。仕入元が売切なのに買える出品が6件残った (キャンセル → Defect の一歩手前)。

鍵は 8/21 に1本化済みなので、**誰か1つが使い切ると全員が止まる**。ところが監視くん以外は
自分の消費を数えておらず、原因を特定できなかった。eBay の使用量照会 (GetApiAccessRules) は
廃止済 (HTTP 410) なので、**自分で数えるしかない**。

★止まるのは取下げ。出品はやり直せるが、取下げ漏れはキャンセルに直結する。
  だから「誰が使ったか」を後から言えることが要る。

## 数え方
`iMakeBayAPI/fix_de_speedpak_shipping.post()` が唯一の Trading API 出口なので、そこで数える。
eBay の1日は **日本時間 16:00 区切り**なので、集計もその境界に合わせる。

## 使い方
    python ebay_api_usage.py            # 今日の内訳
    python ebay_api_usage.py --days 7   # 直近7日
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

USAGE_PATH = r"C:\dev\iMak_data\hq\ebay_api_usage.json"
DAILY_LIMIT = 5000
# 取下げ (監視くん) の分を必ず残すための目安。監視くんの実測は 200〜370回/日。
SAFE_BUDGET = 3000


def load(path=None):
    try:
        with open(path or USAGE_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:                                          # noqa: BLE001
        return {}


def summarize(data, days=1):
    """[(日付, 合計, [(callname, 回数)…])] を新しい順に。純関数・test 可。"""
    out = []
    for day in sorted(data, reverse=True)[:days]:
        bucket = dict(data[day] or {})
        total = int(bucket.pop("_total", 0))
        calls = sorted(bucket.items(), key=lambda kv: -int(kv[1]))
        out.append((day, total, [(k, int(v)) for k, v in calls]))
    return out


def verdict(total, limit=DAILY_LIMIT, safe=SAFE_BUDGET):
    """使い過ぎか (純関数)。取下げの枠を残せているかで見る。"""
    if total >= limit:
        return "over", "★上限に達しています。取下げが送れません"
    if total >= safe:
        return "warn", f"目安 {safe} を超えました。取下げの枠を食い始めています"
    return "ok", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--path", default=USAGE_PATH)
    a = ap.parse_args()

    data = load(a.path)
    if not data:
        print(f"記録がありません ({a.path})")
        print("  ※ 数え始めたのは 2026-08-24。それ以前の分は残っていません")
        return 0
    print("=== eBay API 呼出回数 (1日=日本時間16:00 区切り) ===")
    rc = 0
    for day, total, calls in summarize(data, a.days):
        state, msg = verdict(total)
        mark = {"ok": "🟢", "warn": "🟡", "over": "🔴"}[state]
        print(f"\n{mark} {day}  合計 {total} / 上限 {DAILY_LIMIT}")
        if msg:
            print(f"   {msg}")
            rc = 1
        for name, n in calls:
            print(f"     {name:28} {n:6}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
