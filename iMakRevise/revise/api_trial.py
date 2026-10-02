"""api_trial.py - API 版 revise の1件試験 (2026-10-01 ユーザー go 済み).

手順 (1件ずつ):
  1. GetItem (Item Specifics 込み) で送る前の状態を控える (raw XML も保存)
  2. 値段を +1 USD した値を API で送る (ReviseInventoryStatus。variation は SKU 指定)
     + 送料ポリシーを「今と同じ ID」で送る (ReviseFixedPriceItem。値は変えず、この呼び方で他の項目が消えないかを見る)
  3. GetItem で取り直し、変わったのが値段だけか確かめる
  4. 値段を元に戻す (ReviseInventoryStatus) → GetItem で元どおりか確かめる
全件の切替はしない (このファイルは1件ずつしか送れない)。

使い方:
  python -X utf8 revise/api_trial.py --item 820041238478
  python -X utf8 revise/api_trial.py --item 357849150249 --sku <SKU>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from revise import ebay_trading_api as t  # noqa: E402
from revise.api_revise import (PriceChange, ShippingChange, assert_only_allowed_tags,  # noqa: E402
                               build_inventory_status_xml, build_shipping_xml, trading_call)

OUT_DIR = PKG_ROOT / "decision_log" / "api_trial"


def get_full(item_id: str) -> str:
    return trading_call("GetItem", (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel>"
        "<IncludeItemSpecifics>true</IncludeItemSpecifics></GetItemRequest>"))


def _one(tag: str, xml: str):
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S)
    return m.group(1) if m else None


def summarize(xml: str) -> dict:
    """比べる項目だけ抜く (値段・送料は変わってよい / 他は変わってはいけない)."""
    item = _one("Item", xml) or ""
    no_vars = re.sub(r"<Variations>.*</Variations>", "", item, flags=re.S)
    specifics = re.findall(r"<NameValueList><Name>(.*?)</Name>(.*?)</NameValueList>",
                           _one("ItemSpecifics", no_vars) or "", re.S)
    variations = []
    for v in re.findall(r"<Variation>(.*?)</Variation>", _one("Variations", item) or "", re.S):
        variations.append({"sku": _one("SKU", v), "price": _one("StartPrice", v),
                           "qty": _one("Quantity", v),
                           "specifics": _one("VariationSpecifics", v)})
    return {
        "ack": _one("Ack", xml),
        "title": _one("Title", no_vars),
        "quantity": _one("Quantity", no_vars),
        "start_price": _one("StartPrice", no_vars),
        "shipping_profile_id": _one("ShippingProfileID", no_vars),
        "shipping_profile_name": _one("ShippingProfileName", no_vars),
        "item_specifics": sorted(specifics),
        "description_md5": hashlib.md5((_one("Description", no_vars) or "").encode()).hexdigest(),
        "pictures": re.findall(r"<PictureURL>(.*?)</PictureURL>", no_vars),
        "category": _one("CategoryID", no_vars),
        "best_offer": _one("BestOfferEnabled", no_vars),
        "variations": variations,
    }


def _send(call_name: str, xml: str, log: list) -> str:
    assert_only_allowed_tags(xml)
    res = trading_call(call_name, xml)
    ack = _one("Ack", res)
    errs = re.findall(r"<LongMessage>(.*?)</LongMessage>", res)
    log.append({"call": call_name, "request": xml, "ack": ack, "errors": errs})
    if ack not in ("Success", "Warning"):
        raise RuntimeError(f"{call_name} 失敗: {ack} {errs}")
    return res


def _diff(before: dict, after: dict, allow: set) -> list:
    return [k for k in before if k not in allow and before[k] != after[k]]


def run_trial(item_id: str, sku: str | None) -> dict:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log: list = []

    raw0 = get_full(item_id)
    (OUT_DIR / f"{stamp}_{item_id}_0_before.xml").write_text(raw0, encoding="utf-8")
    s0 = summarize(raw0)
    if s0["ack"] not in ("Success", "Warning"):
        raise RuntimeError(f"GetItem 失敗: {item_id}")

    if sku:
        v0 = next(v for v in s0["variations"] if v["sku"] == sku)
        price0 = float(v0["price"])
    else:
        if s0["variations"]:
            raise RuntimeError("variation 出品なので --sku が必要")
        price0 = float(s0["start_price"])
    price1 = round(price0 + 1.0, 2)

    # 2. 値段 +1 / 送料は今と同じ ID
    _send("ReviseInventoryStatus", build_inventory_status_xml([PriceChange(item_id, price1, sku=sku)]), log)
    _send("ReviseFixedPriceItem", build_shipping_xml(
        ShippingChange(item_id, s0["shipping_profile_name"], s0["shipping_profile_id"])), log)

    raw1 = get_full(item_id)
    (OUT_DIR / f"{stamp}_{item_id}_1_after.xml").write_text(raw1, encoding="utf-8")
    s1 = summarize(raw1)

    # 4. 元に戻す
    _send("ReviseInventoryStatus", build_inventory_status_xml([PriceChange(item_id, price0, sku=sku)]), log)
    raw2 = get_full(item_id)
    (OUT_DIR / f"{stamp}_{item_id}_2_restored.xml").write_text(raw2, encoding="utf-8")
    s2 = summarize(raw2)

    if sku:
        got1 = float(next(v for v in s1["variations"] if v["sku"] == sku)["price"])
        others_same = ([v for v in s0["variations"] if v["sku"] != sku]
                       == [v for v in s1["variations"] if v["sku"] != sku])
        unchanged = _diff(s0, s1, {"variations"}) + ([] if others_same else ["他のvariation"])
        tgt0 = {k: v for k, v in v0.items() if k != "price"}
        tgt1 = {k: v for k, v in next(v for v in s1["variations"] if v["sku"] == sku).items() if k != "price"}
        if tgt0 != tgt1:
            unchanged.append("対象variationの数量/specifics")
    else:
        got1 = float(s1["start_price"])
        unchanged = _diff(s0, s1, {"start_price"})

    result = {
        "item_id": item_id, "sku": sku,
        "price_before": price0, "price_sent": price1, "price_after_send": got1,
        "price_changed_ok": abs(got1 - price1) < 0.001,
        "changed_other_than_price": unchanged,
        "restored_ok": s2 == s0,
        "restored_diff": _diff(s0, s2, set()),
        "calls": log,
    }
    (OUT_DIR / f"{stamp}_{item_id}_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", required=True)
    ap.add_argument("--sku")
    a = ap.parse_args()
    r = run_trial(a.item, a.sku)
    print(json.dumps({k: v for k, v in r.items() if k != "calls"}, ensure_ascii=False, indent=2))
    for c in r["calls"]:
        print(c["call"], c["ack"], c["errors"])
    ok = r["price_changed_ok"] and not r["changed_other_than_price"] and r["restored_ok"]
    print("RESULT:", "OK" if ok else "NG")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
