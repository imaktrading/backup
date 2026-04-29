"""ebay_sku_fetcher - eBay listing から SKU + Qty を取得 (独立モジュール).

設計原則:
  - 既存 iMakeBayAPI/check_csv_core.py の load_ebay_keys / get_oauth_token を
    そのまま参照 (本ファイルは薄い wrapper)
  - 認証は app-level (client_credentials)。Browse API のみ呼出可能。

⚠️ Phase 1 の制約 (重要):
  Sell API / Trading API (listing の SKU/Qty を直接取得・変更) には
  user-OAuth (Authorization Code grant) が必要だが、現状未整備。
  本モジュールは現時点では「stub + シート参照」モードで動作する:

    Mode A (stub_from_sheet): SKU シートに既登録の SKU ID + 旧 Qty を信頼し返却
    Mode B (live_browse):     Browse API で listing 表面情報を取得 (Qty 直接取得不可)
    Mode C (live_sell):       未実装 (Sell API ユーザートークン整備後)

  Phase 1 は Mode A 固定。Phase 4 で Mode C に切替予定。

使用例:
    from ebay_sku_fetcher import get_skus_for_listing
    skus = get_skus_for_listing("357401200653", mode="stub_from_sheet")
    # → [{"sku_id": "MK-UT-S-Black", "size": "S", "color": "Black", "ebay_qty": 1}, ...]
"""
from __future__ import annotations

import os
import sys
from typing import Optional

# iMakeBayAPI を sys.path に追加 (load_ebay_keys / get_oauth_token 参照用)
# iMakInventory への graduation 後: ../iMakeBayAPI を辿る
_IMAK_EBAY_API = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "iMakeBayAPI")
)
if os.path.isdir(_IMAK_EBAY_API) and _IMAK_EBAY_API not in sys.path:
    sys.path.insert(0, _IMAK_EBAY_API)


# ============================================================================
# Mode A: シート参照 (Phase 1 デフォルト、Sell API 未整備の暫定)
# ============================================================================
def get_skus_from_sheet_cache(listing_id: str, sheet_rows: list) -> list:
    """SKU シートの既存行から指定 listing_id の SKU 情報を抽出.

    Args:
        listing_id: eBay listing ID (例: "357401200653")
        sheet_rows: SKU シートの全行 (headers 除く). 列構成は SKU シートに準ずる:
            [対処要, 対処済, 対処日, listing ID, title,
             eBay SKU ID, サイズ, 色, 仕入元在庫, 仕入元価格, eBay 現Qty, 自動CHK日]

    Returns:
        [
            {"sku_id": "MK-UT-S-Black", "size": "S", "color": "Black",
             "ebay_qty": 1, "row_index": 5},  # row_index = sheet 上の 1-based 行番号
            ...
        ]
    """
    skus = []
    for idx, row in enumerate(sheet_rows, start=2):  # 2-based (header が 1行目)
        if len(row) < 11:
            continue
        if str(row[3]).strip() != str(listing_id).strip():
            continue
        try:
            qty = int(row[10]) if row[10] not in (None, "", "-") else 0
        except (ValueError, TypeError):
            qty = 0
        skus.append({
            "sku_id": (row[5] or "").strip(),
            "size": (row[6] or "").strip(),
            "color": (row[7] or "").strip(),
            "ebay_qty": qty,
            "row_index": idx,
        })
    return skus


# ============================================================================
# Mode B: Browse API (Phase 1 補助、listing 単位の topline 情報のみ)
# ============================================================================
def get_listing_topline(listing_id: str) -> Optional[dict]:
    """eBay Browse API で listing の表面情報のみ取得 (タイトル等).

    Browse API は SKU 単位の Qty を返さないため、SKU 個別の qty 取得には不適。
    listing が active か否かのチェック程度に使う。

    Returns: {"title": str, "is_active": bool, ...} or None on failure
    """
    try:
        from check_csv_core import load_ebay_keys, get_oauth_token  # noqa: PLC0415
    except ImportError:
        return None

    keys = load_ebay_keys()
    app_id = keys.get("AppID")
    app_secret = keys.get("CertID") or keys.get("AppSecret")
    if not (app_id and app_secret):
        return None

    try:
        token = get_oauth_token(app_id, app_secret)
    except Exception as e:
        print(f"  ⚠️ ebay_sku_fetcher: token 取得失敗 {type(e).__name__}: {e}")
        return None

    import requests  # noqa: PLC0415
    url = f"https://api.ebay.com/buy/browse/v1/item/v1|{listing_id}|0"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "title": data.get("title", ""),
            "is_active": data.get("itemAffiliateWebUrl") is not None,
            "estimated_availabilities": data.get("estimatedAvailabilities", []),
            "raw": data,
        }
    except Exception as e:
        print(f"  ⚠️ ebay_sku_fetcher: API 呼出失敗 {type(e).__name__}: {e}")
        return None


# ============================================================================
# 公開 API
# ============================================================================
def get_skus_for_listing(
    listing_id: str,
    mode: str = "stub_from_sheet",
    sheet_rows: Optional[list] = None,
) -> list:
    """指定 listing の SKU 情報を取得 (mode により取得元を切替).

    Args:
        listing_id: eBay listing ID
        mode:       "stub_from_sheet" (Phase 1 デフォルト) | "live_browse" | "live_sell" (未実装)
        sheet_rows: stub_from_sheet モードで必須。SKU シート全行 (header 除く)

    Returns: [{"sku_id", "size", "color", "ebay_qty", "row_index"}, ...]
    """
    if mode == "stub_from_sheet":
        if sheet_rows is None:
            raise ValueError("stub_from_sheet モードでは sheet_rows 必須")
        return get_skus_from_sheet_cache(listing_id, sheet_rows)
    elif mode == "live_browse":
        topline = get_listing_topline(listing_id)
        if not topline:
            return []
        # Browse API では SKU 個別を取れないので、空のスキーマ返す
        return [{"sku_id": "?", "size": "", "color": "", "ebay_qty": -1,
                 "title": topline["title"], "row_index": None}]
    elif mode == "live_sell":
        raise NotImplementedError("live_sell mode (Sell API user OAuth) は Phase 4 で実装予定")
    else:
        raise ValueError(f"未対応 mode: {mode}")


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ebay_sku_fetcher.py <listing_id>")
        sys.exit(1)
    listing_id = sys.argv[1]
    print(f"--- listing {listing_id} (Browse API topline) ---")
    topline = get_listing_topline(listing_id)
    if topline:
        print(f"  Title: {topline['title'][:80]}")
        print(f"  Active: {topline['is_active']}")
        print(f"  Availabilities: {topline['estimated_availabilities']}")
    else:
        print("  (取得失敗)")
