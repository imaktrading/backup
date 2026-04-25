"""eBay SOLD データDB（iMak Trading Japan 共通モジュール / SSOT）

`sold_data/*.xlsx` を全走査 → カード番号で集計 → JSON キャッシュ。

公開API:
  - build_index(force=False) -> dict            全xlsxを読んでインデックス構築（キャッシュ優先）
  - get_sold_stats(card_number, days=30) -> dict|None
                                                カード番号で直近30日のSold統計を返す
                                                {"count": n, "median_usd": x, "min": a, "max": b,
                                                 "last_sold_at": iso, "matched_titles": [..]}
  - refresh() -> dict                           強制再構築

設計:
  - 商品ID(eBay item_id)をユニークキー。複数xlsxに出現すれば上書き（最新優先）
  - カード番号抽出はTCG汎用（OP/ST/EB/PRB/FB/SB/GD/E + 数字-数字 or E-数字）
  - 数値のUSD価格は `販売価格` 列（すでに数値）をそのまま使う
  - 販売終了日 `販売終了日` はISO(UTC)文字列
"""
from __future__ import annotations
import os
import re
import json
import glob
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import openpyxl

_BASE = os.path.dirname(os.path.abspath(__file__))
SOLD_DIR = os.path.join(_BASE, "sold_data")
CACHE_PATH = os.path.join(_BASE, "sold_data_index.json")

# TCG カード番号パターン（eBayタイトルに頻出）
# 例: FB01-090, SB02-017, OP10-119, ST01-001, EB02-015, PRB01-001, GD01-010, E01-02, E-33, CP8
_CARD_NUM_PATTERNS = [
    re.compile(r'\b((?:OP|ST|EB|PRB|FB|SB|GD)\d{1,2}-\d{1,3})\b', re.IGNORECASE),
    re.compile(r'\b(E\d{1,2}-\d{1,3})\b', re.IGNORECASE),   # Energy Marker (E01-02)
    re.compile(r'\b(E-\d{1,3})\b', re.IGNORECASE),           # Energy Marker (E-33)
    re.compile(r'\b(CP\d{1,3})\b', re.IGNORECASE),           # Campaign
]

# xlsx の日本語ヘッダ → 英語キー
_COL_MAP = {
    "商品ID": "item_id",
    "商品名": "title",
    "商品画像": "image_url",
    "商品ページURL": "item_url",
    "セラーID": "seller_id",
    "カテゴリーID": "category_id",
    "販売価格": "price_usd",
    "送料": "shipping_usd",
    "販売終了日": "sold_at",
    "ウォッチ数": "watch_count",
    "SOLD数": "sold_count",
    "状態": "condition",
    "Feedback": "feedback",
}


def _extract_card_numbers(title: str) -> List[str]:
    if not title:
        return []
    found = []
    for pat in _CARD_NUM_PATTERNS:
        for m in pat.findall(title):
            n = m.upper().replace(" ", "")
            if n not in found:
                found.append(n)
    return found


def _read_xlsx(path: str) -> List[dict]:
    """xlsxを1行=1出品として辞書のリストで返す。ヘッダは日本語/英語どちらでも対応。"""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    header_raw = next(rows_iter, None)
    if not header_raw:
        return []
    # ヘッダ→英語キー
    header_keys = []
    for h in header_raw:
        h_str = (str(h) if h is not None else "").strip()
        header_keys.append(_COL_MAP.get(h_str, h_str))
    out = []
    for row in rows_iter:
        if not row or all(v is None for v in row):
            continue
        d = {k: v for k, v in zip(header_keys, row) if k}
        if "item_id" in d and d["item_id"]:
            d["_source_file"] = os.path.basename(path)
            out.append(d)
    return out


def _parse_sold_at(value) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    s = str(value).strip()
    # "2026-05-06T06:09:05.000Z" 形式はそのままISO扱い
    return s


def build_index(force: bool = False) -> Dict[str, dict]:
    """SOLDデータをすべて読み、カード番号別インデックスを構築。

    返り値: {
      "items": {item_id: 全列辞書},           # 生データ
      "by_card": {card_number: [item_id,...]}, # カード番号別
      "built_at": "ISO",
      "source_files": [..],
    }
    """
    # キャッシュ有効性: 全xlsxの最終更新時刻より新しいなら再利用
    xlsx_files = sorted(glob.glob(os.path.join(SOLD_DIR, "*.xlsx")))
    if not force and os.path.exists(CACHE_PATH):
        try:
            cache_mtime = os.path.getmtime(CACHE_PATH)
            if all(os.path.getmtime(p) <= cache_mtime for p in xlsx_files):
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    items: Dict[str, dict] = {}
    by_card: Dict[str, List[str]] = {}
    for p in xlsx_files:
        for d in _read_xlsx(p):
            item_id = str(d.get("item_id", "")).strip()
            if not item_id:
                continue
            d["item_id"] = item_id
            d["sold_at"] = _parse_sold_at(d.get("sold_at"))
            # 価格は数値化
            try:
                d["price_usd"] = float(d.get("price_usd") or 0)
            except (ValueError, TypeError):
                d["price_usd"] = 0.0
            items[item_id] = d  # 重複時は後勝ち（新しいxlsxが上書き）
            for cn in _extract_card_numbers(d.get("title", "")):
                by_card.setdefault(cn, [])
                if item_id not in by_card[cn]:
                    by_card[cn].append(item_id)

    index = {
        "items": items,
        "by_card": by_card,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "source_files": [os.path.basename(p) for p in xlsx_files],
    }
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ sold_data_index.json 保存失敗: {e}")
    return index


def refresh() -> Dict[str, dict]:
    return build_index(force=True)


def get_sold_stats(card_number: str, variant_keywords: Optional[List[str]] = None) -> Optional[dict]:
    """カード番号からSold統計を返す。該当なしはNone。

    設計:
      - xlsxは「出品単位」+ 累積SOLD数。販売日時は個別に不明なのでN日フィルタはしない
      - SOLD数>0 のみ集計（実売があるもの）
      - 中央値はSOLD数で加重（1つの出品が22個売れたら22点分のデータ）

    variant_keywords: 追加の必須キーワード（全てがタイトルに含まれる出品だけを集計）
                      例: ["ALTERNATE ART"]
    """
    if not card_number:
        return None
    card_number_norm = card_number.upper().strip()
    index = build_index()
    item_ids = index.get("by_card", {}).get(card_number_norm, [])
    if not item_ids:
        alt = card_number_norm.replace("-", "")
        for k, v in index.get("by_card", {}).items():
            if k.replace("-", "") == alt:
                item_ids = v
                break
    if not item_ids:
        return None

    items = index["items"]
    weighted_prices = []    # SOLD数分だけ複製した価格リスト（加重中央値用）
    listing_count = 0       # 該当出品数
    total_sold = 0          # 総販売個数
    titles = []
    for iid in item_ids:
        it = items.get(iid)
        if not it:
            continue
        title = it.get("title", "") or ""
        if variant_keywords:
            t_up = title.upper()
            if not all(kw.upper() in t_up for kw in variant_keywords):
                continue
        try:
            sold_n = int(it.get("sold_count") or 0)
        except (ValueError, TypeError):
            sold_n = 0
        if sold_n <= 0:
            continue
        p = float(it.get("price_usd") or 0)
        if p <= 0:
            continue
        # SOLD数で加重
        weighted_prices.extend([p] * sold_n)
        listing_count += 1
        total_sold += sold_n
        titles.append(title)

    if not weighted_prices:
        return None
    s = sorted(weighted_prices)
    return {
        "listing_count": listing_count,  # 該当出品数
        "total_sold": total_sold,        # 総販売個数（加重ベース）
        "median_usd": s[len(s) // 2],
        "min": s[0],
        "max": s[-1],
        "matched_titles": titles[:5],
    }


if __name__ == "__main__":
    import sys
    idx = refresh()
    print(f"✅ 構築完了: items={len(idx['items'])} cards={len(idx['by_card'])}")
    print(f"   source: {idx['source_files']}")
    # サンプル
    for cn in ("OP07-085", "OP09-001", "ST21-014", "FB01-090", "E01-02"):
        s = get_sold_stats(cn)
        if s:
            print(f"  [{cn}] 出品{s['listing_count']}/販売{s['total_sold']}個 中央値${s['median_usd']:.0f} (${s['min']:.0f}〜${s['max']:.0f})")
        else:
            print(f"  [{cn}] sold データなし")
