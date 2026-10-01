"""api_revise.py - 価格/送料ポリシーの revise を eBay API で行う版 (FileExchange の並行版・fork).

2026-10-01 HQ 依頼 (2026-10-01_revise_api_parallel_build.md):
  今の FileExchange (Chrome) の流れ (run_daily.py / variation_upload.py) は一切触らない。
  これは別ファイルで、同じ revise CSV を入力に「API なら何を送るか」を組み立てる。
  本番切替はユーザーの go の後。それまでは shadow (api_shadow.py) で突き合わせるだけ。

送る項目は「値段」と「送料ポリシー」だけ (2026-09-03 に FileExchange Revise で
Item Specifics が丸ごと消えた事故の再発防止):
  - 値段     → ReviseInventoryStatus (StartPrice のみ。Quantity は入れない。1呼出 4件まで)
               variation は SKU 指定 (snapshot の variations.json で specifics → SKU を引く)
  - 送料     → ReviseFixedPriceItem (Item 直下は ItemID と SellerProfiles/SellerShippingProfile だけ)
組み立てた XML は assert_only_allowed_tags() で許可タグ以外が無いことを毎回検査する。
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

ACCOUNT_API_FULFILLMENT_URL = "https://api.ebay.com/sell/account/v1/fulfillment_policy"
INVENTORY_STATUS_BATCH = 4  # ReviseInventoryStatus の1呼出あたり上限

# 送ってよいタグ (これ以外が XML に出たら組み立て誤りとして止める)
ALLOWED_TAGS = {
    "ReviseInventoryStatusRequest": {"ReviseInventoryStatusRequest", "InventoryStatus",
                                     "ItemID", "SKU", "StartPrice"},
    "ReviseFixedPriceItemRequest": {"ReviseFixedPriceItemRequest", "Item", "ItemID",
                                    "SellerProfiles", "SellerShippingProfile",
                                    "ShippingProfileID"},
}


@dataclass
class PriceChange:
    item_id: str
    price: float
    sku: Optional[str] = None          # variation のみ
    specifics: Optional[str] = None    # variation の CSV 表記 (突合・表示用)


@dataclass
class ShippingChange:
    item_id: str
    profile_name: str
    profile_id: Optional[str] = None


@dataclass
class ApiPlan:
    prices: list = field(default_factory=list)      # list[PriceChange]
    shippings: list = field(default_factory=list)   # list[ShippingChange]
    problems: list = field(default_factory=list)    # 組み立てられなかった行 (= 切替前に潰す)


# ── 入力 (revise CSV) の読込 ────────────────────────────────────────────

def _read_csv(path: Optional[Path]) -> list:
    if not path or not Path(path).exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _norm_specifics(s: str) -> str:
    """'Color=Black|Sizes=US S(JP M)' → 'Color=Black|Sizes=US S(JP M)' (名前順で正規化)."""
    parts = [p for p in s.split("|") if p]
    return "|".join(sorted(parts))


def _specifics_key(d: dict) -> str:
    return "|".join(sorted(f"{k}={v}" for k, v in d.items()))


def load_variation_skus(variations_json: Optional[Path]) -> dict:
    """snapshot の variations.json → {item_id: {specifics_key: sku}}."""
    if not variations_json or not Path(variations_json).exists():
        return {}
    data = json.loads(Path(variations_json).read_text(encoding="utf-8"))
    out = {}
    for item_id, vars_ in data.items():
        out[str(item_id)] = {_specifics_key(v.get("specifics") or {}): v.get("sku") for v in vars_}
    return out


def build_plan(single_csv: Optional[Path], var_price_csv: Optional[Path],
               var_shipping_csv: Optional[Path], variations_json: Optional[Path],
               policy_ids: dict) -> ApiPlan:
    """revise CSV 3本 → API で送る中身. 引けない行は problems に入れ、推測で埋めない."""
    plan = ApiPlan()
    var_skus = load_variation_skus(variations_json)

    for r in _read_csv(single_csv):
        item_id = (r.get("ItemID") or "").strip()
        if not item_id:
            continue
        if item_id in var_skus:
            plan.problems.append(f"{item_id}: single 行だが variation 出品 (SKU 無しでは値段を送れない)")
            continue
        price = (r.get("*StartPrice") or "").strip()
        if price:
            plan.prices.append(PriceChange(item_id, float(price)))
        prof = (r.get("ShippingProfileName") or "").strip()
        if prof:
            plan.shippings.append(ShippingChange(item_id, prof, policy_ids.get(prof)))

    current_parent = None
    for r in _read_csv(var_price_csv):
        if (r.get("ItemID") or "").strip():
            current_parent = r["ItemID"].strip()
            continue
        if (r.get("Relationship") or "").strip() != "Variation" or not current_parent:
            continue
        spec = (r.get("RelationshipDetails") or "").strip()
        price = (r.get("*StartPrice") or "").strip()
        if not price:
            continue
        sku = var_skus.get(current_parent, {}).get(_norm_specifics(spec))
        if not sku:
            plan.problems.append(f"{current_parent} [{spec}]: snapshot に一致する SKU が無い")
            continue
        plan.prices.append(PriceChange(current_parent, float(price), sku=sku, specifics=spec))

    for r in _read_csv(var_shipping_csv):
        item_id = (r.get("ItemID") or "").strip()
        prof = (r.get("ShippingProfileName") or "").strip()
        if item_id and prof:
            plan.shippings.append(ShippingChange(item_id, prof, policy_ids.get(prof)))

    for s in plan.shippings:
        if not s.profile_id:
            plan.problems.append(f"{s.item_id}: 送料ポリシー名 {s.profile_name} の ID が eBay に無い")
    return plan


# ── XML 組み立て + 許可タグ検査 ────────────────────────────────────────

def build_inventory_status_xml(changes: list) -> str:
    assert 0 < len(changes) <= INVENTORY_STATUS_BATCH
    body = ""
    for c in changes:
        body += "<InventoryStatus>"
        body += f"<ItemID>{escape(c.item_id)}</ItemID>"
        if c.sku:
            body += f"<SKU>{escape(c.sku)}</SKU>"
        body += f"<StartPrice>{c.price:.2f}</StartPrice>"
        body += "</InventoryStatus>"
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<ReviseInventoryStatusRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"{body}</ReviseInventoryStatusRequest>")


def build_shipping_xml(change: ShippingChange) -> str:
    assert change.profile_id
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<ReviseFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<Item><ItemID>{escape(change.item_id)}</ItemID>"
            "<SellerProfiles><SellerShippingProfile>"
            f"<ShippingProfileID>{escape(change.profile_id)}</ShippingProfileID>"
            "</SellerShippingProfile></SellerProfiles></Item>"
            "</ReviseFixedPriceItemRequest>")


def assert_only_allowed_tags(xml: str) -> None:
    root = re.search(r"<(\w+Request)\b", xml).group(1)
    tags = set(re.findall(r"<(\w+)[\s>/]", xml)) - {"?xml"}
    extra = tags - ALLOWED_TAGS[root]
    if extra:
        raise ValueError(f"{root} に許可外のタグ: {sorted(extra)}")


def build_all_xml(plan: ApiPlan) -> list:
    """送る順の XML 一覧 (値段→送料). 各 XML は許可タグ検査済み."""
    out = []
    for i in range(0, len(plan.prices), INVENTORY_STATUS_BATCH):
        out.append(build_inventory_status_xml(plan.prices[i:i + INVENTORY_STATUS_BATCH]))
    for s in plan.shippings:
        if s.profile_id:
            out.append(build_shipping_xml(s))
    for x in out:
        assert_only_allowed_tags(x)
    return out


# ── eBay から読むだけの補助 (送信はしない) ─────────────────────────────

def fetch_shipping_policy_ids() -> dict:
    """Account API で送料ポリシー名 → ID (US). token 切れなら1回 refresh."""
    import requests
    from . import ebay_trading_api as t

    def _get(tok):
        return requests.get(ACCOUNT_API_FULFILLMENT_URL, params={"marketplace_id": "EBAY_US"},
                            headers={"Authorization": f"Bearer {tok}"}, timeout=30)

    r = _get(t.load_access_token())
    if r.status_code == 401:
        r = _get(t.refresh_access_token())
    r.raise_for_status()
    return {p["name"]: p["fulfillmentPolicyId"] for p in r.json().get("fulfillmentPolicies", [])}
