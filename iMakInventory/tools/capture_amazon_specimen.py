"""capture_amazon_specimen - 特定 ASIN の rendered DOM を採取して debug/amazon_specimens/ へ保存.

用途: amazon_scraper が scraper returned None (fail-closed) を返し続ける ASIN の
      buy-box / availability マーカーを調査するため、Selenium レンダリング後の HTML を採取する。
      2026-06-17 の buy-box prose 化調査と同じ検体駆動手順。

⚠️ 実行制約: amazon_driver は Takaaki さんの手動 login プロファイルを共有する。
   Chrome は同一 user-data-dir の同時起動を許さないため、**cycle 非稼働の窓でのみ実行**すること
   (cycle 中に走らせるとプロファイルロック競合 → 破損リスク)。

使い方:
    python tools/capture_amazon_specimen.py B09C64HBQX row686
    python tools/capture_amazon_specimen.py https://www.amazon.co.jp/dp/B09C64HBQX row686
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.amazon_scraper import (  # noqa: E402
    create_amazon_driver, parse_asin, _detect_seller, _detect_stock,
)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "debug", "amazon_specimens")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/capture_amazon_specimen.py <ASIN|url> [label]")
        return 2

    arg = sys.argv[1].strip()
    label = sys.argv[2].strip() if len(sys.argv) >= 3 else ""

    if arg.startswith("http"):
        url = arg
        asin = parse_asin(url) or "UNKNOWN"
    else:
        asin = arg
        url = f"https://www.amazon.co.jp/dp/{asin}"

    os.makedirs(OUT_DIR, exist_ok=True)
    fname = f"{label + '_' if label else ''}{asin}.html"
    out_path = os.path.normpath(os.path.join(OUT_DIR, fname))

    print(f"[capture] url={url}")
    driver = create_amazon_driver(headless=True, use_login_profile=True)
    try:
        driver.get(url)
        html = driver.page_source
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[capture] saved {len(html):,} bytes -> {out_path}")

    # 採取した DOM を現行ロジックに通し、 なぜ None になるか即診断
    seller, seller_reason = _detect_seller(html)
    stock, stock_reason = _detect_stock(html, rendered=True)
    print(f"[diagnose] seller={seller!r} ({seller_reason})")
    print(f"[diagnose] stock={stock!r} ({stock_reason})")
    if seller == "unknown":
        print("[diagnose] => seller unknown が None の原因。 rendered DOM で新 buy-box マーカーを探せ")
    if stock is None:
        print("[diagnose] => stock 判定不能。 availability text を確認せよ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
