"""診断: mercari セラー 468161152 のスクレイプが URL を取れるか (= 0件の切り分け).

差分OFF(known=None)・auto lazy-load・小 cap で total_seen を見る。
  total_seen>0 → スクレイプ健全 (= 先の0件は差分0=正常)
  total_seen=0 → スクレイプ失敗 (= DOM構造変更/ブロック/ログイン等)
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from scrapers import mercari_seller

SELLER = "468161152"


def _prog(cur, total, msg):
    print(f"  [{cur}/{total}] {msg}", flush=True)


def main():
    print(f"seller={SELLER} auto lazy-load, cap=30, 差分OFF", flush=True)
    res = mercari_seller.collect_seller_with_details(
        seller_id=SELLER,
        headless=False,
        user_limit=30,
        exclude_sold=True,
        progress_callback=_prog,
        wait_for_manual_load=False,
        known_item_ids=None,
    )
    print("=== 結果 ===", flush=True)
    print("total_seen(出現):", res.get("total_seen"), flush=True)
    print("items(取得):", len(res.get("items", [])), flush=True)
    print("skipped_sold:", res.get("skipped_sold"), flush=True)
    print("cap_hit:", res.get("cap_hit"), flush=True)
    if res.get("items"):
        for it in res["items"][:3]:
            print("  sample:", (it.get("url") or "")[:50], "|", (it.get("title") or "")[:30], flush=True)


if __name__ == "__main__":
    main()
