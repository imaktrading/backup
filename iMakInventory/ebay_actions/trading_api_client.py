"""eBay Trading API client (iMakInventory self-contained, HQ 2026-06-03).

監視くんの listing 取得 / 取下げ を Trading API で実装するための薄いクライアント。
他 worktree (iMakRevise) を import しないで完結する (worktree 分離ルール遵守)。

OAuth token は 全 worktree 共有領域 `c:/dev/iMak/iMakeBayAPI/ebay_oauth_token.json`
を参照 (= データ共有領域、 cross-worktree read/write 可)。 expired 時は refresh_token
で自動 refresh + file 更新。

提供 API:
- load_access_token() / refresh_access_token()
- get_my_active_listings() = GetSellerList (= 自セラー active 取得)
- revise_inventory_status(item_id, quantity) = qty 改訂 (= 取下げに使う場合 qty=0)
- end_fixed_price_item(item_id) = listing 終了
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Optional

# 共有領域参照 (= HQ 全 worktree 共有 token)
OAUTH_TOKEN_PATH = Path(r"c:/dev/iMak/iMakeBayAPI/ebay_oauth_token.json")
EBAY_KEYS_PATH = Path(r"c:/dev/iMak/iMakeBayAPI/ebay keys.txt")
TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
OAUTH_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
COMPATIBILITY_LEVEL = "967"
SITE_ID_US = "0"


# ============================================================================
# OAuth token
# ============================================================================
def _load_token_data() -> dict:
    if not OAUTH_TOKEN_PATH.exists():
        raise FileNotFoundError(f"eBay OAuth token が見つかりません: {OAUTH_TOKEN_PATH}")
    return json.loads(OAUTH_TOKEN_PATH.read_text(encoding="utf-8-sig"))


def _save_token_data(data: dict):
    OAUTH_TOKEN_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                 encoding="utf-8")


def _load_app_credentials() -> tuple:
    if not EBAY_KEYS_PATH.exists():
        raise FileNotFoundError(f"eBay keys file が見つかりません: {EBAY_KEYS_PATH}")
    keys = {}
    for line in EBAY_KEYS_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip()
    return keys["AppID"], keys["AppSecret"]


def refresh_access_token() -> str:
    """refresh_token で access_token を再取得し、 token file に保存。 新 access_token を返す."""
    import requests  # noqa: PLC0415
    token_data = _load_token_data()
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("refresh_token が token file に存在しません")
    app_id, app_secret = _load_app_credentials()
    creds = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    scope = token_data.get("scope") or ""
    body = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    if scope:
        body["scope"] = scope
    r = requests.post(OAUTH_TOKEN_URL,
                       headers={"Content-Type": "application/x-www-form-urlencoded",
                                "Authorization": f"Basic {creds}"},
                       data=body, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"OAuth refresh 失敗: HTTP {r.status_code} {r.text}")
    new_data = r.json()
    if "refresh_token" not in new_data:
        new_data["refresh_token"] = refresh_token
        new_data["refresh_token_expires_in"] = token_data.get("refresh_token_expires_in")
    new_data["scope"] = scope
    _save_token_data(new_data)
    return new_data["access_token"]


def load_access_token() -> str:
    return _load_token_data()["access_token"]


def _is_expired_iaf_token_error(xml: str) -> bool:
    return ("21917053" in xml
            or "Expired IAF token" in xml
            or "IAF token supplied is expired" in xml)


# ============================================================================
# XML response 解析
# ============================================================================
def _parse_ack_and_errors(xml: str) -> tuple:
    """Trading API レスポンスから Ack + 最初の ErrorCode/ShortMessage を抽出.

    Returns: (ack, error_code, error_message)
      ack: 'Success' / 'Warning' / 'Failure' / None
    """
    ack_m = re.search(r"<Ack>([^<]+)</Ack>", xml)
    ack = ack_m.group(1) if ack_m else None
    code_m = re.search(r"<ErrorCode>([^<]+)</ErrorCode>", xml)
    msg_m = re.search(r"<ShortMessage>([^<]+)</ShortMessage>", xml)
    return ack, (code_m.group(1) if code_m else None), (msg_m.group(1) if msg_m else None)


# ============================================================================
# Trading API call 共通 wrapper
# ============================================================================
def _call_trading(call_name: str, body_xml: str,
                    access_token: Optional[str] = None,
                    timeout: int = 15,
                    _allow_refresh: bool = True) -> dict:
    """Trading API 共通 call wrapper.

    Returns: {"success": bool, "ack": str|None, "error_code": str|None,
              "error_message": str|None, "raw_xml": str (= 1KB cap)}
    """
    import requests  # noqa: PLC0415
    if access_token is None:
        access_token = load_access_token()
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPATIBILITY_LEVEL,
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-SITEID": SITE_ID_US,
        "X-EBAY-API-IAF-TOKEN": access_token,
        "Content-Type": "text/xml; charset=utf-8",
    }
    try:
        r = requests.post(TRADING_API_URL, headers=headers,
                          data=body_xml.encode("utf-8"), timeout=timeout)
    except Exception as e:
        return {"success": False, "ack": None, "error_code": None,
                "error_message": f"{type(e).__name__}: {e}", "raw_xml": ""}
    if r.status_code != 200:
        return {"success": False, "ack": None, "error_code": str(r.status_code),
                "error_message": f"HTTP {r.status_code}", "raw_xml": r.text[:1000]}
    xml = r.text
    if _allow_refresh and _is_expired_iaf_token_error(xml):
        try:
            new_token = refresh_access_token()
            print(f"  [Trading API] {call_name}: IAF token expired → refresh OK")
            return _call_trading(call_name, body_xml, access_token=new_token,
                                  timeout=timeout, _allow_refresh=False)
        except Exception as e:
            return {"success": False, "ack": None, "error_code": "refresh_failed",
                    "error_message": f"token refresh 失敗: {e}", "raw_xml": xml[:1000]}
    ack, code, msg = _parse_ack_and_errors(xml)
    success = ack in ("Success", "Warning")
    return {"success": success, "ack": ack, "error_code": code,
            "error_message": msg, "raw_xml": xml[:2000]}


# ============================================================================
# 書込み API: ReviseInventoryStatus / EndFixedPriceItem
# ============================================================================
def revise_inventory_status(item_id: str, quantity: int,
                              access_token: Optional[str] = None) -> dict:
    """qty 改訂 (= 取下げに使う場合 quantity=0)。 軽量 API (8000/day quota)。

    既に qty=0 で 変更不要 → ack=Warning + err 21917092 "redundant" (= 冪等 success)。
    listing 不在 → ack=Failure + err 231 "Item not found" (= 既 ended、 上流で safe 扱い)。
    """
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        '<InventoryStatus>'
        f'<ItemID>{item_id}</ItemID>'
        f'<Quantity>{quantity}</Quantity>'
        '</InventoryStatus>'
        '</ReviseInventoryStatusRequest>'
    )
    return _call_trading("ReviseInventoryStatus", body, access_token=access_token)


def revise_inventory_status_variation(item_id: str,
                                        variation_specifics: dict,
                                        quantity: int,
                                        start_price: Optional[float] = None,
                                        access_token: Optional[str] = None) -> dict:
    """variation 単位の qty 改訂 (= 公式監視くん用、 variation listing 対応).

    variation_specifics: {"Sizes": "US M(JP L)", "Color": "BL"} 等の identity dict。
    start_price 指定時は price も同時改訂 (= eBay 仕様: variation level)。
    """
    spec_xml = ""
    for name, value in variation_specifics.items():
        # XML escape 最低限 (= 既存 token は ASCII 想定、 「<>&」 のみ手動 escape)
        n = (str(name).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        v = (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        spec_xml += f"<NameValueList><Name>{n}</Name><Value>{v}</Value></NameValueList>"
    price_xml = (f"<StartPrice>{start_price}</StartPrice>"
                 if start_price is not None else "")
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        '<InventoryStatus>'
        f'<ItemID>{item_id}</ItemID>'
        f'<VariationSpecifics>{spec_xml}</VariationSpecifics>'
        f'<Quantity>{quantity}</Quantity>'
        f'{price_xml}'
        '</InventoryStatus>'
        '</ReviseInventoryStatusRequest>'
    )
    return _call_trading("ReviseInventoryStatus", body, access_token=access_token)


def end_fixed_price_item(item_id: str, ending_reason: str = "NotAvailable",
                          access_token: Optional[str] = None) -> dict:
    """listing 終了 (qty=0 保持と違い、 active から完全消失)。

    補充戻し path を維持したい場合は revise_inventory_status を使う。
    """
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f'<ItemID>{item_id}</ItemID>'
        f'<EndingReason>{ending_reason}</EndingReason>'
        '</EndFixedPriceItemRequest>'
    )
    return _call_trading("EndFixedPriceItem", body, access_token=access_token)


# ============================================================================
# GetSellerList (= 自セラー active listing 一括取得)
# ============================================================================
def _build_getsellerlist_xml(page: int, entries_per_page: int = 200) -> str:
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415
    now = datetime.now(timezone.utc)
    start_from = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_to = (now + timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetSellerListRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f'<EndTimeFrom>{start_from}</EndTimeFrom>'
        f'<EndTimeTo>{end_to}</EndTimeTo>'
        '<GranularityLevel>Coarse</GranularityLevel>'
        '<Pagination>'
        f'<EntriesPerPage>{entries_per_page}</EntriesPerPage>'
        f'<PageNumber>{page}</PageNumber>'
        '</Pagination>'
        '</GetSellerListRequest>'
    )


def get_my_active_listings(access_token: Optional[str] = None,
                             entries_per_page: int = 200,
                             max_pages: int = 50,
                             verbose: bool = False) -> list:
    """GetSellerList paging で自セラー active listing 全件取得.

    Returns: [{"item_id": str, "title": str, "available_qty": int}, ...]
    """
    import requests  # noqa: PLC0415
    if access_token is None:
        access_token = load_access_token()
    headers_base = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPATIBILITY_LEVEL,
        "X-EBAY-API-CALL-NAME": "GetSellerList",
        "X-EBAY-API-SITEID": SITE_ID_US,
        "Content-Type": "text/xml; charset=utf-8",
    }
    all_items: list = []
    for page in range(1, max_pages + 1):
        body = _build_getsellerlist_xml(page, entries_per_page)
        headers = {**headers_base, "X-EBAY-API-IAF-TOKEN": access_token}
        r = requests.post(TRADING_API_URL, headers=headers,
                          data=body.encode("utf-8"), timeout=60)
        xml = r.text
        if _is_expired_iaf_token_error(xml):
            access_token = refresh_access_token()
            continue  # 同 page 再試行
        # 各 <Item> ブロックを抽出
        items_in_page = 0
        for m in re.finditer(r"<Item>(.*?)</Item>", xml, re.DOTALL):
            block = m.group(1)
            iid = re.search(r"<ItemID>([^<]+)</ItemID>", block)
            title = re.search(r"<Title>([^<]+)</Title>", block)
            qa = re.search(r"<QuantityAvailable>(\d+)</QuantityAvailable>", block)
            qt = re.search(r"<Quantity>(\d+)</Quantity>", block)
            sd = re.search(r"<QuantitySold>(\d+)</QuantitySold>", block)
            if not iid:
                continue
            if qa:
                qty = int(qa.group(1))
            elif qt:
                qty = int(qt.group(1)) - (int(sd.group(1)) if sd else 0)
            else:
                qty = 0
            all_items.append({
                "item_id": iid.group(1).strip(),
                "title": title.group(1).strip() if title else "",
                "available_qty": qty,
            })
            items_in_page += 1
        has_more = re.search(r"<HasMoreItems>([^<]+)</HasMoreItems>", xml)
        if verbose:
            print(f"  [GetSellerList] page {page}: {items_in_page} items "
                  f"(total {len(all_items)}, has_more={has_more.group(1) if has_more else '?'})",
                  flush=True)
        if not has_more or has_more.group(1).lower() != "true":
            break
    return all_items
