"""iMakCatalog 共通API (lookup / search / upsert / フィルタ値変換).

各 listing スクリプト (psa_to_csv.py / gshock_to_csv.py 等) からの参照点。

設計原則:
  - ID完全一致 lookup を最優先 (フォールバック禁止)
  - 公式DB値をそのまま返す (推測なし)
  - eBay フィルタ値変換は ebay_filter_map 経由で集約

使用例:
    from iMakCatalog import api

    # ID完全一致 lookup
    result = api.lookup(category="one_piece_tcg", product_id="OP01-078")
    if result:
        specs = result["specs"]              # dict
        ebay_set = result["set_name"]        # 'Romance Dawn'

    # eBay フィルタ値変換
    ebay = api.to_ebay_value("one_piece_tcg", "rarity", "SR")
    # → "Super Rare"
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# ============================================================================
# DB 接続
# ============================================================================
_DB_PATH = Path(__file__).parent / "db" / "products.sqlite"
_SCHEMA_PATH = Path(__file__).parent / "db" / "schema.sql"


def _connect() -> sqlite3.Connection:
    """DB 接続を返す。未初期化なら schema.sql を実行。"""
    is_new = not _DB_PATH.exists()
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    if is_new and _SCHEMA_PATH.exists():
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    return conn


# ============================================================================
# Phase 0 スタブ実装
# ============================================================================
# 本実装は Phase 1 以降。今は I/F のみ提示。

def lookup(category: str, product_id: str) -> Optional[dict]:
    """ID完全一致 lookup. 未登録なら None.

    Args:
        category: 'one_piece_tcg' | 'pokemon_tcg' | 'gshock' | etc.
        product_id: 'OP01-078' | 'GA-2100-1A1' | etc.

    Returns:
        dict | None
        {
            "category": str,
            "product_id": str,
            "name": str,
            "name_jp": str | None,
            "set_name": str | None,           # eBay フィルタ値
            "set_name_official": str | None,
            "specs": dict,                     # JSON parsed
            "images": list[str],
            "source": str,
            "source_url": str | None,
            "updated_at": str,                 # ISO 8601
        }
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM products WHERE category = ? AND product_id = ?",
            (category, product_id),
        ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)
    finally:
        conn.close()


def search(category: str, name: str, limit: int = 10) -> list[dict]:
    """名前部分一致検索 (フォールバック用、誤マッチリスク高、慎重に)."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM products WHERE category = ? AND "
            "(name LIKE ? OR name_jp LIKE ?) LIMIT ?",
            (category, f"%{name}%", f"%{name}%", limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def upsert(
    category: str,
    product_id: str,
    name: str,
    specs: dict,
    name_jp: Optional[str] = None,
    set_name: Optional[str] = None,
    set_name_official: Optional[str] = None,
    card_set_id: Optional[int] = None,
    language: Optional[str] = None,
    images: Optional[list[str]] = None,
    source: str = "",
    source_url: Optional[str] = None,
) -> int:
    """商品マスター 1件 INSERT/UPDATE. スクレイパーから呼ぶ.

    Notes:
        - set_name は raw 公式値を入れる (set_name_official と同じ値で OK).
          eBay フィルタ値変換は lookup() が ebay_filter_map で実行する.

    Returns:
        products.id (新規/既存に関わらず)
    """
    now = datetime.now().isoformat(timespec="seconds")
    specs_json = json.dumps(specs, ensure_ascii=False)
    images_json = json.dumps(images or [], ensure_ascii=False)

    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT id FROM products WHERE category = ? AND product_id = ?",
            (category, product_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE products SET name = ?, name_jp = ?, set_name = ?, "
                "set_name_official = ?, card_set_id = ?, language = ?, "
                "specs = ?, images = ?, source = ?, source_url = ?, "
                "updated_at = ? WHERE id = ?",
                (name, name_jp, set_name, set_name_official, card_set_id,
                 language, specs_json, images_json, source, source_url, now,
                 existing["id"]),
            )
            row_id = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO products (category, product_id, name, name_jp, "
                "set_name, set_name_official, card_set_id, language, "
                "specs, images, source, source_url, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (category, product_id, name, name_jp, set_name,
                 set_name_official, card_set_id, language, specs_json,
                 images_json, source, source_url, now, now),
            )
            row_id = cur.lastrowid
        conn.commit()
        return row_id
    finally:
        conn.close()


def to_ebay_value(category: str, field: str, source_value: str) -> Optional[str]:
    """公式DB値 → eBay フィルタ表示値変換. マップ未登録なら None.

    例:
        to_ebay_value("one_piece_tcg", "set",
                      "BOOSTER PACK -AWAKENED PULSE- [FB01]")
        → "Awakened Pulse"
    """
    if not source_value:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT ebay_value FROM ebay_filter_map "
            "WHERE category = ? AND field = ? AND source_value = ?",
            (category, field, source_value),
        ).fetchone()
        return row["ebay_value"] if row else None
    finally:
        conn.close()


def register_filter_map(
    category: str,
    field: str,
    source_value: str,
    ebay_value: str,
    note: Optional[str] = None,
) -> None:
    """eBay フィルタ値マッピングを 1件登録 (重複時は何もしない)."""
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ebay_filter_map "
            "(category, field, source_value, ebay_value, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (category, field, source_value, ebay_value, note, now),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================================
# 内部ヘルパー
# ============================================================================
def _row_to_dict(row: sqlite3.Row) -> dict:
    """sqlite Row → 公開 dict.

    - specs / images は JSON parse
    - set_name は raw を ebay_filter_map で変換して返す (mapping なければ raw)
    - row.keys() に存在しないカラムは None で埋める (古い DB 互換)
    """
    keys = row.keys() if hasattr(row, "keys") else []

    def g(k, default=None):
        return row[k] if k in keys else default

    set_official = g("set_name_official")
    set_raw = g("set_name") or set_official
    category = g("category")
    set_ebay = None
    if set_official and category:
        # 1st: 公式原文ベタ一致 (例: "BOOSTER PACK -WINGS OF THE CAPTAIN- [OP-06]" → "Wings of the Captain")
        set_ebay = to_ebay_value(category, "set", set_official)
        if not set_ebay:
            # 2nd fallback: 公式原文末尾の set_code パターンから抽出
            #   ASCII: [OP-06] / [PRB-02] / [OP15-EB04]
            #   全角  : 【OP-06】 (JA detail で使われる)
            m = re.search(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]", set_official)
            if m:
                set_ebay = to_ebay_value(category, "set_code", m.group(1))
        if not set_ebay:
            # 3rd fallback: product_id の prefix を set_code として試行
            # (Pokemon 等、set_name_official に bracket コードが含まれない場合)
            # 例: "M2a-240" → "M2a"
            pid = g("product_id") or ""
            if "-" in pid:
                pid_prefix = pid.split("-", 1)[0]
                # Pokemon set_code は大文字小文字混在 (M2a, S8a, SV4 等) → 複数表記試行
                for cand in {pid_prefix, pid_prefix.upper(), pid_prefix.lower()}:
                    set_ebay = to_ebay_value(category, "set_code", cand)
                    if set_ebay:
                        break
                if not set_ebay:
                    # 末尾英字を小文字化したバリアント (M2A → M2a)
                    import re as _re
                    m_norm = _re.match(r"^([A-Z]+\d+)([A-Z])$", pid_prefix)
                    if m_norm:
                        set_ebay = to_ebay_value(
                            category, "set_code",
                            m_norm.group(1) + m_norm.group(2).lower(),
                        )
    return {
        "category": category,
        "product_id": g("product_id"),
        "name": g("name"),
        "name_jp": g("name_jp"),
        "set_name": set_ebay or set_raw,           # eBay 値があれば優先、なければ raw
        "set_name_official": set_official,
        "card_set_id": g("card_set_id"),
        "language": g("language"),
        "specs": json.loads(g("specs")) if g("specs") else {},
        "images": json.loads(g("images")) if g("images") else [],
        "source": g("source"),
        "source_url": g("source_url"),
        "updated_at": g("updated_at"),
    }


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    print(f"iMakCatalog API stub (Phase 0)")
    print(f"  DB path: {_DB_PATH}")
    print(f"  DB exists: {_DB_PATH.exists()}")
    if len(sys.argv) >= 3:
        cat, pid = sys.argv[1], sys.argv[2]
        result = lookup(cat, pid)
        print(f"\nlookup({cat!r}, {pid!r}):")
        print(json.dumps(result, ensure_ascii=False, indent=2)
              if result else "  None (未登録)")
    else:
        print("\n使用例: python api.py one_piece_tcg OP01-078")
