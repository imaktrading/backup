#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出品した分だけ棚を空ける — 落とす出品を選んで取り下げる (2026-08-26)。

なぜ必要か:
    eBay の出品リミットは **金額** ($1M)。件数は半分以上あまっており、詰まっているのは金額だけ。
    出品を続ける限り棚は埋まり続けるので、**出した分より少し多く落とす**運用にしないと
    出品が止まる。落とす相手は「稼いでいないもの」から選ぶ。

決めたこと (2026-08-26 ユーザー確定):
    - **カテゴリを跨いで横並び**で選ぶ。売れないカテゴリの中で最適化しても、
      売れるカテゴリの1件には及ばない (Gemini 指摘)。棚割は結果として動いてよい。
    - 落とす額は **その日に出品した額の 1.3倍**。毎日少しずつ棚を空け、
      空いた分を成績の良いカテゴリに回す。

落とす順 (上から埋めて、目標額に達したら止める):
    ① 仕入元が死んでいる   … 買えないので稼ぎようがない。空く額の大きい順
    ② 出品30日超・未販売   … **アクセス (累計表示) の少ない順**

    ★閾値は設けない (2026-08-26 ユーザー確定)。「表示◯回以上なら」という線は
      カテゴリごとに桁が違って必ずどちらかを取りこぼすので、順位で決める。
    ★空く額は **ミラー込み** で数える。US価格だけ見ると効き目を読み違える
      (実測: ある層は US $63,808 に対し棚は $272,890 空く)。

触らない:
    ・出品30日未満 (まだ判定できない)
    ・売れた実績あり
    ・US 以外 (UK/AU/CA は eBaymag のミラー。親を落とせば消える)

使い方:
    python shelf_evict.py                    # 候補を出すだけ
    python shelf_evict.py --end              # eBay に End を送る
    python shelf_evict.py --amount 20000     # 目標額を直接指定する
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cull_end as CE          # noqa: E402
import listing_funnel as LF    # noqa: E402

RATIO = 1.3          # 出品額に対して落とす倍率
REPORT_GLOB = r"C:\dev\iMak_data\seller_hub\reports\**\eBay-all-active-listings-report-*.csv"
CSV_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "csv_output"))

TIER_OOS, TIER_STALE = 1, 2
TIER_NAME = {TIER_OOS: "① 仕入元が死んでいる",
             TIER_STALE: "② 30日超・未販売 (アクセスの少ない順)"}
# 出品からこれ未満は「まだ判定できない」ので触らない。
MIN_AGE_DAYS = 30


def _f(v):
    try:
        return float(str(v or 0).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0.0


def tier_of(row, min_age=MIN_AGE_DAYS):
    """その出品を落とす順の何番に置くか。触らないものは None (純関数, test可)。

    ★2026-08-26 ユーザー確定: **閾値を設けない**。表示回数がいくつ以上なら…という線は引かず、
      「30日超・未販売」を対象にして、その中を **アクセスの少ない順** に落とす。
      固定の閾値はカテゴリごとに桁が違って必ずどちらかを取りこぼす。
    """
    if _f(row.get("qty")) == 0:
        return TIER_OOS                   # 買えないので稼ぎようがない
    if _f(row.get("sold_qty")) + _f(row.get("sales90")) > 0:
        return None                       # 売れた実績あり
    if _f(row.get("age_days")) < min_age:
        return None                       # まだ判定できない
    return TIER_STALE


def pick(rows, target, shelf_of):
    """目標額に届くまで、順位の上から選ぶ。戻り: (選んだ行, 空く額) 純関数, test可。

    ① は空く額の大きい順 (1件で空く額が大きいほうが先)。
    ② は **アクセス (累計表示) の少ない順**。見てもらえていないものから畳む。
    """
    cand = []
    for r in rows:
        t = tier_of(r)
        if t is None:
            continue
        rank = -shelf_of(r) if t == TIER_OOS else _f(r.get("impr_total"))
        cand.append((t, rank, r))
    cand.sort(key=lambda x: (x[0], x[1]))
    picked, total = [], 0.0
    for t, _rank, r in cand:
        if total >= target:
            break
        picked.append((t, r))
        total += shelf_of(r)
    return picked, total


def listed_today_amount(csv_dir=CSV_DIR, today=None):
    """その日に作った入稿CSVの金額合計 (US価格)。純関数寄り, test可。"""
    today = today or datetime.date.today()
    stamp = today.strftime("%Y%m%d")
    total = 0.0
    for p in glob.glob(os.path.join(csv_dir, f"*_upload_{stamp}_*.csv")):
        if p.endswith((".bak", ".json")):
            continue
        try:
            with open(p, encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    total += _f(row.get("*StartPrice") or row.get("StartPrice"))
        except OSError:
            continue
    return total


def _load():
    """(funnel の US 行, itemID→ミラー込み棚額) を返す。"""
    done = CE.load_done()
    fr = [r for r in csv.DictReader(
        open(sorted(glob.glob(os.path.join(LF.OUT_DIR, "funnel_*.csv")))[-1],
             encoding="utf-8-sig")) if r["item_id"] not in done]
    mir = collections.defaultdict(float)
    reps = sorted(glob.glob(REPORT_GLOB, recursive=True))
    if reps:
        seen = set()
        for r in csv.DictReader(open(reps[-1], encoding="utf-8-sig", errors="replace")):
            i = (r.get("Item number") or "").strip()
            if not i or i in done or i in seen:
                continue
            seen.add(i)
            if (r.get("Listing site") or "").strip() != "US":
                mir[LF._title_key(r.get("Title"))] += _f(r.get("Current price"))
    def shelf_of(row):
        return _f(row.get("price")) + mir.get(LF._title_key(row.get("title")), 0.0)
    return fr, shelf_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", action="store_true", help="eBay に End を送る")
    ap.add_argument("--amount", type=float, default=None, help="目標額を直接指定")
    ap.add_argument("--ratio", type=float, default=RATIO)
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass

    rows, shelf_of = _load()
    listed = listed_today_amount()
    target = a.amount if a.amount is not None else listed * a.ratio
    print(f"今日の出品額 ${listed:,.0f} × {a.ratio} = **落とす目標 ${target:,.0f}**")
    print(f"対象: 仕入元が死んでいるもの → 出品{MIN_AGE_DAYS}日超で未販売のものを アクセスの少ない順")
    if target <= 0:
        print("  今日はまだ出品していないので、落とす分もありません")
        return 0
    picked, total = pick(rows, target, shelf_of)
    if not picked:
        print("  落とせる候補がありません")
        return 0
    byt = collections.Counter()
    byv = collections.Counter()
    for t, r in picked:
        byt[t] += 1
        byv[t] += shelf_of(r)
    print(f"\n選定 {len(picked)}件 / 空く額 ${total:,.0f}")
    for t in sorted(byt):
        print(f"   {TIER_NAME[t]:26s}{byt[t]:4d}件 ${byv[t]:9,.0f}")
    print("\n  上位10件:")
    for t, r in picked[:10]:
        print(f"   [{t}] ${shelf_of(r):8,.0f} 表示{_f(r.get('impr_total')):6.0f} "
              f"watch{_f(r.get('watch')):.0f}  {r['item_id']}  {(r.get('title') or '')[:44]}")
    if not a.end:
        print("\n  → 実際に落とすには --end")
        return 0
    # ★送る直前に eBay の実状態を1件ずつ見る (誤取下げ防止)。
    #   ・既に終了している → 済みリストに入れて外す
    #   ・在庫切れで選んだのに **補充されていた** → 外す (①だけに効く。②③は在庫ありで選んでいる)
    #   ・状態が取れない → 外す (fail-closed。取得失敗を破壊側に倒さない)
    sys.path.insert(0, os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
    try:
        from ebay_getitem_images import fetch_listing_qty, fetch_listing_status
    except Exception as e:                                     # noqa: BLE001
        print(f"⛔ 在庫検証モジュールを読めないので中止します (fail-closed): {e}")
        return 1
    print(f"\n  現eBay状態を実機確認中 ({len(picked)}件)...", flush=True)
    keep, dropped = [], collections.Counter()
    for t, r in picked:
        iid = r["item_id"]
        try:
            st = fetch_listing_status(iid)
        except Exception:                                      # noqa: BLE001
            st = None
        if st is None:
            dropped["状態が取れない"] += 1
            continue
        if st != "Active":
            dropped["既に終了"] += 1
            CE.remember_done([iid])
            continue
        try:
            q = fetch_listing_qty(iid)
        except Exception:                                      # noqa: BLE001
            q = None
        if q is None:
            dropped["在庫が取れない"] += 1
            continue
        if t == TIER_OOS and q > 0:
            dropped["在庫が復活していた"] += 1
            continue
        keep.append((t, r))
    for k, n in dropped.items():
        print(f"   ⏭ 除外 {k}: {n}件")
    if not keep:
        print("  実機確認後の対象なし。処理終了。")
        return 0
    picked = keep
    print(f"  → End 確定 = {len(picked)}件 (${sum(shelf_of(r) for _t, r in picked):,.0f})")
    ids = [r["item_id"] for _t, r in picked]
    ok, ng = CE.end_on_ebay([{"item_id": i} for i in ids])
    CE.remember_done(ok)
    print(f"\n▶ eBay に送信 → 成功 {len(ok)}件 / {len(ids)}件")
    for iid, msg in ng[:8]:
        print(f"   ⚠ {iid}: {msg}")
    if ok:
        import cull_writeback as CW
        n = CW.apply(set(ok), commit=True)
        print(f"▶ スプシ更新 → {n}行 (B列を空 + Q列に印)")
        try:
            import oos_status_refresh as OS
            OS.main_commit()
        except Exception as e:                                 # noqa: BLE001
            print(f"   ⚠ 在庫なしシートの状態列は次回に持ち越します: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
