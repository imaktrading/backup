"""debug_mercari_size_dom - Mercari 商品ページの「商品のサイズ」DOM 構造を調査.

mercari_item_detail._extract_size の selector が当たらない件の調査用。
URL を 1 つ開き、「サイズ」を含む要素を全パターンで列挙する。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import mercari_likes  # noqa: E402

URLS = [
    "https://jp.mercari.com/item/m66875521479",
]


def main() -> int:
    from selenium.webdriver.common.by import By  # noqa: PLC0415

    url = sys.argv[1] if len(sys.argv) > 1 else URLS[0]
    print(f"--- DOM debug: {url} ---")

    driver = mercari_likes.create_driver(headless=False)
    try:
        driver.get(url)
        # ハイドレーション待ち
        for i in range(20):
            try:
                body_text = driver.find_element(By.TAG_NAME, "body").text or ""
                if "商品のサイズ" in body_text or "商品の状態" in body_text:
                    print(f"  ハイドレーション完了 ({i+1}s)")
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            print("  ⚠️ ハイドレーション完了せず (20s)")

        # page_source を保存
        out_dir = Path(__file__).resolve().parent.parent / "debug"
        out_dir.mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = out_dir / f"size_dom_{ts}.html"
        out.write_text(driver.page_source or "", encoding="utf-8")
        print(f"  HTML dump: {out}")

        # 「サイズ」を含む要素を全列挙
        print("\n=== サイズ関連要素 (data-testid 含む) ===")
        for elem in driver.find_elements(By.CSS_SELECTOR, "[data-testid*='ize'], [data-testid*='サイズ']"):
            try:
                tag = elem.tag_name
                testid = elem.get_attribute("data-testid") or ""
                text = (elem.text or "").strip().replace("\n", " | ")[:120]
                print(f"  <{tag} data-testid={testid!r}>{text}</{tag}>")
            except Exception as e:
                print(f"  (err: {e})")

        # 「商品のサイズ」テキストを持つ要素
        print("\n=== text=='商品のサイズ' を持つ要素 ===")
        for tag in ("dt", "dd", "span", "div", "p", "th", "td"):
            for elem in driver.find_elements(By.TAG_NAME, tag):
                try:
                    text = (elem.text or "").strip()
                    if text == "商品のサイズ":
                        # この要素の親 / 兄弟 / 直後を列挙
                        outer = elem.get_attribute("outerHTML") or ""
                        print(f"  found tag=<{tag}>: {outer[:200]}")
                        # 親要素の outerHTML (最大 500 chars)
                        try:
                            parent = elem.find_element(By.XPATH, "..")
                            parent_html = parent.get_attribute("outerHTML") or ""
                            print(f"  親の outerHTML[:500]:")
                            print(f"    {parent_html[:500]}")
                        except Exception:
                            pass
                except Exception:
                    pass

        # 既存 selector が拾えない理由を診断
        print("\n=== 既存 selector の動作 ===")
        for sel in (
            'span[data-testid="商品のサイズ"]',
            '[data-testid="商品のサイズ"]',
            'span[data-testid="商品の状態"]',  # 比較用 (動いてる方)
        ):
            try:
                elem = driver.find_element(By.CSS_SELECTOR, sel)
                text = (elem.text or "").strip()
                print(f"  ✓ {sel}: {text[:60]!r}")
            except Exception as e:
                print(f"  ✗ {sel}: {type(e).__name__}")

    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
