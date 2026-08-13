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
# 2026-05-03: worktree 跨ぎ共有のため絶対パス化 (Catalog 切出 Phase 2)
# 旧 _DB_PATH = Path(__file__).parent / "db" / "products.sqlite"
_DB_PATH = Path(r"C:/dev/iMak_data/catalog/products.sqlite")
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


def search_prefix(category: str, prefix: str, limit: int = 100) -> list[dict]:
    """product_id が prefix で始まる record を全件返す (SSOT source を跨いだ variant 列挙用).

    用途: bandai_tcg_plus/dbfw_official 両ソースにまたがる同一 card_number 系の全 variant を
    lookup 側で列挙するとき (2026-08-10 dragonball dummy_s1 案C, 窓口GO).
    副作用: LIKE 検索なので prefix 内の '%' / '_' メタ文字は escape しない (呼び出し側は
    正規化された prefix を渡す).
    """
    if not prefix:
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM products WHERE category = ? AND product_id LIKE ? "
            "ORDER BY product_id LIMIT ?",
            (category, f"{prefix}%", limit),
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
    name_en: Optional[str] = None,
    name_en_source: Optional[str] = None,
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
            # name_en / name_en_source は呼び出し側が明示的に渡した時のみ更新.
            # スクレイパーの再走で None を渡された時に既存翻訳を破壊しない.
            if name_en is not None or name_en_source is not None:
                conn.execute(
                    "UPDATE products SET name = ?, name_jp = ?, name_en = ?, "
                    "name_en_source = ?, set_name = ?, set_name_official = ?, "
                    "card_set_id = ?, language = ?, specs = ?, images = ?, "
                    "source = ?, source_url = ?, updated_at = ? WHERE id = ?",
                    (name, name_jp, name_en, name_en_source, set_name,
                     set_name_official, card_set_id, language, specs_json,
                     images_json, source, source_url, now, existing["id"]),
                )
            else:
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
                "name_en, name_en_source, set_name, set_name_official, "
                "card_set_id, language, specs, images, source, source_url, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (category, product_id, name, name_jp, name_en, name_en_source,
                 set_name, set_name_official, card_set_id, language, specs_json,
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


_SET_CODE_RE = re.compile(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]")


def derive_set_name_ebay(category: str, set_name_official: Optional[str],
                         product_id: Optional[str]) -> Optional[str]:
    """clean な eBay facet set 名を導出 (filter_map で一度だけ変換). 無ければ None=空欄.

    SSOT(出品は参照のみ)用。_row_to_dict と同順:
      ①set_official 完全一致 → ②[CODE]→set_code → ③product_id prefix
    再録は set_official が再録先 booster 名のため ① で再録先 clean 名になる。
    filter_map miss は **None(fail-closed)**. raw に degrade させない。
    scraper の取り込み + migration の両方から呼ぶ共通 helper.
    """
    if set_name_official:
        v = to_ebay_value(category, "set", set_name_official)
        if v:
            return v
        m = _SET_CODE_RE.search(set_name_official)
        if m:
            v = to_ebay_value(category, "set_code", m.group(1))
            if v:
                return v
    if product_id and "-" in product_id:
        pref = product_id.split("-", 1)[0]
        for cand in {pref, pref.upper(), pref.lower()}:
            v = to_ebay_value(category, "set_code", cand)
            if v:
                return v
    return None


_RARITY_STAR_RE = re.compile(r"[★☆]+\s*$")


def derive_rarity_ebay(category: str, rarity_raw: Optional[str]) -> Optional[str]:
    """公式 rarity コード → eBay canonical 値. filter_map miss は None (fail-closed).

    ★ は **公式の rarity 語彙ではない**。公式 dbs-cardgame.com/fw の cardlist
    rarity filter は L / C / UC / R / SR / SCR / PR の 7 値のみ (2026-08-13 実取得)。
    ★ は parallel / alt-art の刷り違いを card list 表示上で示すマーカーなので、
    base コードに落としてから filter_map を引く (★ の意味は Features 側で表現)。

    derive_set_name_ebay と同じ SSOT 方針: 出品側は specs.rarity_ebay を
    そのまま消費し、変換しない (契約 v1.2 §1-1)。
    """
    if not rarity_raw:
        return None
    base = _RARITY_STAR_RE.sub("", rarity_raw.strip()).strip()
    if not base:
        return None
    return to_ebay_value(category, "rarity", base)


# B層 verified status (= b_layer_status テーブル. 2026-06-07 新設)
#   4状態: unverified / verified_auto / verified_manual / disputed
#   出品ゲートは "強制" を listing/HQ 側が担い、ここは status の "参照" を提供する。
_BLOCKING_STATUS = {"unverified", "disputed"}


def field_status(category: str, product_id: str, field: str) -> Optional[str]:
    """B層フィールドの検証 status を返す. 未記録なら None.

    field: 'name_en' | 'set_name_ebay' 等.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT status FROM b_layer_status "
            "WHERE category = ? AND product_code = ? AND field = ?",
            (category, product_id, field),
        ).fetchone()
        return row["status"] if row else None
    except sqlite3.OperationalError:
        # テーブル未作成環境 (migration 未適用) では None
        return None
    finally:
        conn.close()


def is_listable(category: str, product_id: str,
                fields: tuple[str, ...] = ("name_en", "set_name_ebay")) -> bool:
    """出品可否の "参照" 判定. 対象 B層フィールドが unverified / disputed を含めば False.

    注: ゲートの "強制" は listing/HQ 側 (新規・relist 両経路) の責務.
        昇格 (verified_auto/verified_manual) 完了前に強制すると大量ブロックになるため、
        本ヘルパーは判定材料の提供のみ (呼び出し側がゲート有効化時期を制御する).
        status 未記録(None)のフィールドは判定対象外 (= ブロックしない).
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT status FROM b_layer_status "
            "WHERE category = ? AND product_code = ? AND field IN (%s)"
            % ",".join("?" * len(fields)),
            (category, product_id, *fields),
        ).fetchall()
        return not any(r["status"] in _BLOCKING_STATUS for r in rows)
    except sqlite3.OperationalError:
        return True  # テーブル未作成 = ゲート無効 (従来動作)
    finally:
        conn.close()


def register_filter_map(
    category: str,
    field: str,
    source_value: str,
    ebay_value: str,
    note: Optional[str] = None,
) -> None:
    """eBay フィルタ値マッピングを 1件 upsert.

    重複 (同 category/field/source_value) 時は ebay_value / note を **更新** する
    (yaml = SSOT。旧実装の INSERT OR IGNORE は yaml 修正後 loader を回しても
    既存行を更新せず yaml↔DB 乖離を招いた=2026-06-08 Dragonball FB/FS 誤set名の真因)。
    created_at は初回値を保持。
    """
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO ebay_filter_map "
            "(category, field, source_value, ebay_value, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(category, field, source_value) DO UPDATE SET "
            "ebay_value=excluded.ebay_value, note=excluded.note",
            (category, field, source_value, ebay_value, note, now),
        )
        conn.commit()
    finally:
        conn.close()


# ============================================================================
# Atomic 部分 update (specs 内 field のみ、他 field を保護)
# ============================================================================
def update_active_status(category: str, product_id: str,
                          is_active: bool, reason: str = "") -> bool:
    """specs.is_active_msrp + specs.deactivation_reason + specs.last_active_check を atomic 更新.

    背景 (HQ Phase 2):
        Inventory が AJAX 連敗 / 全 variant 7 日連続 no-stock で廃番検知した時に
        catalog 側へ通知する経路. api.upsert() は specs 全体上書きで他 field を壊す
        ので、専用 update API を用意.

    Args:
        category: 'workman' 等
        product_id: 'workman:series:67335' 等
        is_active: True=active / False=廃番
        reason: 廃番理由 (任意、log 用)

    Returns:
        True: 更新成功, False: 該当 record なし
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT specs FROM products WHERE category = ? AND product_id = ?",
            (category, product_id),
        ).fetchone()
        if row is None:
            return False
        try:
            specs = json.loads(row["specs"]) if row["specs"] else {}
        except Exception:
            specs = {}
        specs["is_active_msrp"] = bool(is_active)
        specs["last_active_check"] = datetime.now().isoformat(timespec="seconds")
        if reason:
            specs["deactivation_reason"] = reason
        elif "deactivation_reason" in specs and is_active:
            # active に戻ったら理由 clear
            specs.pop("deactivation_reason", None)
        conn.execute(
            "UPDATE products SET specs = ?, updated_at = ? "
            "WHERE category = ? AND product_id = ?",
            (json.dumps(specs, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds"),
             category, product_id),
        )
        conn.commit()
        return True
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
        "name_en": g("name_en"),                   # NULL なら呼び出し側で fallback
        "name_en_source": g("name_en_source"),     # 出典 / 翻訳手段の透明化
        "set_name": set_ebay or set_raw,           # eBay 値があれば優先、なければ raw
        "set_name_official": set_official,
        "card_set_id": g("card_set_id"),
        "language": g("language"),
        "specs": json.loads(g("specs")) if g("specs") else {},
        "images": json.loads(g("images")) if g("images") else [],
        "source": g("source"),
        "source_url": g("source_url"),
        "updated_at": g("updated_at"),
        # variants: variant_meta.get_variant_meta() で利用、 旧 DB 互換で None
        "variants": json.loads(g("variants")) if g("variants") else None,
        # alias_of: 別名(短縮形)が指す canonical product_id (gshock dedupe B案 / 2026-06-11)
        #           NULL = canonical 自身 or 独立商品。旧 DB 互換で None。
        "alias_of": g("alias_of"),
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
