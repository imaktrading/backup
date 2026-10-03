"""メルカリ API 化の POC — 同じ URL を Chrome 版と API 版で読んで突き合わせる (本番は替えない).

2026-10-03 ADV 依頼 watcher_mercari_api_poc (ユーザー: 「TEST して、合格するまでは切り替えない」)。
合格の線: **両方とも読めた件 (有効件数) が 300件以上で、売切の判定が全件一致**。

使い方 (LAPTOP で):
    python tools/mercari_api_poc.py            # 既定 380件
    python tools/mercari_api_poc.py --n 400

巡回と当たらないように:
  - Chrome は本番のメルカリ用プロファイルを **写した別フォルダ** (`chrome_profile_POC`) で動かす。
    同じ PC・同じユーザーなのでログインは写しでも効く。巡回の Chrome 掃除は自分のプロファイルだけを
    殺すので、こちらは巻き込まれない
  - 写す瞬間だけは本番プロファイルが使われていないことが要る。使用中なら写さずに止まる (後でやり直す)
  - スプシ・eBay には何も書かない。結果は decision_log/mercari_api_poc_<日時>.jsonl だけ
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import random
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers import mercari_scraper as ms  # noqa: E402

DECISION_LOG_DIR = ROOT / "decision_log"
POC_PROFILE = ms.CHROME_PROFILE_DIR + "_POC"
SKIP_DIRS = {"Cache", "Code Cache", "GPUCache", "Service Worker", "ShaderCache",
             "GrShaderCache", "GraphiteDawnCache", "DawnCache", "Crashpad", "component_crx_cache"}
# 前回の巡回結果の内訳に合わせて、売切・削除・Shops を厚めに混ぜる (n=330 の時の配分)
MIX = {("item", "ON_SALE"): 110, ("item", "SOLD_OUT"): 55, ("item", "DELETED"): 20,
       ("item", "AUCTION"): 5, ("item", "ERR"): 35, ("shops", "ON_SALE"): 55,
       ("shops", "SOLD_OUT"): 30, ("shops", "DELETED"): 10, ("shops", "ERR"): 10}
CHROME_FAIL_STREAK_LIMIT = 8   # Chrome が続けて読めない = 試験の場が壊れている → 止める


def copy_profile() -> None:
    """本番プロファイルを POC 用に写す。使用中 (ファイルが掴まれている) なら止める."""
    src = Path(ms.CHROME_PROFILE_DIR)
    if not src.is_dir():
        raise SystemExit(f"本番のメルカリ用プロファイルがありません: {src}")
    if Path(POC_PROFILE).exists():
        shutil.rmtree(POC_PROFILE)

    def _ignore(d, names):
        return [n for n in names if n in SKIP_DIRS or n in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")]

    try:
        shutil.copytree(src, POC_PROFILE, ignore=_ignore)
    except shutil.Error as e:
        locked = [x for x in e.args[0] if "Cookies" in str(x) or "Login Data" in str(x)]
        if locked:
            shutil.rmtree(POC_PROFILE, ignore_errors=True)
            raise SystemExit("本番プロファイルが使用中 (巡回が動いている) なので写せません。巡回が終わってからやり直してください")
        # キャッシュ類が写せないのは問題ない


def pick_urls(n: int) -> list:
    files = sorted(glob.glob(str(DECISION_LOG_DIR / "listings_SHEET_*.jsonl")))[-4:]
    buckets = collections.defaultdict(list)
    for f in files:
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            for s in r.get("sub_results") or []:
                if s.get("supplier") != "mercari" or not s.get("url"):
                    continue
                k = ("shops" if "/shops/" in s["url"] else "item", s.get("raw_status") or "ERR")
                buckets[k].append(s["url"])
    scale = n / sum(MIX.values())
    rng = random.Random(20261003)
    urls, seen = [], set()
    for k, want in MIX.items():
        pool = [u for u in dict.fromkeys(buckets.get(k, [])) if u not in seen]
        rng.shuffle(pool)
        for u in pool[: max(1, round(want * scale))]:
            urls.append((k, u))
            seen.add(u)
    # 足りない時は在庫ありの個人出品で埋める
    extra = [u for u in dict.fromkeys(buckets.get(("item", "ON_SALE"), [])) if u not in seen]
    rng.shuffle(extra)
    while len(urls) < n and extra:
        urls.append((("item", "ON_SALE"), extra.pop()))
    return urls


def classify(api, chrome) -> str:
    if chrome is None:
        return "chrome_unreadable"   # 有効件数に数えない
    if api is None:
        return "api_unreadable"      # 本番では Chrome に回る = 有効 (一致扱い) だが別に数える
    if api["in_stock"] != chrome["in_stock"]:
        return "SOLD_MISMATCH"
    if api["in_stock"] and api.get("price_jpy") != chrome.get("price_jpy"):
        return "price_mismatch"
    return "match"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=380)   # 削除済等で API が決めない分を見込んで多めに
    ap.add_argument("--keep-profile", action="store_true", help="前回写した POC プロファイルをそのまま使う")
    args = ap.parse_args()

    ms.MERCARI_API_ENABLED = True   # この試験の中だけ API を使う (本番の既定は触らない)
    if not (args.keep_profile and Path(POC_PROFILE).is_dir()):
        print("本番プロファイルを POC 用に写します…", flush=True)
        copy_profile()
    urls = pick_urls(args.n)
    print(f"対象 {len(urls)} 件", flush=True)

    out_path = DECISION_LOG_DIR / f"mercari_api_poc_{datetime.now():%Y%m%d_%H%M}.jsonl"
    counts = collections.Counter()
    t_api = t_chrome = 0.0
    streak = 0
    driver = ms.create_driver(headless=True, profile_dir=POC_PROFILE)
    stopped = ""
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            for i, (prev, url) in enumerate(urls, 1):
                shops = ms.is_mercari_shops_url(url)
                t = time.time()
                api = ms._detect_via_api(url, shops)
                t_api += time.time() - t
                t = time.time()
                try:
                    chrome = ms._detect_via_selenium(driver, url, shops)
                except Exception as e:  # noqa: BLE001
                    chrome = None
                    print(f"  Chrome 例外: {type(e).__name__}: {str(e)[:80]}", flush=True)
                t_chrome += time.time() - t
                kind = classify(api, chrome)
                counts[kind] += 1
                streak = streak + 1 if kind == "chrome_unreadable" else 0
                rec = {"i": i, "prev": list(prev), "url": url, "kind": kind, "api": api, "chrome": chrome}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                if kind not in ("match", "api_unreadable"):
                    print(f"[{i}/{len(urls)}] {kind} {url} api={api} chrome={chrome}", flush=True)
                elif i % 25 == 0:
                    print(f"[{i}/{len(urls)}] {dict(counts)}", flush=True)
                if streak == CHROME_FAIL_STREAK_LIMIT // 2:
                    print("  Chrome が続けて読めない → Chrome を開き直します", flush=True)
                    try:
                        driver.quit()
                    except Exception:  # noqa: BLE001
                        pass
                    driver = ms.create_driver(headless=True, profile_dir=POC_PROFILE)
                if streak >= CHROME_FAIL_STREAK_LIMIT:
                    stopped = f"Chrome が {streak} 件続けて読めないので中止 (メモリ・ログイン切れ等を確認)"
                    break
                time.sleep(2)
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass

    # 有効件数 = API が判定を出し、Chrome も読めた件 (API が決めずに Chrome へ回した件は別に数える)
    valid = counts["match"] + counts["SOLD_MISMATCH"] + counts["price_mismatch"]
    summary = {"有効件数(API と Chrome の両方が判定した件)": valid, "内訳": dict(counts),
               "売切の食い違い": counts["SOLD_MISMATCH"], "値段ずれ": counts["price_mismatch"],
               "API合計秒": round(t_api, 1), "Chrome合計秒": round(t_chrome, 1),
               "合否": ("合格" if valid >= 300 and counts["SOLD_MISMATCH"] == 0 and not stopped else "不合格/未達"),
               "中止理由": stopped, "記録": str(out_path)}
    print(json.dumps(summary, ensure_ascii=False, indent=1), flush=True)
    return 0 if summary["合否"] == "合格" else 1


if __name__ == "__main__":
    raise SystemExit(main())
