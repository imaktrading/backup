"""dry_run_summary - Mercari dry-run + 結果を HQ 検証フォーマットで compact 表示.

通常の `run_harvest.py --dry-run` は image_urls が 60+ URL あって読みづらいので、
HQ 側目視検証用に最小限のフィールドのみ整形して出力する。

使い方:
    python tools/dry_run_summary.py [--max-items N]

出力フィールド:
  - 商品 URL (Mercari)
  - title
  - 商品本体画像 URL (1 枚目、出品者プロフィール画像は除外)
  - S (color)
  - T (size)
  - 色判定 path 推定 (Step1 whitelist / Step2 AI / EMPTY)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import mercari_likes  # noqa: E402
from scrapers.color_vision import extract_katakana_color_from_text  # noqa: E402
from scrapers.mercari_item_detail import _first_product_image_url  # noqa: E402


def _classify_path(color: str, title: str, description: str) -> str:
    """色判定がどの path から出たかを推定 (post-hoc 推定なので 100% ではない)."""
    if not color:
        return "EMPTY (Step1+Step2 失敗)"
    # whitelist 抽出を再実行して、Step1 で取れる色と一致するか確認
    step1_color = extract_katakana_color_from_text(title or "", description or "")
    if step1_color == color:
        return "Step1 (whitelist hit)"
    # Step1 が空 or 違う色 → AI 判定
    return "Step2 (AI fallback)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-items", type=int, default=15)
    ap.add_argument("--load-more", type=int, default=12)
    args = ap.parse_args()

    print(f"=== Mercari dry-run summary (max-items={args.max_items}) ===\n")

    def _progress(cur, total, msg):
        print(f"  [{cur}/{total}] fetching: {msg.split('?')[0]}")

    items = mercari_likes.collect_likes_with_details(
        max_items=args.max_items,
        load_more_clicks=args.load_more,
        headless=False,
        exclude_sold=True,
        progress_callback=_progress,
    )

    print(f"\n--- 結果: {len(items)} 件 ---\n")

    step1_count = 0
    step2_count = 0
    empty_count = 0
    size_filled = 0

    for i, item in enumerate(items, 1):
        title = item.get("title") or ""
        color = item.get("color") or ""
        size = item.get("size") or ""
        description = item.get("description") or ""
        product_img = _first_product_image_url(item.get("image_urls") or [])
        path = _classify_path(color, title, description)

        if path.startswith("Step1"):
            step1_count += 1
        elif path.startswith("Step2"):
            step2_count += 1
        else:
            empty_count += 1
        if size:
            size_filled += 1

        # description 抜粋 (最初の 100 字)
        desc_excerpt = (description or "").replace("\n", " | ")[:100]

        print(f"[{i}] {item['url']}")
        print(f"    title: {title}")
        print(f"    desc : {desc_excerpt}")
        print(f"    img  : {product_img or '(無し)'}")
        print(f"    S(色): {color or '(空)'}")
        print(f"    T(size): {size or '(空)'}")
        print(f"    path : {path}")
        print()

    # サマリ
    total = len(items)
    print("=" * 60)
    print(f"件数: {total}")
    if total > 0:
        print(f"  S(色) 内訳:")
        print(f"    Step1 whitelist hit : {step1_count}/{total} ({step1_count*100//total}%)")
        print(f"    Step2 AI fallback   : {step2_count}/{total} ({step2_count*100//total}%)")
        print(f"    EMPTY               : {empty_count}/{total} ({empty_count*100//total}%)")
        print(f"  T(size) 抽出成功: {size_filled}/{total} ({size_filled*100//total}%)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
