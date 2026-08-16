"""ebay_sold - eBay で売れた注文と、その出品の商品情報を取る (再出品の入口).

2026-08-17 新設 (user 依頼「売れた商品の補充」)。

**なぜ eBay から引くのか**: 売れた行は HIGH 商品管理シートに残らない
(2026-08-17 実測: 直近90日の注文 30 件のうち シートに残っていたのは 4 件)。
シートを起点にすると 26/30 が辿れないので、**eBay 側を SSOT** にする。

2 段構成 (どちらも既存の認証をそのまま使う。 新規セットアップ不要):
  ① 注文一覧 : Sell Fulfillment API `getOrders`
     `iMakeBayAPI/ebay_oauth_token_sell.json` の user token (sell.fulfillment.readonly)
     期限切れなら `cd iMakeBayAPI && python oauth_sell_setup.py refresh`
  ② 商品情報 : Trading API `GetItem` + **IncludeItemSpecifics=true**
     `iMakeBayAPI/ebay keys.txt` の AuthToken。 売れて終了した listing でも取れる
     (実測: Card Name / Card Number / Set / Game / Grade / Year が全部返る)。
     ★`DetailLevel=ReturnAll` だけでは ItemSpecifics が返らない。 明示フラグが要る。

本モジュールは **読むだけ**。 listing の変更は一切しない。
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

import requests

# 認証情報は本元 (C:/dev/iMak) 側にある。 sheet_writer.CREDS_PATH と同じ参照の仕方。
EBAY_DIR = Path(r"C:/dev/iMak/iMakeBayAPI")
KEYS_PATH = EBAY_DIR / "ebay keys.txt"
SELL_TOKEN_PATH = EBAY_DIR / "ebay_oauth_token_sell.json"

ORDERS_URL = "https://api.ebay.com/sell/fulfillment/v1/order"
TRADING_ENDPOINT = "https://api.ebay.com/ws/api.dll"
TRADING_COMPAT = "1193"

# この環境は getaddrinfo が断続失敗する (既知)。 fetch は必ず retry する。
_RETRY = 4
_RETRY_SLEEP = 4.0


def _load_keys() -> dict:
    k = {}
    with open(KEYS_PATH, encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                a, b = line.split("=", 1)
                k[a.strip()] = b.strip()
    return k


def _load_sell_token() -> str:
    import json  # noqa: PLC0415
    return json.loads(SELL_TOKEN_PATH.read_text(encoding="utf-8"))["access_token"]


def _get(url, **kwargs):
    last = None
    for attempt in range(_RETRY):
        try:
            return requests.get(url, **kwargs)
        except Exception as e:  # noqa: BLE001 - DNS 瞬断を含む
            last = e
            if attempt < _RETRY - 1:
                time.sleep(_RETRY_SLEEP)
    raise last


def _post(url, **kwargs):
    last = None
    for attempt in range(_RETRY):
        try:
            return requests.post(url, **kwargs)
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < _RETRY - 1:
                time.sleep(_RETRY_SLEEP)
    raise last


# ---------------------------------------------------------------------------
# ① 注文一覧
# ---------------------------------------------------------------------------
def fetch_sold_items(since_iso: str, token: Optional[str] = None) -> list[dict]:
    """since_iso 以降の注文を全ページ取得し、 出品単位に潰して返す.

    Args:
        since_iso: "2026-05-20T00:00:00.000Z" 形式
    Returns:
        [{"item_id": str, "title": str, "sold_at": "YYYY-MM-DD", "quantity": int}]
        同じ item_id が複数回売れていれば 最新の売却日で 1 件にまとめる。
    """
    tok = token or _load_sell_token()
    orders, offset = [], 0
    while True:
        r = _get(ORDERS_URL, headers={"Authorization": f"Bearer {tok}"},
                 params={"filter": f"creationdate:[{since_iso}..]",
                         "limit": 200, "offset": offset}, timeout=30)
        r.raise_for_status()
        d = r.json()
        got = d.get("orders") or []
        orders += got
        offset += len(got)
        if len(got) < 200 or offset >= (d.get("total") or 0):
            break
    return group_line_items(orders)


def group_line_items(orders: list[dict]) -> list[dict]:
    """注文 JSON を item_id 単位に潰す (純関数 = テスト対象)."""
    out: dict[str, dict] = {}
    for o in orders:
        sold_at = (o.get("creationDate") or "")[:10]
        for li in o.get("lineItems") or []:
            iid = str(li.get("legacyItemId") or "").strip()
            if not iid:
                continue
            cur = out.get(iid)
            qty = int(li.get("quantity") or 1)
            if cur is None:
                out[iid] = {"item_id": iid, "title": li.get("title") or "",
                            "sold_at": sold_at, "quantity": qty}
            else:
                cur["quantity"] += qty
                if sold_at > cur["sold_at"]:
                    cur["sold_at"] = sold_at
    return sorted(out.values(), key=lambda x: x["sold_at"], reverse=True)


# ---------------------------------------------------------------------------
# ② 商品情報 (Item Specifics)
# ---------------------------------------------------------------------------
_NAME_VALUE_RE = re.compile(
    r"<Name>([^<]*)</Name>((?:\s*<Value>[^<]*</Value>)+)")
_VALUE_RE = re.compile(r"<Value>([^<]*)</Value>")
_TITLE_RE = re.compile(r"<Title>([^<]*)</Title>")
_ACK_RE = re.compile(r"<Ack>([^<]*)</Ack>")


def parse_get_item(xml: str) -> dict:
    """GetItem 応答から タイトル と Item Specifics を抜く (純関数 = テスト対象).

    Returns: {"ok": bool, "title": str, "specifics": {name: value}}
             値が複数ある項目は "/" 連結。 HTML エンティティは復元する。
    """
    import html as _html  # noqa: PLC0415

    ack = (_ACK_RE.search(xml or "") or [None, ""])[1]
    ok = ack in ("Success", "Warning")
    title = _html.unescape((_TITLE_RE.search(xml or "") or [None, ""])[1])
    specifics = {}
    for name, values in _NAME_VALUE_RE.findall(xml or ""):
        vals = [_html.unescape(v) for v in _VALUE_RE.findall(values)]
        specifics[_html.unescape(name)] = "/".join(v for v in vals if v)
    return {"ok": ok, "title": title, "specifics": specifics}


def fetch_item_specifics(item_id: str, keys: Optional[dict] = None) -> dict:
    """売れた listing でも取得できる。 失敗時は {"ok": False, ...}."""
    k = keys or _load_keys()
    hdr = {
        "X-EBAY-API-CALL-NAME": "GetItem",
        "X-EBAY-API-SITEID": "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": TRADING_COMPAT,
        "X-EBAY-API-APP-NAME": k["AppID"],
        "X-EBAY-API-DEV-NAME": k["DevID"],
        "X-EBAY-API-CERT-NAME": k["AppSecret"],
        "Content-Type": "text/xml",
    }
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f"<RequesterCredentials><eBayAuthToken>{k['AuthToken']}</eBayAuthToken>"
        "</RequesterCredentials>"
        f"<ItemID>{item_id}</ItemID>"
        # ★ReturnAll だけでは ItemSpecifics が返らない (2026-08-17 実測)
        "<IncludeItemSpecifics>true</IncludeItemSpecifics>"
        "<DetailLevel>ReturnAll</DetailLevel></GetItemRequest>"
    )
    try:
        r = _post(TRADING_ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=30)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "title": "", "specifics": {}, "error": repr(e)[:120]}
    return parse_get_item(r.text)
