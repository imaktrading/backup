"""ebay_active_listing_via_trading_api - GetSellerList Fine で Active Listing CSV 生成.

Phase 4a-3 (2026-06-05): Selenium UI scrape (ebay_active_listing_dl.py) を
Trading API GetSellerList に置換。 eBay reports/schedule の UI 構造変更で
_schedule_new_report XPath が 5/29 から失敗継続 → fallback で 6/3 dated CSV を
使い続け → 新規 listing が監視対象外になる Defect Rate リスクを解消。

memory: reuse_existing_proven_solution.md (= 既存 Trading API client を流用)。

出力 CSV format:
  既存 Active Listing Report と互換 8 column (= parse_ebay_report / audit_and_heal
  が必要な最小列):
    Item number, Title, Variation details, Custom label (SKU),
    Available quantity, Format, Currency, Start price

  variation listing は variation 別 row、 single listing は 1 row。
  utf-8-sig (BOM 付き) で既存 reader と互換。

実行:
    python ebay_active_listing_via_trading_api.py        # DL → path 表示
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# stdout/stderr UTF-8 化
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# iMakInventory の Trading API client を流用
_inv_root = SCRIPT_DIR.parent.parent / "iMakInventory"
if str(_inv_root) not in sys.path:
    sys.path.append(str(_inv_root))

import requests  # noqa: E402

from ebay_actions.trading_api_client import (  # noqa: E402
    COMPATIBILITY_LEVEL,
    SITE_ID_US,
    TRADING_API_URL,
    _is_expired_iaf_token_error,
    load_access_token,
    refresh_access_token,
)

# 出力先 (= ebay_active_listing_dl.py と同じ dir、 _latest_ebay_report が mtime で拾える)
DL_DIR = Path(r"C:\Users\imax2\local_data\iMakInventory\ebay_active_listing_dl")
DL_DIR.mkdir(parents=True, exist_ok=True)

# 既存 Active Listing Report CSV と互換の最小 8 column
CSV_HEADER = [
    "Item number",
    "Title",
    "Variation details",
    "Custom label (SKU)",
    "Available quantity",
    "Format",
    "Currency",
    "Start price",
]


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _build_request_xml(page: int, entries_per_page: int = 200) -> str:
    """GetSellerList Fine + IncludeVariations の request XML."""
    now = datetime.now(timezone.utc)
    sf = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    st = (now + timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetSellerListRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f"<EndTimeFrom>{sf}</EndTimeFrom>"
        f"<EndTimeTo>{st}</EndTimeTo>"
        "<DetailLevel>ReturnAll</DetailLevel>"
        "<GranularityLevel>Fine</GranularityLevel>"
        "<IncludeVariations>true</IncludeVariations>"
        "<Pagination>"
        f"<EntriesPerPage>{entries_per_page}</EntriesPerPage>"
        f"<PageNumber>{page}</PageNumber>"
        "</Pagination>"
        "</GetSellerListRequest>"
    )


def _post_with_retry(xml: str, token: str, max_attempts: int = 5,
                     sleep_sec: float = 10.0) -> tuple[str, str]:
    """POST + DNS / 一時的接続失敗 自動 retry + IAF 期限切れ自動 refresh.

    Returns: (response_text, current_token)
    """
    headers = {
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPATIBILITY_LEVEL,
        "X-EBAY-API-CALL-NAME": "GetSellerList",
        "X-EBAY-API-SITEID": SITE_ID_US,
        "X-EBAY-API-IAF-TOKEN": token,
        "Content-Type": "text/xml; charset=utf-8",
    }
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            r = requests.post(TRADING_API_URL, headers=headers,
                              data=xml.encode("utf-8"), timeout=90)
        except requests.exceptions.ConnectionError as e:
            last_exc = e
            _log(f"  [WARN] attempt {attempt}/{max_attempts} ConnErr "
                 f"(DNS/Timeout) → sleep {sleep_sec}s")
            time.sleep(sleep_sec)
            continue
        if _is_expired_iaf_token_error(r.text):
            _log("  [Trading API] GetSellerList: IAF token expired → refresh")
            token = refresh_access_token()
            headers["X-EBAY-API-IAF-TOKEN"] = token
            continue  # 同 page 再試行
        return r.text, token
    raise RuntimeError(f"GetSellerList: connection failed after {max_attempts} attempts "
                       f"(last: {type(last_exc).__name__}: {last_exc})")


def _extract_variation_details(var_block: str) -> str:
    """Variation XML block → "Sizes=US M(JP L)|Color=BL" 形式の文字列.

    eBay Active Listing Report の Variation details column 表現に合わせる。
    """
    nvls = re.findall(
        r"<NameValueList>\s*<Name>([^<]+)</Name>\s*<Value>([^<]+)</Value>",
        var_block,
    )
    return "|".join(f"{n}={v}" for n, v in nvls)


def _parse_items(xml: str) -> list:
    """page XML → CSV row list. variation 別 + single 別を出力.

    Returns: list of [Item number, Title, Variation details, Custom label,
                      Available quantity, Format, Currency, Start price]
    """
    rows: list = []
    for m in re.finditer(r"<Item>(.*?)</Item>", xml, re.DOTALL):
        block = m.group(1)
        iid_m = re.search(r"<ItemID>([^<]+)</ItemID>", block)
        if not iid_m:
            continue
        iid = iid_m.group(1).strip()
        title_m = re.search(r"<Title>([^<]+)</Title>", block)
        title = title_m.group(1).strip() if title_m else ""
        currency_m = re.search(r'<StartPrice[^>]*currencyID="([^"]+)"', block)
        currency = currency_m.group(1).strip() if currency_m else "USD"
        # listing 全体の StartPrice (= single listing の price、 variation の default)
        sp_m = re.search(r"<StartPrice[^>]*>([\d.]+)</StartPrice>", block)
        listing_price = sp_m.group(1).strip() if sp_m else "0.00"

        # listing type = FixedPrice (= 既存 CSV の "FIXED_PRICE")
        listing_type_m = re.search(r"<ListingType>([^<]+)</ListingType>", block)
        listing_type = (listing_type_m.group(1).strip() if listing_type_m
                        else "FixedPriceItem")
        format_csv = "FIXED_PRICE" if "FixedPrice" in listing_type else listing_type

        if "<Variations>" in block:
            # variation listing: 各 variation を 1 row + 親 row (= 既存 CSV と互換)
            varblocks = re.findall(r"<Variation>(.*?)</Variation>", block, re.DOTALL)
            # 親 row (= variation details 集約、 SKU 空、 qty 空): 既存 reader で skip 判定される
            #   ; 含む = 親行扱い、 ebay_qty_sync / audit_heal は skip。 必須ではないが互換のため出す
            specs_per_axis: dict = {}
            for vb in varblocks:
                nvls = re.findall(
                    r"<NameValueList>\s*<Name>([^<]+)</Name>\s*<Value>([^<]+)</Value>",
                    vb,
                )
                for n, v in nvls:
                    specs_per_axis.setdefault(n, [])
                    if v not in specs_per_axis[n]:
                        specs_per_axis[n].append(v)
            parent_spec = "|".join(
                f"{n}={';'.join(vals)}" for n, vals in specs_per_axis.items()
            )
            rows.append([iid, title, parent_spec, "", "", format_csv, currency,
                         listing_price])
            # 子 variation 行
            for vb in varblocks:
                vsku_m = re.search(r"<SKU>([^<]+)</SKU>", vb)
                vsku = vsku_m.group(1).strip() if vsku_m else ""
                vqty_m = re.search(r"<Quantity>(\d+)</Quantity>", vb)
                vsold_m = re.search(
                    r"<SellingStatus>.*?<QuantitySold>(\d+)</QuantitySold>",
                    vb, re.DOTALL,
                )
                vqty = int(vqty_m.group(1)) if vqty_m else 0
                vsold = int(vsold_m.group(1)) if vsold_m else 0
                available = max(0, vqty - vsold)
                vprice_m = re.search(r"<StartPrice[^>]*>([\d.]+)</StartPrice>", vb)
                vprice = vprice_m.group(1).strip() if vprice_m else listing_price
                vspec = _extract_variation_details(vb)
                rows.append([iid, title, vspec, vsku, str(available), format_csv,
                             currency, vprice])
        else:
            # single listing
            sku_m = re.search(r"<SKU>([^<]+)</SKU>", block)
            sku = sku_m.group(1).strip() if sku_m else ""
            qt_m = re.search(r"<Quantity>(\d+)</Quantity>", block)
            sold_m = re.search(
                r"<SellingStatus>.*?<QuantitySold>(\d+)</QuantitySold>",
                block, re.DOTALL,
            )
            qt = int(qt_m.group(1)) if qt_m else 0
            sold = int(sold_m.group(1)) if sold_m else 0
            available = max(0, qt - sold)
            rows.append([iid, title, "", sku, str(available), format_csv,
                         currency, listing_price])
    return rows


def download_active_listing_via_trading_api(
    entries_per_page: int = 200,
    max_pages: int = 60,
    out_dir: Path = DL_DIR,
) -> Path:
    """GetSellerList Fine paging → Active Listing CSV 生成 → path 返却."""
    _log("=" * 60)
    _log("Active Listings via Trading API GetSellerList")
    _log("=" * 60)

    token = load_access_token()
    all_rows: list = []
    for page in range(1, max_pages + 1):
        xml = _build_request_xml(page, entries_per_page)
        resp, token = _post_with_retry(xml, token)
        ack = re.search(r"<Ack>([^<]+)</Ack>", resp)
        if ack and ack.group(1) not in ("Success", "Warning"):
            err = re.search(r"<ShortMessage>([^<]+)</ShortMessage>", resp)
            raise RuntimeError(f"GetSellerList Ack={ack.group(1)}, "
                               f"err={err.group(1) if err else '?'}")
        page_rows = _parse_items(resp)
        all_rows.extend(page_rows)
        has_more_m = re.search(r"<HasMoreItems>([^<]+)</HasMoreItems>", resp)
        has_more = (has_more_m.group(1).lower() == "true") if has_more_m else False
        total_m = re.search(r"<TotalNumberOfPages>(\d+)</TotalNumberOfPages>", resp)
        total_pages = int(total_m.group(1)) if total_m else page
        _log(f"  page {page}/{total_pages}: {len(page_rows)} rows "
             f"(累計 {len(all_rows)})、 has_more={has_more}")
        if not has_more:
            break
        time.sleep(0.5)  # quota pacing

    # 書込先 path (= mtime 最新で _latest_ebay_report に拾われる命名)
    date_str = datetime.now().strftime("%Y-%m-%d")
    ts_str = datetime.now().strftime("%H%M%S")
    csv_path = out_dir / f"eBay-all-active-listings-report-{date_str}-trading-{ts_str}.csv"
    # utf-8-sig = BOM 付き、 既存 reader と互換
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerows(all_rows)
    _log(f"[OK] CSV 出力: {csv_path}  ({len(all_rows)} rows)")
    return csv_path


def main():
    parser = argparse.ArgumentParser(
        description="Active Listings via Trading API GetSellerList")
    parser.add_argument("--entries-per-page", type=int, default=200)
    parser.add_argument("--max-pages", type=int, default=60)
    args = parser.parse_args()
    path = download_active_listing_via_trading_api(
        entries_per_page=args.entries_per_page,
        max_pages=args.max_pages,
    )
    print(f"CSV_PATH={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
