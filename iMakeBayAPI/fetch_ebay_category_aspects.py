#!/usr/bin/env python3
"""eBay Sell Metadata API getItemAspectsForCategory で カテゴリ別 Item Specifics 正規値 取得.

usage:
    python fetch_ebay_category_aspects.py <category_id> [output_json]

example (= TCG):
    python fetch_ebay_category_aspects.py 183454 C:/dev/iMak_data/catalog/_input/ebay_tcg_filter_lists_api.json

= 既存 OAuth 流用 (check_csv_core.load_ebay_keys + get_oauth_token).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parent))
from check_csv_core import get_oauth_token, load_ebay_keys


def fetch_category_aspects(token: str, category_id: str, tree_id: str = "0") -> dict[str, Any]:
    """getItemAspectsForCategory call.

    tree_id = "0" (= EBAY_US marketplace tree).
    response = {"aspects": [{"localizedAspectName": str, "aspectValues": [{"localizedValue": str}], "aspectConstraint": {...}}, ...]}
    """
    url = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{tree_id}/get_item_aspects_for_category"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Accept-Language": "en-US",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    params = {"category_id": category_id}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_aspects(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """raw response → {aspect_name: {"values": [...], "constraint": {...}}}."""
    parsed: dict[str, dict[str, Any]] = {}
    for asp in raw.get("aspects", []):
        name = asp.get("localizedAspectName", "")
        if not name:
            continue
        values = [v.get("localizedValue", "") for v in asp.get("aspectValues", []) if v.get("localizedValue")]
        constraint = asp.get("aspectConstraint", {}) or {}
        parsed[name] = {
            "values": sorted(values),
            "constraint": {
                "aspect_required": constraint.get("aspectRequired", False),
                "aspect_data_type": constraint.get("aspectDataType", ""),
                "item_to_aspect_cardinality": constraint.get("itemToAspectCardinality", ""),
                "aspect_mode": constraint.get("aspectMode", ""),
                "aspect_usage": constraint.get("aspectUsage", ""),
                "expected_required_by_date": constraint.get("expectedRequiredByDate", ""),
                "aspect_enabled_for_variations": constraint.get("aspectEnabledForVariations", False),
            },
            "value_count": len(values),
        }
    return parsed


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python fetch_ebay_category_aspects.py <category_id> [output_json]")
        return 1
    category_id = sys.argv[1]
    output_path = (
        Path(sys.argv[2])
        if len(sys.argv) >= 3
        else Path(f"C:/dev/iMak_data/catalog/_input/ebay_category_{category_id}_aspects.json")
    )

    keys = load_ebay_keys()
    app_id = keys.get("AppID") or keys.get("APP_ID")
    app_secret = keys.get("AppSecret") or keys.get("CERT_ID")
    if not app_id or not app_secret:
        print(f"  ❌ AppID/AppSecret not found in keys (got: {list(keys.keys())})")
        return 2

    print(f"  → OAuth token 取得中 ...")
    token = get_oauth_token(app_id, app_secret)
    print(f"  ✅ token OK ({len(token)} chars)")

    print(f"  → getItemAspectsForCategory call (category_id={category_id}) ...")
    raw = fetch_category_aspects(token, category_id)
    aspects = parse_aspects(raw)
    print(f"  ✅ {len(aspects)} aspects 取得")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "category_id": category_id,
        "tree_id": "0",
        "marketplace_id": "EBAY_US",
        "aspect_count": len(aspects),
        "aspects": aspects,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  📝 saved → {output_path}")

    print()
    print("=" * 60)
    print(f"取得 aspects 一覧 ({len(aspects)} 件):")
    print("=" * 60)
    for name, info in sorted(aspects.items(), key=lambda x: -x[1]["value_count"]):
        req = "★" if info["constraint"]["aspect_required"] else " "
        print(f"  {req} {name:35s} = {info['value_count']:5d} values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
