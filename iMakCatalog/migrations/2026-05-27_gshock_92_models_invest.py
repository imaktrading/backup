#!/usr/bin/env python3
"""G-shock 未登録 92 models 追加投入.

依頼: 2026-05-27_catalog_gshock_models_addition_implementation.md (= 案 B 採用、 G-shock 先)
source: 重複くん list CSV = C:/dev/iMak_data/dedupe/requests/2026-05-27_gshock_76_models_full_list.csv
        (= 92 unique models 含む、 想定 76 から +16)

手段: 既存 `iMakCatalog/scrapers/gshock.py update_single_model()` 流用 + URL fallback 追加対応済.

実行:
    python migrations/2026-05-27_gshock_92_models_invest.py --probe         # CSV から model list 抽出
    python migrations/2026-05-27_gshock_92_models_invest.py --sanity        # 先頭 3 models のみ
    python migrations/2026-05-27_gshock_92_models_invest.py                 # 本走 全 92 models
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))

CSV_PATH = "C:/dev/iMak_data/dedupe/requests/2026-05-27_gshock_76_models_full_list.csv"


def load_models() -> list[str]:
    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [r["model"].strip() for r in reader if r.get("model", "").strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true", help="model list 抽出のみ (DB 触らず)")
    p.add_argument("--sanity", action="store_true", help="先頭 3 models のみ投入")
    p.add_argument("--limit", type=int, help="先頭 N models のみ")
    p.add_argument("--start", type=int, default=0, help="先頭 N skip (= resume 用)")
    args = p.parse_args()

    models = load_models()
    print(f"load: {len(models)} models from CSV")
    print()

    if args.probe:
        # AW / G- / non-G の分類
        aw = [m for m in models if m.startswith("AW")]
        g = [m for m in models if m.startswith("G")]
        other = [m for m in models if not m.startswith("AW") and not m.startswith("G")]
        print(f"  AW 系 (fallback 候補): {len(aw)}")
        print(f"  G 系: {len(g)}")
        print(f"  other: {len(other)}: {other}")
        return

    # 1. sanity / limit / start で範囲絞り込み
    if args.sanity:
        target_models = models[:3]
    elif args.limit:
        target_models = models[args.start: args.start + args.limit]
    else:
        target_models = models[args.start:]

    print(f"target: {len(target_models)} models (= range {args.start}..)")

    # 2. import + driver 起動 (= 遅延)
    import gshock  # type: ignore

    driver = gshock._start_driver()
    success, failed, scrape_results = 0, [], []
    started_at = time.time()
    try:
        for i, m in enumerate(target_models, start=1):
            try:
                ok = gshock.update_single_model(m, driver=driver)
                if ok:
                    success += 1
                    scrape_results.append((m, "OK"))
                else:
                    failed.append(m)
                    scrape_results.append((m, "FAIL"))
            except Exception as ex:
                failed.append((m, type(ex).__name__, str(ex)))
                scrape_results.append((m, f"EXCEPTION: {ex}"))
            time.sleep(2)  # polite delay
            if i % 10 == 0:
                elapsed = int(time.time() - started_at)
                print(f"\n  ... {i}/{len(target_models)} done | OK={success} FAIL={len(failed)} "
                      f"elapsed={elapsed}s\n", flush=True)
    finally:
        driver.quit()

    elapsed = int(time.time() - started_at)
    print(f"\n=== 完了 ===")
    print(f"  OK   : {success}")
    print(f"  FAIL : {len(failed)}")
    print(f"  total: {len(target_models)}")
    print(f"  elapsed: {elapsed} sec (= {elapsed/60:.1f} min)")

    if failed:
        print(f"\n=== failed models ===")
        for f in failed:
            print(f"  {f}")

    # 結果 log を CSV に書き出し (= 次回 retry 用)
    log_csv = Path("C:/dev/iMak_data/catalog/_gshock_92_invest_log.csv")
    with open(log_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "status"])
        for m, s in scrape_results:
            w.writerow([m, s])
    print(f"\nlog → {log_csv}")


if __name__ == "__main__":
    main()
