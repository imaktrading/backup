"""PSA 補URL 640本の値段・在庫を1回だけ見る (ADV 依頼 2026-09-21_hoju_price_recheck).

- シートは一切書かない。結果は依頼 dir の _result.csv に追記 (途中再開可)
- 巡回と当たらない時だけ回す: cycle lock がある / 監視くんのタスクが45分以内に始まる → 待つ
  (メルカリは巡回と同じ chrome profile を使うため。スニダンは HTTP のみだが同じ扱いで統一)
- 判定不能は「判定不能」のまま返す (売り切れに倒さない)
"""
from __future__ import annotations

import csv
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrapers import mercari_scraper, snkrdunk_scraper  # noqa: E402

REQ = Path("C:/dev/iMak_data/inventory/requests")
SRC = REQ / "2026-09-21_hoju_price_recheck_urls.csv"
OUT = REQ / "2026-09-21_hoju_price_recheck_result.csv"
LOCK_DIR = ROOT / "decision_log"
GUARD_MIN = 45
PACE_SEC = 4
# chrome を使わないタスク (eBay API / 集計のみ) は当たっても害が無いので待たない
NO_CHROME_TASKS = ("DrainTakedowns", "ReverseAudit", "StaleZeroReport")


def _log(msg: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def _next_task_start() -> datetime | None:
    """監視くんのタスク (iMakInventory_*) で一番近い次回起動."""
    try:
        out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"],
                             capture_output=True, text=True, encoding="cp932",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return datetime.now()   # 分からない時は「すぐ始まる」扱い = 待つ
    best = None
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) < 2 or "iMakInventory" not in cols[0]:
            continue
        if any(k in cols[0] for k in NO_CHROME_TASKS):
            continue
        try:
            t = datetime.strptime(cols[1], "%Y/%m/%d %H:%M:%S")
        except ValueError:
            continue
        if best is None or t < best:
            best = t
    return best


def _blocked() -> str | None:
    locks = list(LOCK_DIR.glob(".cycle*.lock"))
    if locks:
        return f"巡回中 ({', '.join(p.name for p in locks)})"
    nxt = _next_task_start()
    if nxt and nxt - datetime.now() < timedelta(minutes=GUARD_MIN):
        return f"次のタスクが {nxt:%H:%M} に開始"
    return None


def _verdict(res: dict | None) -> tuple[str, str]:
    """scraper の in_stock で判定 (status 名はサイトごとに違う: mercari=ON_SALE / snkrdunk=IN_STOCK).
    メルカリのオークション出品は定価で買えるか判らないので判定不能."""
    if not res or res.get("status") in ("AUCTION", "UNKNOWN"):
        return "判定不能", ""
    sku = (res.get("skus") or [{}])[0]
    if sku.get("in_stock") is True:
        price = sku.get("price_jpy")
        return "買える", "" if price is None else str(price)
    if sku.get("in_stock") is False:
        return "売り切れ", ""
    return "判定不能", ""


def main() -> None:
    rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
    done = set()
    if OUT.exists():
        done = {r["url"] for r in csv.DictReader(OUT.open(encoding="utf-8-sig"))}
    else:
        with OUT.open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(["url", "状態", "値段", "確認日時"])
    todo = [r["url"] for r in rows if r["url"] not in done]
    _log(f"対象 {len(rows)} / 済 {len(done)} / 残り {len(todo)}")

    driver = None
    try:
        for i, url in enumerate(todo, 1):
            while (why := _blocked()):
                if driver:
                    driver.quit()
                    driver = None
                _log(f"待機: {why}")
                time.sleep(300)
            try:
                if "mercari" in url:
                    if driver is None:
                        driver = mercari_scraper.create_driver(headless=True)
                    res = mercari_scraper.fetch_product_inventory(url, driver=driver)
                else:
                    res = snkrdunk_scraper.fetch_product_inventory(url)
            except Exception as e:  # noqa: BLE001
                _log(f"例外 {url}: {e!r}")
                res = None
                if driver:
                    try:
                        driver.quit()
                    except Exception:  # noqa: BLE001
                        pass
                    driver = None
            state, price = _verdict(res)
            with OUT.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([url, state, price, datetime.now().isoformat(timespec="seconds")])
            if i % 20 == 0:
                _log(f"{i}/{len(todo)}")
            time.sleep(PACE_SEC)
    finally:
        if driver:
            driver.quit()
    _log("完了")


if __name__ == "__main__":
    main()
