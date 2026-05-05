"""debug_mercari_shops_detail_dom - Mercari Shops 商品詳細ページ DOM 確認.

通常 Mercari の `mercari_item_detail.fetch_detail` で使う selector が Shops でも
動くかを確認 (流用可否の判定)。

確認 testid:
  - checkout-button-container, checkout-button (在庫判定)
  - 商品の状態 (condition)
  - サイズ (size)
  - name, item-name, display-name (title 候補)
  - price, product-price, item-price (price 候補)
  - description (description)
  - item-image (image)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import mercari_likes  # noqa: E402

TEST_URLS = [
    "https://jp.mercari.com/shops/product/2JNysv3RcsZP37Dt8Zoaof",
]

CHECK_TESTIDS = [
    # 在庫判定
    "checkout-button-container",
    "checkout-button",
    # title
    "name",
    "item-name",
    "display-name",
    # price
    "price",
    "product-price",
    "item-price",
    # condition / size
    "商品の状態",
    "サイズ",
    "商品のサイズ",  # 旧仮定 (Phase 1d-1 時の bug)
    # description / image
    "description",
    "item-image",
]


def main() -> int:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    url = sys.argv[1] if len(sys.argv) > 1 else TEST_URLS[0]
    print(f"--- Shops detail DOM debug: {url} ---")

    driver = mercari_likes.create_driver(headless=False)
    try:
        driver.get(url)
        # ハイドレーション
        for i in range(20):
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text or ""
                if any(kw in body_text for kw in ("商品の状態", "在庫切れ", "購入手続き", "カートに追加")):
                    print(f"  ハイドレーション完了 ({i+1}s)")
                    break
            except Exception:
                pass
            time.sleep(1)

        # page_source 保存
        out_dir = Path(__file__).resolve().parent.parent / "debug"
        out_dir.mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_html = out_dir / f"shops_detail_dom_{ts}.html"
        out_html.write_text(driver.page_source or "", encoding="utf-8")
        print(f"  HTML dump: {out_html}\n")

        print("=== testid 検査 (通常品で使ってる selector の流用可否) ===")
        for tid in CHECK_TESTIDS:
            try:
                elem = driver.find_element(By.CSS_SELECTOR, f'[data-testid="{tid}"]')
                text = (elem.text or "").strip().replace("\n", " | ")[:100]
                tag = elem.tag_name
                print(f"  HIT  {tid:<25} <{tag}> text={text!r}")
            except Exception:
                print(f"  MISS {tid:<25} (not found)")

        print()
        print("=== Shops 固有 testid 候補 ===")
        # shops-* な testid を探索
        all_with_testid = driver.find_elements(By.CSS_SELECTOR, "[data-testid]")
        found_testids = set()
        for el in all_with_testid:
            try:
                tid = el.get_attribute("data-testid") or ""
            except Exception:
                continue
            if tid and tid not in found_testids:
                found_testids.add(tid)
        # 関連しそうなのを抜粋表示
        keywords = ("name", "title", "price", "image", "shop", "product",
                     "description", "condition", "size", "状態", "サイズ", "色",
                     "checkout", "buy", "cart", "purchase")
        relevant = sorted(t for t in found_testids if any(k in t.lower() for k in keywords))
        for t in relevant:
            print(f"  '{t}'")

        print()
        print("=== 画像 selector 候補 (.slick-list, img[src*=mercdn]) ===")
        img_selectors = [
            ".slick-list button mer-item-thumbnail",
            ".slick-list button img",
            "img[data-testid='item-image']",
            "img[src*='static.mercdn.net']",
            "img[src*='shops.mercdn.net']",
            "main img",
        ]
        for sel in img_selectors:
            try:
                imgs = driver.find_elements(By.CSS_SELECTOR, sel)
                if imgs:
                    sample_src = imgs[0].get_attribute("src") or imgs[0].get_attribute("data-src") or ""
                    print(f"  HIT  {sel:<45} {len(imgs)} 件、最初: {sample_src[:80]}")
                else:
                    print(f"  MISS {sel}")
            except Exception:
                print(f"  ERR  {sel}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
