"""iMakCatalog (= 共有 products.sqlite) read-only 参照 wrapper.

iMak Trading Japan の商品マスター。 共有 path:
  `C:/dev/iMak_data/catalog/products.sqlite` (= 全 worktree 共有)

重複くん利用方針 (= 5/27 ユーザー指摘):
- title regex / Browse API Item Specifics で card_id 取れない / 部分形式の場合に
  catalog 経由で **公式 product_id を復元**
- read-only / 接続後 close 必須 (= 他 worker への影響ゼロ)

catalog schema (= 確認済):
- products.product_id = 公式 card ID / 商品 ID (例: `OP06-022`, `GD02-070`)
- products.category = `one_piece_tcg` / `pokemon_tcg` / `dragonball_scg` / `gundam_tcg` 等
- ebay_filter_map (= category, field, source_value, ebay_value):
  - field='set_code' で eBay Set aspect 表示名 ↔ 内部 set_code の双方向 map
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Tuple

CATALOG_DB_PATH = Path(r"C:/dev/iMak_data/catalog/products.sqlite")

# === iMakCatalog 越境 import path (= 5/27 Phase 1j 依頼で DON lookup 統合) ===
IMAK_CATALOG_DIR = r"C:/dev/iMak_catalog/iMakCatalog"

# 完全形 card_id (= prefix + 数字 + ハイフン + (= 修飾) 数字、 例 OP08-106 / GD02-070)
_FULL_RE = re.compile(r"^[A-Z]+\d*-[A-Z]*\d+$", re.IGNORECASE)
# 公式 slash 形 (= 連番 / prefix、 例 001/SM-P / 001/M-P = Pokemon Promo 系)
# Catalog SSOT (= 2026-05-27): 正規化禁止、 公式形そのまま catalog で verify
_SLASH_RE = re.compile(r"^\d+/[A-Z]+-?[A-Z]?$", re.IGNORECASE)
# Pokemon 公式 "番号/総数" 形式 (= 例 102/100 / 086/079) — 5/27 出品くん修正後
# 数字/数字 のみ。 _SLASH_RE (連番/prefix) との衝突を避けるため厳密に数字 only
_NUM_OVER_NUM_RE = re.compile(r"^\d+/\d+$")
# 連番のみ (= digits)
_DIGITS_RE = re.compile(r"^\d+$")

# Phase 1k (= 2026-05-27): catalog 直接 fuzzy lookup 用 token regex.
# 緩い pattern で title / aspect 内 token 全 hit → 各 token を valid_pids で完全一致 verify.
# 区切り = `-` / `_` / `/`、 alphanumeric が前後にある token のみ採用。
# 例:
#   "PSA 10 Pokemon SV1V-086 Drowzee" → ['SV1V-086']
#   "Casio DW-5600-1JF" → ['DW-5600-1JF']
#   "Uniqlo UT E420005-000" → ['E420005-000']
#   "PSA 10" / "tag" → match なし (= 区切り無の単語は skip)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_/][A-Za-z0-9]+)+")


def open_catalog_readonly(path: Path = CATALOG_DB_PATH) -> sqlite3.Connection:
    """共有 catalog SQLite を read-only モードで開く.

    URI mode で `?mode=ro` を付け、 SQLite レベルで write を block。
    他 worker (= Catalog Claude) の書込 cycle と衝突しない。
    """
    if not path.exists():
        raise FileNotFoundError(f"catalog DB not found: {path}")
    uri = f"file:{path.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def load_set_name_map(con: sqlite3.Connection) -> Dict[str, Tuple[str, str]]:
    """`ebay_filter_map` から eBay Set 表示名 → (category, set_code) を構築.

    返り値 key = eBay listing の Set aspect 表示値 (= 例 "Wings of the Captain")
    返り値 value = (category, set_code) — 例 ("one_piece_tcg", "OP-06")
    """
    cur = con.cursor()
    cur.execute(
        "SELECT category, source_value, ebay_value FROM ebay_filter_map "
        "WHERE field='set_code'"
    )
    out: Dict[str, Tuple[str, str]] = {}
    for cat, sv, ev in cur.fetchall():
        if ev:
            out[ev.strip()] = (cat or "", (sv or "").strip())

    # 2026-06-09 fallback: ebay_filter_map に set_code 行が無いセット (M1S/M2a 等 最近のもの) を
    # products.specs.set_name_ebay から補完 (= set_map 漏れによる KEY1 取得失敗の救済)。
    # product_id prefix を set_code とする (例 'M1S-079' → 'M1S')。ebay_filter_map 既存値は上書きしない。
    # dedup の set_map 専用 (生成・catalog 本体には一切影響しない、 read のみ)。
    import re as _re_sm
    try:
        cur.execute(
            "SELECT category, product_id, json_extract(specs,'$.set_name_ebay') "
            "FROM products WHERE product_id LIKE '%-%' "
            "AND json_extract(specs,'$.set_name_ebay') IS NOT NULL"
        )
        for cat, pid, sne in cur.fetchall():
            if not sne:
                continue
            sne = sne.strip()
            if not sne or sne in out:
                continue
            m = _re_sm.match(r"^([A-Za-z0-9]+)-", pid or "")
            if m:
                out[sne] = (cat or "", m.group(1))
    except Exception:
        pass  # fallback 失敗時は既存挙動 (ebay_filter_map のみ)
    return out


def load_valid_product_ids(con: sqlite3.Connection) -> FrozenSet[str]:
    """products テーブル全 product_id を 大文字 set として返す.

    復元候補が catalog に登録済か verify するため。
    """
    cur = con.cursor()
    cur.execute(
        "SELECT product_id FROM products "
        "WHERE product_id IS NOT NULL AND product_id != ''"
    )
    return frozenset((r[0] or "").upper() for r in cur.fetchall())


def reconstruct_card_id(
    card_number: str,
    set_aspect_value: str,
    set_map: Dict[str, Tuple[str, str]],
    valid_pids: FrozenSet[str],
) -> Tuple[Optional[str], str]:
    """Item Specifics の Card Number + Set から card_id 復元.

    Returns: (card_id, reason)
    - 完全形 + catalog 登録あり → (id, "完全形 verified")
    - 完全形 + catalog 未登録 → (id, "完全形 未登録") (= 採用するか呼出側判断)
    - 連番のみ + Set 経由復元 + catalog 登録あり → (id, "連番+Set (w=N)")
    - 連番のみ + Set 経由復元 + 未登録 → (id, "連番+Set 未登録")
    - 復元不能 → (None, "<理由>")
    """
    cn = (card_number or "").strip()
    set_v = (set_aspect_value or "").strip()
    if not cn:
        return None, "no Card Number"

    # Phase 1k v2 (= 2026-05-27): Pokemon 公式 "番号/総数" 形式 入力時は分子のみ採用.
    # 出品くん 5/27 修正で eBay C:Card Number 列に `102/100` 形式書込 (= SEO 用) が始まる。
    # Set aspect 経由復元のため、 入力 normalize で 「102/100」 → 「102」 に変換。
    # 既存 _SLASH_RE (= `001/SM-P` 連番/prefix) と区別: こちらは数字/数字 only.
    if _NUM_OVER_NUM_RE.match(cn):
        cn = cn.split("/", 1)[0]  # 分子のみ採用 → _DIGITS_RE 経路に流す

    # 完全形 (prefix-連番、 例 OP08-106) → catalog verify
    if _FULL_RE.match(cn):
        u = cn.upper()
        if u in valid_pids:
            return u, "完全形 verified"
        return u, "完全形 未登録"

    # 公式 slash 形 (連番/prefix、 例 001/SM-P) → catalog verify (= 正規化なし)
    if _SLASH_RE.match(cn):
        u = cn.upper()
        if u in valid_pids:
            return u, "公式 slash 形 verified"
        return u, "公式 slash 形 未登録"

    # 連番のみ → Set 経由復元
    if _DIGITS_RE.match(cn):
        if set_v not in set_map:
            return None, f"Set 未登録: {set_v[:40]!r}"
        _, set_code = set_map[set_v]
        if not set_code:
            return None, f"set_code 空"
        # 候補生成: catalog category 別 format 差を吸収 (= 正規化でなく candidate 試行)
        prefix_no_dash = set_code.replace("-", "").upper()
        set_code_upper = set_code.upper()
        for width in (3, 4, 2):
            cn_padded = cn.zfill(width)
            # 候補 A: prefix-連番 (= 例 OP06-022 / GD02-070)
            for candidate in (
                f"{prefix_no_dash}-{cn_padded}",       # OP06-022
                f"{cn_padded}/{set_code_upper}",       # 001/SM-P (= Pokemon promo 公式形)
                f"{set_code_upper}-{cn_padded}",       # S6a-001
            ):
                if candidate.upper() in valid_pids:
                    return candidate.upper(), f"連番+Set verified ({candidate})"
        # catalog 未登録 fallback (= 旧挙動、 prefix-連番 形式採用)
        return f"{prefix_no_dash}-{cn.zfill(3)}", "連番+Set 未登録"

    return None, f"format 不明: {cn[:20]!r}"


def find_product_id_in_text(
    text: str,
    valid_pids: FrozenSet[str],
) -> Optional[Tuple[str, str]]:
    """Phase 1k: text 内の token を catalog valid_pids で完全一致 verify.

    緩い regex で alphanumeric + 区切り (= `-` / `_` / `/`) + alphanumeric の token を
    全 hit させ、 各 token を大文字化して valid_pids 照合。 最長一致を優先。

    cover 可能:
    - Pokemon: `SV1V-086` / `S6a-001` / `SV9-102` 等 (= 既存 _FULL_RE で漏れた alpha 混在)
    - One Piece: `OP08-106` / `DON-OP15-002`
    - DragonBall: `FB02-049_FB08` (= アンダースコア suffix 込)
    - Gundam: `GD02-070` / `RP-004`
    - G-shock: `DW-5600-1JF` / `AW-500BB-1E` (= 多段ハイフン)
    - Uniqlo UT: `E420005-000`

    cover 不能 (= 別 logic 必要):
    - Yu-Gi-Oh: 8 桁数字のみ (lookup_yugioh 経由)
    - Montbell: 7 桁数字のみ
    - Workman: `workman:NNNNN` colon 区切り

    Returns: (product_id, reason) or None.
    """
    if not text or not valid_pids:
        return None
    candidates = _TOKEN_RE.findall(text)
    # 最長 token 優先 (= 部分一致より完全一致が確実)
    candidates.sort(key=len, reverse=True)
    for token in candidates:
        u = token.upper()
        if u in valid_pids:
            return u, "catalog token verified"
    return None


# ============================================================================
# Catalog category 別 lookup wrapper (= 越境 read-only import for iMakCatalog/integrations)
# ============================================================================

def _import_catalog_lookup(name: str):
    """iMakCatalog の lookup_* 関数を遅延 import."""
    if IMAK_CATALOG_DIR not in sys.path:
        sys.path.insert(0, IMAK_CATALOG_DIR)
    try:
        from integrations import psa_to_csv as _cat_psa
    except ImportError as exc:
        raise RuntimeError(
            f"iMakCatalog psa_to_csv import 失敗: {exc} (path={IMAK_CATALOG_DIR})"
        )
    fn = getattr(_cat_psa, name, None)
    if fn is None:
        raise RuntimeError(f"iMakCatalog に関数 {name!r} なし")
    return fn


def lookup_don(
    brand: str,
    subject: str,
    verbose: bool = False,
    image_url: Optional[str] = None,
) -> Optional[Dict]:
    """DON カード lookup. iMakCatalog 側 lookup_don wrapper (= 5/27 Phase 1j).

    Phase 1r (= 5/28): image_url 引数追加. Catalog B 完成 (= lookup_don が
    image_url kwarg 対応) 時に signature inspect で自動的に渡す forward-compat 設計.
    Catalog 未対応 + image_url なし → 既存 (brand, subject) 呼出に fallback.
    """
    fn = _import_catalog_lookup("lookup_don")
    import inspect as _inspect
    sig = _inspect.signature(fn)
    if "image_url" in sig.parameters and image_url:
        return fn(brand, subject, verbose=verbose, image_url=image_url)
    return fn(brand, subject, verbose=verbose)


def lookup_yugioh(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = False,
) -> Optional[Dict]:
    """Yu-Gi-Oh! lookup. PSA subject 経由 name fuzzy match (= 5/27 Phase 1k).

    Yu-Gi-Oh は Konami numeric ID (= title に出ない) のため subject 必須。
    CSV に `C:PSA Subject` 列が無い場合は呼ばないこと (= 結果 None になる)。
    """
    return _import_catalog_lookup("lookup_yugioh")(
        brand, card_number, subject=subject, verbose=verbose
    )


def lookup_pokemon(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = False,
) -> Optional[Dict]:
    """Pokemon lookup wrapper (= 5/27 Phase 1k)."""
    return _import_catalog_lookup("lookup_pokemon")(
        brand, card_number, subject=subject, verbose=verbose
    )


def lookup_dragonball(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = False,
) -> Optional[Dict]:
    """Dragon Ball SCG lookup wrapper."""
    return _import_catalog_lookup("lookup_dragonball")(
        brand, card_number, subject=subject, verbose=verbose
    )


def lookup_gundam(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = False,
) -> Optional[Dict]:
    """Gundam Card Game lookup wrapper."""
    return _import_catalog_lookup("lookup_gundam")(
        brand, card_number, subject=subject, verbose=verbose
    )


def lookup_one_piece(
    brand: str,
    card_number: str,
    subject: str = "",
    verbose: bool = False,
) -> Optional[Dict]:
    """One Piece TCG lookup wrapper (= 5/28 Phase 1q 追加).

    brand から set_code 抽出 → base product_id 組立 → variant suffix 試行。
    例: brand="ONE PIECE JAPANESE PROMOS" + subject="MARCO WEEKLY SHONEN JUMP-#8"
        → "OP08-002_P_LF" 等の確定 product_id 返却。
    """
    return _import_catalog_lookup("lookup_one_piece")(
        brand, card_number, subject=subject, verbose=verbose
    )


# ============================================================================
# variant_meta wrapper (= Phase 1n / 5/27 ①連動)
# Catalog `integrations/variant_meta.py` の関数を越境 read-only import.
# Catalog SSOT 原則準拠 (= 重複くん側で正規化せず、 公式 variant_code を使う).
# ============================================================================

def _import_catalog_variant_meta(name: str):
    if IMAK_CATALOG_DIR not in sys.path:
        sys.path.insert(0, IMAK_CATALOG_DIR)
    try:
        from integrations import variant_meta as _vm
    except ImportError as exc:
        raise RuntimeError(
            f"iMakCatalog variant_meta import 失敗: {exc} (path={IMAK_CATALOG_DIR})"
        )
    fn = getattr(_vm, name, None)
    if fn is None:
        raise RuntimeError(f"iMakCatalog variant_meta に関数 {name!r} なし")
    return fn


def extract_variant_alias(subject: str) -> Optional[str]:
    """PSA Subject から variant_code を抽出 (= catalog Tier 3 表記揺れ吸収).

    Returns: variant_code (= 'AR' / 'SAR' / 'Promo' etc.) or None
    """
    if not subject:
        return None
    return _import_catalog_variant_meta("extract_variant_alias")(subject)


def get_variant_meta(
    product_id: str,
    variant_code: str,
    category: str,
) -> Optional[Dict]:
    """catalog products.specs.variants[variant_code] のメタを取得.

    Returns: {'features': ..., 'finish': ..., 'rarity_ebay': ..., 'title_token': ...}
    or None (= variant 未登録 / catalog 未投入カテゴリ)
    """
    if not (product_id and variant_code and category):
        return None
    return _import_catalog_variant_meta("get_variant_meta")(
        product_id, variant_code, category
    )


def get_catalog_variants(
    product_id: str,
    category: str,
) -> Optional[Dict]:
    """catalog products.specs.variants JSON 全体を取得 (= image_phash 含む全 variant メタ).

    Phase 1o (= 5/28 ③ Phase C cycle 統合) 用。 `get_variant_meta` は variant 単体取得、
    本 fn は **全 variant dict** を返す (= 画像 hash 比較で複数 variant 比較に必要)。

    Returns:
        {'AR': {'features': ..., 'image_phash': '...'},
         'SAR': {'features': ..., 'image_phash': '...'},
         ...} or None (= products 未登録 / variants 列 NULL / parse 失敗)
    """
    if not (product_id and category):
        return None
    try:
        con = open_catalog_readonly()
    except Exception:
        return None
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT specs FROM products "
            "WHERE UPPER(product_id) = ? AND category = ? LIMIT 1",
            (product_id.upper(), category),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        import json as _json
        try:
            specs = _json.loads(row[0])
        except Exception:
            return None
        variants = specs.get("variants")
        if not isinstance(variants, dict):
            return None
        return variants
    finally:
        con.close()


def get_category_by_product_id(product_id: str) -> Optional[str]:
    """catalog products.product_id から category を逆引き.

    重複くん側で CSV row に category 列無いため、 key1 (= product_id) 確定後に
    catalog で category 判定して variant_meta lookup に渡すため。
    """
    if not product_id:
        return None
    try:
        con = open_catalog_readonly()
    except Exception:
        return None
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT category FROM products WHERE UPPER(product_id) = ? LIMIT 1",
            (product_id.upper(),),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        con.close()
