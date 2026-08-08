#!/usr/bin/env python3
"""graniph 出品側 scraper.

Inventory 側の graniph_scraper (1 SKU × 定期巡回 × qty=0 判定) とは別モジュール。
listing 側は 1商品 (12桁 item_code) × 全 variation を一度に取り出す用途。

依頼書: C:/dev/iMak_data/hq/requests/2026-08-08_graniph_listing_poc_response.md
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


@dataclass
class SizeRow:
    label_jp: str
    values_cm: dict  # {"SS": 62.5, "S": 65.5, ...}


@dataclass
class GraniphProduct:
    item_code: str          # 12桁 product URL 末尾 (例 019001564303)
    product_group_id: str   # 9桁 (JSON-LD productGroupID、例 019001564)
    color_code: str         # 3桁 (color_code、例 303)
    name_jp: str
    description_jp: str
    material_jp: str        # 生地表示 (例 "ポリエステル 65%  綿 35%")
    color_jp: str
    suggested_gender: str   # unisex / male / female
    price_regular_jpy: int
    price_sale_jpy: Optional[int]  # None if not on sale
    image_urls: list       # 全画像 URL
    sizes: list            # ["SS","S","M","L","XL"]  actually available (in stock)
    size_all_declared: list  # JSON-LD hasVariant 全 size (in-stock/out-of-stock 問わず)
    stock: dict            # {"SS": 20, "S": 33, ...}  real_quantity per size
    size_table: list       # [SizeRow(label_jp="着丈", values_cm={"SS": 62.5, ...}), ...]
    url: str


def _fetch_html(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return raw.decode("utf-8", errors="replace")


def _parse_json_ld(html: str) -> dict:
    m = re.search(
        r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not m:
        raise ValueError("JSON-LD block not found")
    data = json.loads(m.group(1))
    if isinstance(data, list):
        data = data[0]
    if data.get("@type") not in ("ProductGroup", "Product"):
        raise ValueError(f"Unexpected @type: {data.get('@type')}")
    return data


def _parse_price_data(html: str, color_code: str) -> tuple:
    """priceData JS object から (regular, sale_or_None) を返す.

    priceData のキーは 14桁 sku_code (item_code + color_code + size_code).
    color_code 一致する最初の entry を採用。
    """
    m = re.search(r"priceData\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not m:
        raise ValueError("priceData block not found")
    obj = json.loads(m.group(1))
    for sku_code, v in obj.items():
        if color_code and color_code in sku_code[9:12]:
            price = int(v.get("price", 0))
            sale = v.get("sale_price")
            sale = int(sale) if sale else None
            if sale and v.get("sale_flg"):
                return price, sale
            return price, None
    v = next(iter(obj.values()))
    price = int(v.get("price", 0))
    sale = v.get("sale_price")
    sale = int(sale) if sale else None
    return price, sale


def _parse_stocks(html: str, color_code: str) -> dict:
    """stocks JS object から {size_label: real_quantity} を返す."""
    m = re.search(r"const\s+stocks\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not m:
        return {}
    obj = json.loads(m.group(1))
    out = {}
    for sku_code, v in obj.items():
        if color_code and color_code not in sku_code[9:12]:
            continue
        sku_info = v.get("sku_info", {})
        size_label = sku_info.get("size_label") or ""
        qty = v.get("real_quantity", 0)
        if size_label:
            out[size_label] = qty
    return out


def _parse_size_table(html: str) -> list:
    """size-block-table-left (ラベル) + size-block-table-right (数値) を突合."""
    left_m = re.search(
        r"size-block-table-left(.*?)</table>", html, re.DOTALL,
    )
    right_m = re.search(
        r"size-block-table-right(.*?)</table>", html, re.DOTALL,
    )
    if not left_m or not right_m:
        return []
    labels = re.findall(r"<span>([^<]+)</span>", left_m.group(1))
    trs = re.findall(r"<tr[^>]*>(.*?)</tr>", right_m.group(1), re.DOTALL)
    if not trs:
        return []
    headers = re.findall(r"<th[^>]*>([^<]+)</th>", trs[0])
    if not headers:
        return []
    rows = []
    for tr in trs[1:]:
        tds = re.findall(r"<td[^>]*>([^<]+)</td>", tr)
        if tds:
            rows.append([t.strip() for t in tds])
    if len(rows) != len(labels):
        raise ValueError(
            f"size table label/row mismatch: labels={len(labels)} rows={len(rows)}"
        )
    result = []
    for label, row in zip(labels, rows):
        values_cm = {}
        for size, val in zip(headers, row):
            try:
                values_cm[size] = float(val)
            except ValueError:
                pass
        result.append(SizeRow(label_jp=label, values_cm=values_cm))
    return result


def _extract_ids(item_code: str, jsonld: dict) -> tuple:
    pg_id = str(jsonld.get("productGroupID") or "").strip()
    if not pg_id:
        pg_id = item_code[:9]
    color_code = ""
    if len(item_code) >= 12:
        color_code = item_code[9:12]
    return pg_id, color_code


def scrape(url: str) -> GraniphProduct:
    """graniph PDP URL → GraniphProduct."""
    m = re.search(r"/item-detail/(\d{12})", url)
    if not m:
        raise ValueError(f"Not a graniph item-detail URL: {url}")
    item_code = m.group(1)
    html = _fetch_html(url)
    jsonld = _parse_json_ld(html)
    pg_id, color_code = _extract_ids(item_code, jsonld)
    variants = jsonld.get("hasVariant", []) or []
    size_all = [v.get("size", "") for v in variants if v.get("size")]
    stock = _parse_stocks(html, color_code)
    sizes_in_stock = [s for s in size_all if stock.get(s, 0) > 0]
    price_reg, price_sale = _parse_price_data(html, color_code)
    size_table = _parse_size_table(html)
    images = jsonld.get("image") or []
    if isinstance(images, str):
        images = [images]
    audience = jsonld.get("audience", {}) or {}
    return GraniphProduct(
        item_code=item_code,
        product_group_id=pg_id,
        color_code=color_code,
        name_jp=jsonld.get("name", ""),
        description_jp=jsonld.get("description", ""),
        material_jp=jsonld.get("material", ""),
        color_jp=jsonld.get("color", ""),
        suggested_gender=audience.get("suggestedGender", "unisex"),
        price_regular_jpy=price_reg,
        price_sale_jpy=price_sale,
        image_urls=images,
        sizes=sizes_in_stock,
        size_all_declared=size_all,
        stock=stock,
        size_table=size_table,
        url=url,
    )
