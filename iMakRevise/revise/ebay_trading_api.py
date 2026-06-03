"""ebay_trading_api.py - eBay Trading API GetItem (旧 Policy 名 取得用).

最低限の実装: ItemID → ShippingProfileName のみ。
OAuth token は `c:\\dev\\iMak\\iMakeBayAPI\\ebay_oauth_token.json` (HQ 共有) を参照。
expired 時は refresh_token で 自動再取得 + token file 更新。

注意:
- Trading API は legacy SOAP/XML、新規実装は本来非推奨
- だが seller 自身の listing 詳細 (= SellerProfiles) は Trading API が最も直接的
- API quota: seller 自身の listing は消費ゼロ
- レート: 1 ItemID ≒ 1.5秒、normal cycle 規模 (19件) なら ~30秒
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Optional

OAUTH_TOKEN_PATH = Path(r"c:/dev/iMak/iMakeBayAPI/ebay_oauth_token.json")
EBAY_KEYS_PATH = Path(r"c:/dev/iMak/iMakeBayAPI/ebay keys.txt")
TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
OAUTH_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
COMPATIBILITY_LEVEL = "967"
SITE_ID_US = "0"


def _load_token_data() -> dict:
    if not OAUTH_TOKEN_PATH.exists():
        raise FileNotFoundError(f"eBay OAuth token が見つかりません: {OAUTH_TOKEN_PATH}")
    return json.loads(OAUTH_TOKEN_PATH.read_text(encoding="utf-8-sig"))


def _save_token_data(data: dict):
    """token data を file に書込 (= HQ 共有 file、auth refresh artifact なので例外的 cross-worktree write)."""
    OAUTH_TOKEN_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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
    """refresh_token で access_token を再取得し、token file に保存。返り値は新 access_token."""
    import requests
    token_data = _load_token_data()
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("refresh_token が token file に存在しません")
    app_id, app_secret = _load_app_credentials()
    creds = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    # 元の scope を引き継ぐ (= 不明なら eBay 側が default 適用)
    scope = token_data.get("scope") or ""
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if scope:
        body["scope"] = scope
    r = requests.post(
        OAUTH_TOKEN_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {creds}",
        },
        data=body,
        timeout=10,
    )
    if r.status_code != 200:
        raise RuntimeError(f"OAuth refresh 失敗: HTTP {r.status_code} {r.text}")
    new_data = r.json()
    # refresh_token は維持 (= レスポンスに含まれない場合)
    if "refresh_token" not in new_data:
        new_data["refresh_token"] = refresh_token
        new_data["refresh_token_expires_in"] = token_data.get("refresh_token_expires_in")
    new_data["scope"] = scope
    _save_token_data(new_data)
    return new_data["access_token"]


def load_access_token(auto_refresh: bool = True) -> str:
    """token を読込。expired (= IAF Error) 時は auto_refresh=True なら自動 refresh."""
    return _load_token_data()["access_token"]


def _build_getitem_xml(item_id: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f'<ItemID>{item_id}</ItemID>'
        '<DetailLevel>ReturnAll</DetailLevel>'
        '<IncludeItemSpecifics>false</IncludeItemSpecifics>'
        '</GetItemRequest>'
    )


def _parse_shipping_profile_name(xml: str) -> Optional[str]:
    """response XML から ShippingProfileName を抜く. なければ None."""
    m = re.search(r"<ShippingProfileName>(.*?)</ShippingProfileName>", xml)
    return m.group(1) if m else None


def _parse_current_price(xml: str) -> Optional[float]:
    """response XML から CurrentPrice を抜く (= BuyItNowPrice or StartPrice).

    Trading API は <ConvertedCurrentPrice currencyID="USD">XX.XX</ConvertedCurrentPrice>
    を返す (= site 通貨統一).
    """
    m = re.search(r'<ConvertedCurrentPrice[^>]*>([0-9.]+)</ConvertedCurrentPrice>', xml)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _is_expired_iaf_token_error(xml: str) -> bool:
    return "21917053" in xml or "Expired IAF token" in xml or "IAF token supplied is expired" in xml


def get_item(item_id: str, access_token: Optional[str] = None, timeout: int = 10,
              _allow_refresh: bool = True) -> dict:
    """ItemID → {"shipping_profile_name": str | None, "current_price_usd": float | None}.

    エラー時は dict["error"] にメッセージを格納し、他フィールドは None。
    IAF token expired (21917053) を検出したら refresh + 1 回 retry。
    """
    import requests  # 遅延 import (= test で mock しやすい)

    if access_token is None:
        access_token = load_access_token()

    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPATIBILITY_LEVEL,
        "X-EBAY-API-CALL-NAME": "GetItem",
        "X-EBAY-API-SITEID": SITE_ID_US,
        "X-EBAY-API-IAF-TOKEN": access_token,
        "Content-Type": "text/xml; charset=utf-8",
    }
    body = _build_getitem_xml(item_id)

    try:
        r = requests.post(TRADING_API_URL, headers=headers, data=body.encode("utf-8"),
                          timeout=timeout)
    except Exception as e:
        return {"shipping_profile_name": None, "current_price_usd": None,
                "error": f"{type(e).__name__}: {e}"}

    if r.status_code != 200:
        return {"shipping_profile_name": None, "current_price_usd": None,
                "error": f"HTTP {r.status_code}"}

    xml = r.text
    # 期限切れ自動 refresh + 1 回だけ retry
    if _allow_refresh and _is_expired_iaf_token_error(xml):
        try:
            new_token = refresh_access_token()
            print(f"  [Trading API] IAF token expired → refresh OK")
            return get_item(item_id, access_token=new_token, timeout=timeout,
                            _allow_refresh=False)
        except Exception as e:
            return {"shipping_profile_name": None, "current_price_usd": None,
                    "error": f"token refresh 失敗: {e}"}

    return {
        "shipping_profile_name": _parse_shipping_profile_name(xml),
        "current_price_usd": _parse_current_price(xml),
        "error": None,
    }


def get_items_batch(item_ids: list, access_token: Optional[str] = None,
                     sleep_sec: float = 0.5, verbose: bool = True) -> dict:
    """複数 ItemID を順次取得 → {item_id: dict}.

    sleep_sec: API rate limit 配慮の inter-call sleep (default 0.5s)。
    """
    if access_token is None:
        access_token = load_access_token()

    result: dict = {}
    for i, item_id in enumerate(item_ids, 1):
        if verbose:
            print(f"  [Trading API] [{i}/{len(item_ids)}] GetItem {item_id} ...", flush=True)
        result[item_id] = get_item(item_id, access_token=access_token)
        if i < len(item_ids) and sleep_sec > 0:
            time.sleep(sleep_sec)
    return result


# ============================================================================
# Policy cache (= 初回 全件 1424×1.5秒=36分 回避)
# ============================================================================
_CACHE_DIR = Path(__file__).resolve().parent / "cache"
POLICY_CACHE_FILE = _CACHE_DIR / "policy_cache.json"


def load_policy_cache() -> dict:
    """policy_cache.json → {item_id: {"shipping_profile_name": str, "current_price_usd": float, "ts": int}}."""
    if not POLICY_CACHE_FILE.exists():
        return {}
    try:
        import json as _json
        return _json.loads(POLICY_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_policy_cache(cache: dict):
    """cache を JSON 保存."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    import json as _json
    POLICY_CACHE_FILE.write_text(
        _json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_getsellerlist_xml(page: int, entries_per_page: int = 200) -> str:
    """GetSellerList request XML (= active listing 一括取得).

    GranularityLevel=Fine で StartPrice / Quantity / ShippingProfileName を含める。
    EndTimeFrom (= 直近 30日以内に終わる listing) で active 絞り込み。
    """
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    # active listing 全部拾うため: 今 から 120 日後まで終わる listing (= 全 GTC 含む)
    # EndTimeFrom = 今 (= ちょうど今日終わる listing も含む)
    start_from = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_to = (now + timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetSellerListRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f'<EndTimeFrom>{start_from}</EndTimeFrom>'
        f'<EndTimeTo>{end_to}</EndTimeTo>'
        '<GranularityLevel>Fine</GranularityLevel>'
        '<DetailLevel>ReturnAll</DetailLevel>'
        '<Pagination>'
        f'<EntriesPerPage>{entries_per_page}</EntriesPerPage>'
        f'<PageNumber>{page}</PageNumber>'
        '</Pagination>'
        '<IncludeVariations>true</IncludeVariations>'
        '</GetSellerListRequest>'
    )


def _parse_variations(item_block: str) -> list:
    """Item block の <Variations> から各 variation を抽出.

    Returns: List[dict] (= 空 list なら single listing)
      [{
        "sku": str (= UUID), "start_price": float, "quantity": int,
        "specifics": {"Sizes": "US XS(JP S)", "Colors": "Red"}
      }, ...]
    """
    variations: list = []
    var_section = re.search(r"<Variations>(.*?)</Variations>", item_block, re.DOTALL)
    if not var_section:
        return variations
    section_xml = var_section.group(1)
    for vm in re.finditer(r"<Variation>(.*?)</Variation>", section_xml, re.DOTALL):
        vblock = vm.group(1)
        sku = _x(vblock, "SKU")
        start_price = _xf(vblock, "StartPrice")
        # Quantity - SellingStatus.QuantitySold = available
        qty_total = _xi(vblock, "Quantity") or 0
        qty_sold = _xi(vblock, "QuantitySold") or 0
        # SellingStatus 内の QuantitySold (= variation 単位)
        ss = re.search(r"<SellingStatus>(.*?)</SellingStatus>", vblock, re.DOTALL)
        if ss:
            ss_sold = _xi(ss.group(1), "QuantitySold")
            if ss_sold is not None:
                qty_sold = ss_sold
        qty_avail = max(0, qty_total - qty_sold)
        # VariationSpecifics
        specifics: dict = {}
        spec_block = re.search(r"<VariationSpecifics>(.*?)</VariationSpecifics>",
                                vblock, re.DOTALL)
        if spec_block:
            for nv in re.finditer(r"<NameValueList>(.*?)</NameValueList>",
                                  spec_block.group(1), re.DOTALL):
                name = _x(nv.group(1), "Name")
                value = _x(nv.group(1), "Value")
                if name:
                    specifics[name] = value
        variations.append({
            "sku": sku,
            "start_price": start_price,
            "quantity": qty_avail,
            "specifics": specifics,
        })
    return variations


def _parse_seller_list_page(xml: str) -> tuple:
    """response XML → (items: List[dict], has_more: bool, total_pages: int).

    各 item は seller hub DL CSV と互換な column 名で:
      item_number / title / current_price / available_qty / shipping_profile_name / currency / site
      + has_variations / variations (= List[dict], 2026-05-24 追加)
    """
    items: list = []
    # Item ブロックを正規表現で抽出 (= 軽量 parser、依存最小化)
    for m in re.finditer(r"<Item>(.*?)</Item>", xml, re.DOTALL):
        block = m.group(1)
        item_id = _x(block, "ItemID")
        if not item_id:
            continue
        title = _x(block, "Title")
        # ConvertedCurrentPrice (= site 通貨) / StartPrice / BuyItNowPrice いずれか
        price = _xf(block, "ConvertedCurrentPrice")
        if price is None:
            price = _xf(block, "CurrentPrice")
        if price is None:
            price = _xf(block, "StartPrice")
        qty_avail = _xi(block, "QuantityAvailable")
        if qty_avail is None:
            # fallback: Quantity - QuantitySold
            qty_total = _xi(block, "Quantity") or 0
            qty_sold = _xi(block, "QuantitySold") or 0
            qty_avail = max(0, qty_total - qty_sold)
        # ShippingProfileName (SellerProfiles 内)
        prof = re.search(r"<SellerShippingProfile>(.*?)</SellerShippingProfile>",
                         block, re.DOTALL)
        shipping_profile = _x(prof.group(1), "ShippingProfileName") if prof else ""
        site = _x(block, "Site")
        currency = _x(block, "Currency") or "USD"

        # variation 解析 (2026-05-24 追加)
        variations = _parse_variations(block)
        has_variations = len(variations) > 0

        items.append({
            "item_id": item_id,
            "title": title,
            "current_price": price if price is not None else "",
            "available_qty": qty_avail,
            "shipping_profile_name": shipping_profile,
            "currency": currency,
            "site": site,
            "has_variations": has_variations,
            "variations": variations,
        })

    has_more = False
    m = re.search(r"<HasMoreItems>(true|false)</HasMoreItems>", xml)
    if m:
        has_more = (m.group(1) == "true")
    total_pages = 0
    m = re.search(r"<TotalNumberOfPages>(\d+)</TotalNumberOfPages>", xml)
    if m:
        total_pages = int(m.group(1))
    return items, has_more, total_pages


def _x(block: str, tag: str) -> str:
    """XML tag から text 抽出 (= 1 occurrence)。"""
    m = re.search(rf"<{tag}(?:\s[^>]*)?>(.*?)</{tag}>", block, re.DOTALL)
    return m.group(1).strip() if m else ""


def _xf(block: str, tag: str) -> Optional[float]:
    s = _x(block, tag)
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _xi(block: str, tag: str) -> Optional[int]:
    s = _x(block, tag)
    try:
        return int(s) if s else None
    except ValueError:
        return None


def fetch_all_active_listings(access_token: Optional[str] = None,
                               entries_per_page: int = 200,
                               sleep_sec: float = 0.5,
                               verbose: bool = True) -> list:
    """Trading API GetSellerList で全 active listing を取得.

    Returns: List[dict] (= snapshot CSV と互換 column の dict 配列)
    pagination で全 page 巡回、~1424件 8 page (= ~12秒) 想定。

    IAF token expired は自動 refresh。
    """
    import requests
    if access_token is None:
        access_token = load_access_token()

    all_items: list = []
    page = 1
    while True:
        body = _build_getsellerlist_xml(page=page, entries_per_page=entries_per_page)
        headers = {
            "X-EBAY-API-COMPATIBILITY-LEVEL": COMPATIBILITY_LEVEL,
            "X-EBAY-API-CALL-NAME": "GetSellerList",
            "X-EBAY-API-SITEID": SITE_ID_US,
            "X-EBAY-API-IAF-TOKEN": access_token,
            "Content-Type": "text/xml; charset=utf-8",
        }
        if verbose:
            print(f"  [GetSellerList] page {page} fetching...", flush=True)
        r = requests.post(TRADING_API_URL, headers=headers,
                          data=body.encode("utf-8"), timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"GetSellerList HTTP {r.status_code}: {r.text[:200]}")
        xml = r.text
        # token expired → 1 回だけ refresh + retry
        if _is_expired_iaf_token_error(xml) and access_token is not None:
            access_token = refresh_access_token()
            if verbose:
                print(f"  [GetSellerList] IAF token expired → refresh OK")
            continue

        items, has_more, total_pages = _parse_seller_list_page(xml)
        all_items.extend(items)
        if verbose:
            print(f"  [GetSellerList] page {page}: {len(items)} items "
                  f"(total so far {len(all_items)}, has_more={has_more})")
        if not has_more or len(items) == 0:
            break
        page += 1
        if sleep_sec > 0:
            time.sleep(sleep_sec)
        # 安全 cap (= 想定外の無限 loop 防止)
        if page > 50:
            print(f"  [GetSellerList] [WARN] page 50 上限 で打切")
            break

    return all_items


def save_snapshot_csv(items: list, output_dir: Path) -> Path:
    """items を seller hub DL CSV 互換 format で保存.

    file 名: ebay_active_YYYY-MM-DD_HHMMSS.csv
    column: Item number / Title / Currency / Current price / Listing site / Available quantity
    """
    import csv as _csv
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H%M%S")
    path = output_dir / f"ebay_active_{ts}.csv"
    headers = ["Item number", "Title", "Currency", "Current price",
               "Listing site", "Available quantity", "Shipping profile name"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = _csv.writer(f)
        writer.writerow(headers)
        for it in items:
            writer.writerow([
                it.get("item_id", ""),
                it.get("title", ""),
                it.get("currency", "USD"),
                it.get("current_price", ""),
                it.get("site", "US"),
                it.get("available_qty", 0),
                it.get("shipping_profile_name", ""),
            ])
    # variation 情報を別 JSON で並列保存 (= snapshot CSV format 互換を保つため)
    var_items = [it for it in items if it.get("has_variations")]
    if var_items:
        import json as _json
        var_path = output_dir / f"ebay_active_{ts}.variations.json"
        var_map = {it["item_id"]: it["variations"] for it in var_items}
        var_path.write_text(_json.dumps(var_map, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return path


def rotate_snapshots(snapshot_dir: Path, pattern: str = "ebay_active_*.csv",
                      keep_count: int = 5) -> list:
    """古い snapshot を自動削除. mtime 順に keep_count 件のみ残す.

    Returns: 削除した file path のリスト
    """
    if not snapshot_dir.exists():
        return []
    files = sorted(snapshot_dir.glob(pattern),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    deleted: list = []
    for old in files[keep_count:]:
        try:
            old.unlink()
            deleted.append(old)
        except OSError:
            pass
    return deleted


def get_items_cached(item_ids: list, cache: Optional[dict] = None,
                      force_refresh_ids: Optional[set] = None,
                      access_token: Optional[str] = None,
                      sleep_sec: float = 0.5, verbose: bool = True) -> dict:
    """cache 優先で取得。cache hit は API 呼ばず即返し、miss / force_refresh のみ API 呼出.

    force_refresh_ids: 直近 revise 済の ItemID set。確実に再取得して cache 更新。

    Returns: {item_id: entry} (全 item_ids 含む、entry は cache or 新規取得)
    """
    if cache is None:
        cache = load_policy_cache()
    force_refresh_ids = force_refresh_ids or set()

    to_fetch = [iid for iid in item_ids
                if iid not in cache or iid in force_refresh_ids]
    if verbose:
        cached_n = len(item_ids) - len(to_fetch)
        print(f"  [Trading API cache] hit {cached_n} / fetch {len(to_fetch)} (force_refresh={len(force_refresh_ids)})")

    if to_fetch:
        if access_token is None:
            access_token = load_access_token()
        fresh = {}
        for i, iid in enumerate(to_fetch, 1):
            if verbose:
                print(f"  [Trading API] [{i}/{len(to_fetch)}] GetItem {iid} ...", flush=True)
            fresh[iid] = get_item(iid, access_token=access_token)
            fresh[iid]["ts"] = int(time.time())
            if i < len(to_fetch) and sleep_sec > 0:
                time.sleep(sleep_sec)
        # cache 更新 (成功 entry のみ)
        for iid, entry in fresh.items():
            if not entry.get("error"):
                cache[iid] = entry
        save_policy_cache(cache)

    # return: 全 item_ids
    result = {}
    for iid in item_ids:
        result[iid] = cache.get(iid) or {"shipping_profile_name": None,
                                          "current_price_usd": None,
                                          "error": "not_in_cache"}
    return result
