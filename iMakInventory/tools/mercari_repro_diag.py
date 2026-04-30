"""mercari_repro_diag - 14:50 cycle で None を返した URL を単体で再 fetch.

目的: scraper returned None の真因を切り分ける (anti-bot / driver 死亡 / 一時障害)。

usage:
    python tools/mercari_repro_diag.py
    python tools/mercari_repro_diag.py --listings-log decision_log/listings_TEST_PARALLEL_20260430_145301.jsonl

出力:
- 各 URL に対して driver で fetch を試行
- 結果:
  - 成功 (status / in_stock 取得) → 一時障害 (cycle 当時の問題は解消済)
  - None 返却 → anti-bot or サーバ側問題、page snapshot 確認推奨
- page_snapshot を decision_log/mercari_repro_<ts>.jsonl に保存:
  - current_url / title / body_text(冒頭400文字) / detected_signals
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scrapers.mercari_scraper import (  # noqa: E402
    fetch_product_inventory, create_driver,
)


def diagnose(urls: list[str], headless: bool = True) -> dict:
    summary = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "url_count": len(urls),
        "results": [],
        "verdict": "unknown",
    }
    print(f"=== mercari driver 起動 (headless={headless}) ===")
    t0 = time.time()
    driver = create_driver(headless=headless)
    print(f"driver up in {time.time()-t0:.1f}s")

    success = 0
    none_returned = 0
    try:
        for u in urls:
            entry = {"url": u}
            print()
            print(f"--- {u} ---")
            t0 = time.time()
            try:
                info = fetch_product_inventory(u, driver=driver)
                elapsed = time.time() - t0
                entry["elapsed_sec"] = round(elapsed, 1)
                if info is None:
                    none_returned += 1
                    entry["status"] = "None"
                    print(f"  ❌ None 返却 ({elapsed:.1f}s)")
                    # page snapshot
                    try:
                        entry["current_url"] = driver.current_url
                        entry["page_title"] = driver.title
                        body_text = driver.execute_script(
                            "return document.body ? document.body.innerText.substring(0, 400) : '';"
                        )
                        entry["body_text_400"] = body_text
                        # bot block 兆候の検出
                        bot_signals = []
                        for kw in ["bot", "blocked", "403", "Forbidden", "Captcha", "Access Denied",
                                   "認証", "ロボット", "アクセスが拒否"]:
                            if kw.lower() in (body_text or "").lower():
                                bot_signals.append(kw)
                        entry["bot_block_signals"] = bot_signals
                        if bot_signals:
                            print(f"  ⚠️ bot 疑い signals: {bot_signals}")
                        # checkout-button-container 探索
                        try:
                            from selenium.webdriver.common.by import By  # noqa: PLC0415
                            container = driver.find_element(
                                By.CSS_SELECTOR, '[data-testid="checkout-button-container"]'
                            )
                            entry["checkout_container_found"] = True
                            entry["container_html_500"] = (container.get_attribute("outerHTML") or "")[:500]
                            print(f"  📋 checkout-button-container 発見 (内容は下記参照)")
                        except Exception:
                            entry["checkout_container_found"] = False
                            print(f"  📋 checkout-button-container 不在")
                        print(f"  current_url: {entry['current_url']}")
                        print(f"  title: {entry['page_title']!r}")
                        print(f"  body[:400]: {body_text!r}")
                    except Exception as e:
                        entry["snapshot_err"] = f"{type(e).__name__}: {e}"
                else:
                    success += 1
                    sku = (info.get("skus") or [{}])[0]
                    entry["status"] = info.get("status", "?")
                    entry["in_stock"] = sku.get("in_stock")
                    entry["price_jpy"] = sku.get("price_jpy")
                    print(f"  ✅ 成功 ({elapsed:.1f}s) status={entry['status']} in_stock={entry['in_stock']}")
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
                print(f"  💥 例外: {entry['error']}")
            summary["results"].append(entry)
            time.sleep(2)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if success == len(urls):
        summary["verdict"] = "all_recovered_likely_transient"
    elif none_returned == len(urls):
        if any(r.get("bot_block_signals") for r in summary["results"]):
            summary["verdict"] = "all_failed_anti_bot_suspected"
        else:
            summary["verdict"] = "all_failed_dom_or_server_issue"
    else:
        summary["verdict"] = "partial_recovery"
    summary["success_count"] = success
    summary["none_returned"] = none_returned

    return summary


def extract_failed_urls_from_log(log_path: Path) -> list[str]:
    urls = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("error") and r.get("supplier") == "mercari":
                u = r.get("url")
                if u:
                    urls.append(u)
    return urls


def main():
    parser = argparse.ArgumentParser(description="Mercari error 真因究明 diag (Phase 9 拡張 C)")
    parser.add_argument(
        "--listings-log", type=Path,
        default=ROOT / "decision_log" / "listings_TEST_PARALLEL_20260430_145301.jsonl",
        help="対象 listings ログ (default: 14:50 cycle のもの)",
    )
    parser.add_argument("--max", type=int, default=5,
                        help="再 fetch する URL 数上限 (default: 5)")
    parser.add_argument("--no-headless", action="store_true", help="headless 無効化 (デバッグ表示)")
    args = parser.parse_args()

    if not args.listings_log.exists():
        print(f"❌ listings log 不在: {args.listings_log}")
        sys.exit(1)

    urls = extract_failed_urls_from_log(args.listings_log)
    if not urls:
        print(f"⚠️ failed mercari URL が見つからない (log: {args.listings_log})")
        sys.exit(0)
    urls = urls[:args.max]
    print(f"対象 URL: {len(urls)} 件 (log {args.listings_log.name} から抽出)")
    summary = diagnose(urls, headless=not args.no_headless)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = ROOT / "decision_log" / f"mercari_repro_{ts}.jsonl"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"VERDICT: {summary['verdict']}")
    print(f"  success: {summary['success_count']} / none: {summary['none_returned']} / total: {summary['url_count']}")
    print(f"saved: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
