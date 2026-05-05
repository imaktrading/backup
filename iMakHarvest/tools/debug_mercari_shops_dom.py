"""debug_mercari_shops_dom - メルカリいいねページの Shops 商品 DOM 構造を調査.

Phase 1b 実装前の selector 確認用:
  - /mypage/favorites に通常 Mercari と Shops が混在するか
  - Shops anchor の data-testid が通常品と同じか別か
  - Shops 商品 URL slug の形式確認
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import mercari_likes  # noqa: E402

LIKES_URL = "https://jp.mercari.com/mypage/favorites"
SCROLL_COUNT = 10
SCROLL_SLEEP = 1.5


def main() -> int:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    print(f"--- DOM debug: {LIKES_URL} ---")
    driver = mercari_likes.create_driver(headless=False)
    try:
        driver.get(LIKES_URL)
        # ハイドレーション + 全件ロード (無限スクロール)
        time.sleep(8)
        for i in range(SCROLL_COUNT):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(SCROLL_SLEEP)

        # page_source 保存
        out_dir = Path(__file__).resolve().parent.parent / "debug"
        out_dir.mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_html = out_dir / f"shops_dom_{ts}.html"
        out_html.write_text(driver.page_source or "", encoding="utf-8")
        print(f"  HTML dump: {out_html}\n")

        # 全 a タグ分析
        all_anchors = driver.find_elements(By.CSS_SELECTOR, "a")
        regular_count = 0
        shops_count = 0
        regular_testids: Counter = Counter()
        shops_testids: Counter = Counter()
        shops_samples: list[tuple[str, str]] = []
        regular_samples: list[tuple[str, str]] = []

        for a in all_anchors:
            try:
                href = a.get_attribute("href") or ""
            except Exception:
                continue
            try:
                tid = a.get_attribute("data-testid") or "(none)"
            except Exception:
                tid = "(none)"

            if "/items?/" in href or "/item/" in href:
                regular_count += 1
                regular_testids[tid] += 1
                if len(regular_samples) < 3:
                    regular_samples.append((tid, href[:90]))
            elif "/shops/product/" in href:
                shops_count += 1
                shops_testids[tid] += 1
                if len(shops_samples) < 5:
                    shops_samples.append((tid, href[:120]))

        print(f"=== anchor 分布 ===")
        print(f"  通常 Mercari (/item/): {regular_count}")
        print(f"  Mercari Shops (/shops/product/): {shops_count}")
        print()

        print(f"=== 通常 Mercari anchor data-testid 分布 ===")
        for tid, cnt in regular_testids.most_common():
            print(f"  {cnt:>4}  {tid!r}")
        print()
        print(f"  サンプル (上位 3 件):")
        for tid, href in regular_samples:
            print(f"    testid={tid!r}, href={href}")
        print()

        print(f"=== Shops anchor data-testid 分布 ===")
        for tid, cnt in shops_testids.most_common():
            print(f"  {cnt:>4}  {tid!r}")
        print()
        print(f"  サンプル (上位 5 件):")
        for tid, href in shops_samples:
            print(f"    testid={tid!r}, href={href}")

        # Shops anchor の親要素 1 つだけ outerHTML で構造確認
        print()
        print(f"=== Shops anchor 1 件の親構造 ===")
        try:
            shops_first = driver.find_element(By.CSS_SELECTOR, "a[href*='/shops/product/']")
            outer = shops_first.get_attribute("outerHTML") or ""
            print(f"  outerHTML[:500]:")
            print(f"    {outer[:500]}")
            try:
                parent = shops_first.find_element(By.XPATH, "..")
                parent_outer = parent.get_attribute("outerHTML") or ""
                print(f"  親 outerHTML[:500]:")
                print(f"    {parent_outer[:500]}")
            except Exception:
                pass
        except Exception as e:
            print(f"  (Shops anchor が 1 件も無い: {type(e).__name__})")

    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
