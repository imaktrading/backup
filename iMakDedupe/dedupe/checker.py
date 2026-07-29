"""重複くん main logic + CLI.

Phase 1 本実装:
1. 既存 HIGH/LOW/公式 スプシ 全 worksheet から (title, url) 読込 → index 化
2. 中間スプシ 全 worksheet を巡回、 各 row を classify_row() で分類
3. flag を中間スプシ U 列 (= 「既存出品 chk」) に書込

CLI 引数:
- `--tab <name>`: 中間スプシの 1 タブのみ突合 (= POC / 動作確認用)
- `--dry-run`: 書込せず判定結果サマリーのみ表示
- 引数なし = 中間スプシ 全タブ突合 + U 列書込
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .extractors import (
    extract_gshock_model,
    extract_mercari_url_key,
    extract_tcg_id,
    extract_variant,
)


# flag 文字列 (= 中間スプシに書込む値、 single source of truth)
FLAG_DUP_URL = "重複 URL"
FLAG_DUP_CARD_ID = "重複 card_id"
FLAG_DUP_MODEL = "重複 型番"
FLAG_DUP_CANONICAL = "重複"  # Step 4 (= 2026-06-10): 単一 KEY 化、 種別問わず重複
FLAG_NEW = ""  # 新規 (= 重複なし、 出品候補として OK)
FLAG_UNKNOWN = "不明"  # extractor hit せず、 user 目視判断


# KEY 列 (Phase 1a) の type tag
KEY_TYPE_CARD = "card"
KEY_TYPE_MODEL = "model"
KEY_TYPE_URL = "url"
KEY_TYPE_NONE = ""

# Step 4 (= 2026-06-10): canonical KEY 型 tag.
# product_id = catalog-backed (= TCG / G-shock suffix 込)、
# url = non-catalog (= mercari item:/shops: prefix)、
# "" = 解決不能 = fail-closed.
KEY_TYPE_PRODUCT_ID = "product_id"
KEY_TYPE_URL_KEY = "url"
KEY_TYPE_FAILED = ""


def extract_priority_key(title: str, url: str) -> tuple:
    """KEY1 列に書込む 1 値を 優先順序 card_id > 型番 > URL で抽出.

    返り値: (key_string, key_type)
    - key_type: "card" / "model" / "url" / "" (= 抽出失敗)
    - 失敗時は (None, "")
    """
    tcg = extract_tcg_id(title)
    if tcg:
        return tcg, KEY_TYPE_CARD
    gshock = extract_gshock_model(title)
    if gshock:
        return gshock, KEY_TYPE_MODEL
    url_key = extract_mercari_url_key(url)
    if url_key:
        return url_key, KEY_TYPE_URL
    return None, KEY_TYPE_NONE


def extract_priority_key2(title: str, url: str, extra_text: str = "") -> tuple:
    """Phase 1f: (KEY1, KEY1_type, KEY2_variant) 3-tuple を抽出.

    - KEY1: extract_priority_key と同じ (card > model > url)
    - KEY2: title + extra_text (= Subject / Features 等の aspect 値) から variant code
      - KEY1 が空なら KEY2 も空 (= 突合対象外、 fail-closed)
      - KEY1 が URL 型 (= card_id じゃない通常 listing) なら KEY2 = "" (= variant 概念なし)
    """
    key1, type1 = extract_priority_key(title, url)
    if not key1:
        return None, KEY_TYPE_NONE, ""
    # variant は card_id / 型番 にのみ意味あり (= TCG / 限定 model の rarity 識別)。
    # URL 型 (= mercari 個別 listing) は KEY2 不要 = "" (= 単一 listing としてのみ識別)
    if type1 == KEY_TYPE_URL:
        return key1, type1, ""
    # title から variant 抽出、 取れなければ extra_text (= Subject 等) から
    variant = extract_variant(title)
    if not variant and extra_text:
        variant = extract_variant(extra_text)
    return key1, type1, variant


def classify_existing_key(key: str) -> str:
    """既存スプシ KEY 列 1 セル値 を url/card/model のいずれか判定.

    Phase 1b で KEY 列読込時 に 各値を 3 つの set に振分けるのに使う。
    手動補完で自由文字列入った場合は "unknown" を返す (= index に入れない)。
    """
    if not key:
        return KEY_TYPE_NONE
    key = key.strip()
    if not key:
        return KEY_TYPE_NONE
    if key.startswith("item:") or key.startswith("shops:"):
        return KEY_TYPE_URL
    if extract_gshock_model(key):
        return KEY_TYPE_MODEL
    if extract_tcg_id(key):
        return KEY_TYPE_CARD
    return "unknown"


# ============================================================================
# Step 4 (= 2026-06-10): canonical KEY 単一化 API
# spec: iMak_data/KEY_REDESIGN_SPEC.md §2
# resolver 経由 (= 再導出禁止、 SSOT 中央集約)
# ============================================================================

def classify_canonical_key(key: str) -> str:
    """canonical KEY (= 単一文字列) を product_id / url / failed のいずれか分類.

    Step 4 仕様:
    - "" / 空白 → KEY_TYPE_FAILED (= 解決不能、 fail-closed)
    - "item:" / "shops:" prefix → KEY_TYPE_URL_KEY (= mercari URL key)
    - その他 (= 非空・非 URL prefix) → KEY_TYPE_PRODUCT_ID (= catalog 由来 product_id)

    手動補完値の検出は呼出側で別途 valid_pids 突合で行う想定 (= 本関数は形式分類のみ)。
    """
    if not key:
        return KEY_TYPE_FAILED
    k = key.strip()
    if not k:
        return KEY_TYPE_FAILED
    if k.startswith("item:") or k.startswith("shops:"):
        return KEY_TYPE_URL_KEY
    return KEY_TYPE_PRODUCT_ID


def extract_canonical_key(
    title: str = "",
    url: str = "",
    cert: str = "",
    image_url: str = "",
    extra_text: str = "",
    purpose: str = "dedup",
) -> Tuple[str, str]:
    """canonical KEY を resolver 経由で取得 (= 単一値、 KEY2 廃止).

    spec §3 = resolver(context) → product_id | url-key | "".

    Returns:
        (canonical_key, key_type)
        - canonical_key: product_id (例 "OP10-049_p1") / "item:m..." / "" (= 解決不能)
        - key_type: KEY_TYPE_PRODUCT_ID / KEY_TYPE_URL_KEY / KEY_TYPE_FAILED
    """
    from . import resolver_io  # 遅延 import (= module-level 越境依存回避)
    key = resolver_io.resolve_sheet_row(
        title=title,
        url=url,
        image_url=image_url,
        cert=cert,
        extra_text=extra_text,
        purpose=purpose,
    )
    return key, classify_canonical_key(key)


def extract_canonical_key_with_category(
    title: str = "",
    url: str = "",
    cert: str = "",
    image_url: str = "",
    extra_text: str = "",
    purpose: str = "dedup",
) -> Tuple[str, str]:
    """canonical KEY を **カテゴリ prefix 込み** で取得 (= 案B Phase2b 書く側用).

    resolve_sheet_row_with_category → key_format.build_key で
    `{category}:{product_id}` (catalog-backed) / url-key そのまま / "" を組立。
    classify は組立後の KEー に対して行う (= prefix 付き product_id も PRODUCT_ID 判定)。

    Returns:
        (canonical_key, key_type) — extract_canonical_key と同 signature。
        canonical_key: "gundam_tcg:ST02-010" / "item:m..." / "" (= 未解決)
    """
    from . import resolver_io
    from .key_format import build_key
    res = resolver_io.resolve_sheet_row_with_category(
        title=title,
        url=url,
        image_url=image_url,
        cert=cert,
        extra_text=extra_text,
        purpose=purpose,
    )
    key = build_key(res.get("category"), res.get("product_id"))
    return key, classify_canonical_key(key)


@dataclass(frozen=True)
class CanonicalIndex:
    """既存出品スプシ (= HIGH/LOW/公式) から構築した単一 KEY 突合 index.

    Step 4 spec §2:
    - 単一 frozenset (= keys)、 全 canonical KEY を統合
    - product_id / url-key を区別せず同一 set で突合 (= 1 KEY 1 一意)

    fail-closed: "" (= 解決不能) は index 投入対象外 (= 突合不能 → keep over remove)
    """

    keys: frozenset = frozenset()

    @classmethod
    def empty(cls) -> "CanonicalIndex":
        return cls(frozenset())

    @classmethod
    def from_iterable(cls, keys: Iterable[str]) -> "CanonicalIndex":
        """canonical KEY string iterable から index 構築 (= 空・None は skip).

        2026-07-27 Phase1b: KEー を group_key 正規化して格納 (= カテゴリ込み突合)。
        旧 `ST02-010` と 新 `gundam_tcg:ST02-010` は別 group_key → 別グループ
        (= 移行期に混ぜない)。 url-key / 旧形式は group_key が恒等なので後方互換。
        """
        from .key_format import group_key
        out: set = set()
        for k in keys:
            if not k:
                continue
            k_stripped = k.strip()
            if k_stripped:
                out.add(group_key(k_stripped))
        return cls(frozenset(out))

    def __contains__(self, key: str) -> bool:
        from .key_format import group_key
        if not key:
            return False
        return group_key(key) in self.keys

    def __len__(self) -> int:
        return len(self.keys)


def classify_row_canonical(
    title: str,
    url: str,
    existing: CanonicalIndex,
    cert: str = "",
    image_url: str = "",
    extra_text: str = "",
) -> Tuple[str, str]:
    """中間スプシ 1 row を単一 canonical KEY で分類.

    Step 4 spec §1, §4:
    - canonical KEY を resolver 経由で 1 値解決
    - existing index と完全一致 → 重複
    - "" (= 解決不能) → 不明 (= fail-closed、 keep)

    Returns: (flag, canonical_key) — flag は中間スプシ書込用文字列、 key は debug 用
    """
    canonical_key, key_type = extract_canonical_key(
        title=title,
        url=url,
        cert=cert,
        image_url=image_url,
        extra_text=extra_text,
        purpose="dedup",
    )
    if key_type == KEY_TYPE_FAILED:
        return FLAG_UNKNOWN, ""
    if canonical_key in existing:
        return FLAG_DUP_CANONICAL, canonical_key
    return FLAG_NEW, canonical_key


@dataclass(frozen=True)
class ExistingIndex:
    """既存出品スプシ (= HIGH/LOW/公式) から構築した突合 index.

    Phase 1f 拡張:
    - Phase 1a-1e の単 KEY 系 set (= url_keys / tcg_ids / gshock_models) は保持
    - (KEY1, KEY2) tuple set を追加 = 真の重複判定用 (= 物理除外可)
    """

    url_keys: frozenset
    tcg_ids: frozenset
    gshock_models: frozenset
    tuples: frozenset = frozenset()  # Phase 1f: (key1, key2) tuple set

    @classmethod
    def empty(cls) -> "ExistingIndex":
        return cls(frozenset(), frozenset(), frozenset(), frozenset())


def build_existing_index(
    rows: Iterable[Tuple[str, str]],
) -> ExistingIndex:
    """既存出品スプシ rows (= title, url) から index を構築.

    title 列を各 extractor に通し、 hit したものを set に集約。
    """
    url_keys: set = set()
    tcg_ids: set = set()
    gshock_models: set = set()

    for title, url in rows:
        key = extract_mercari_url_key(url)
        if key:
            url_keys.add(key)
        tcg = extract_tcg_id(title)
        if tcg:
            tcg_ids.add(tcg)
        gshock = extract_gshock_model(title)
        if gshock:
            gshock_models.add(gshock)

    return ExistingIndex(
        url_keys=frozenset(url_keys),
        tcg_ids=frozenset(tcg_ids),
        gshock_models=frozenset(gshock_models),
    )


def classify_row(
    title: str,
    url: str,
    existing: ExistingIndex,
    extracted_id: Optional[str] = None,
) -> str:
    """中間スプシ 1 row を分類して flag string を返す.

    Phase 1f: (KEY1, KEY2) tuple 完全一致を優先判定 (= 真の重複)。
    tuple 一致なら card_id / 型番 / URL いずれの形式かに応じて旧 flag を返す
    (= U 列の見た目互換維持)。

    優先順位:
    1. URL 一致 (= 完全一致なので確度最高)
    2. (KEY1, KEY2) tuple 完全一致 → card_id/型番/URL 種別に応じた flag
    3. card_id 一致 (= TCG) — 後方互換 (= KEY2 不在 の旧 index)
    4. 型番一致 (= G-shock) — 同上
    5. extractor で id 取れた + 上記 hit なし → 新規 ""
    6. extractor で id 取れず → "不明" (= fail-closed)
    """
    url_key = extract_mercari_url_key(url)
    if url_key and url_key in existing.url_keys:
        return FLAG_DUP_URL

    # Phase 1f: tuple 突合
    key1, type1, key2 = extract_priority_key2(title, url)
    if key1 and type1 in (KEY_TYPE_CARD, KEY_TYPE_MODEL):
        key1_norm = key1.upper()
        if (key1_norm, key2) in existing.tuples:
            return FLAG_DUP_CARD_ID if type1 == KEY_TYPE_CARD else FLAG_DUP_MODEL

    # 旧経路 (= KEY2 不在の場合の互換)
    tcg = extracted_id if extracted_id else extract_tcg_id(title)
    if tcg and tcg in existing.tcg_ids:
        return FLAG_DUP_CARD_ID

    gshock = extract_gshock_model(title)
    if gshock and gshock in existing.gshock_models:
        return FLAG_DUP_MODEL

    if tcg or gshock or url_key:
        return FLAG_NEW

    return FLAG_UNKNOWN


# ============================================================================
# CLI
# ============================================================================

def _build_full_existing_index(client) -> ExistingIndex:
    """HIGH / LOW / 公式 SKU詳細 の KEY1+KEY2 列を読込んで 統合 index を返す.

    Phase 1f 仕様:
    - 単 KEY 系 set (url_keys / tcg_ids / gshock_models) は後方互換維持
    - (KEY1, KEY2) tuple set を追加 = 真の重複判定用 (= 物理除外可)
    """
    from . import sheet_io  # 遅延 import (= unit test で network 不要にするため)

    url_keys: set = set()
    tcg_ids: set = set()
    gshock_models: set = set()
    tuples: set = set()

    def _ingest_keys(keys_list, source_label, tuples_list=None):
        """KEY1 値 list を url/card/model 3 set に振分け. tuples も収集."""
        n_url = n_card = n_model = n_unknown = n_empty = 0
        for k in keys_list:
            t = classify_existing_key(k)
            if t == KEY_TYPE_URL:
                url_keys.add(k.strip())
                n_url += 1
            elif t == KEY_TYPE_CARD:
                tcg_ids.add(k.strip().upper())
                n_card += 1
            elif t == KEY_TYPE_MODEL:
                gshock_models.add(k.strip().upper())
                n_model += 1
            elif t == "unknown":
                n_unknown += 1
            else:
                n_empty += 1
        n_tuples_added = 0
        if tuples_list:
            for k1, k2 in tuples_list:
                k1_norm = k1.strip()
                k2_norm = (k2 or "").strip()
                if not k1_norm:
                    continue
                # card_id / model は upper、 URL はそのまま
                t = classify_existing_key(k1_norm)
                if t in (KEY_TYPE_CARD, KEY_TYPE_MODEL):
                    k1_norm = k1_norm.upper()
                tuples.add((k1_norm, k2_norm))
                n_tuples_added += 1
        print(
            f"    {source_label}: url={n_url} card={n_card} model={n_model} "
            f"unknown={n_unknown} empty={n_empty} (total={len(keys_list)}, "
            f"tuples={n_tuples_added})"
        )

    # HIGH / LOW: KEY1 + KEY2 同時読込
    # 2026-05-27 ACTIVE filter:
    # ACTIVE 条件 = B 列 itemID NOT NULL (= eBay 出品済) + D 列 sold 空欄 (= 未売切)
    # B 空欄 = 未出品 / D 値あり = 取下げ → どちらも index 外 (= false positive 防止)
    HIGH_LOW_ITEM_ID_COL = 2  # B 列
    for label, sid in [("HIGH", sheet_io.HIGH_SHEET_ID), ("LOW", sheet_io.LOW_SHEET_ID)]:
        print(f"[*] {label} 商品管理シート KEY1/KEY2 列 読込 (ACTIVE のみ = B あり + D 空)...", flush=True)
        sh = sheet_io.open_spreadsheet(sid, client=client)
        ws = sheet_io._get_worksheet_by_gid(sh, sheet_io.LISTINGS_GID)
        key1_col = sheet_io.find_key1_column(ws)
        if key1_col is None:
            print(
                f"    {label}: KEY1 列が無い (= Phase 1a/1f 未実行). "
                "`python -m dedupe.checker --backfill-keys` を先に実行してください."
            )
            continue
        key2_col = sheet_io.find_key_column(ws, sheet_io.KEY2_COLUMN_HEADER)
        if key2_col is not None:
            tup_list = sheet_io.read_key_columns_tuples(
                ws, key1_col, key2_col,
                active_only=True,
                sold_col=sheet_io.LISTINGS_COL_SOLD,
                item_id_col=HIGH_LOW_ITEM_ID_COL,
            )
            keys = [t[0] for t in tup_list]
        else:
            keys = sheet_io.read_key_column_values(
                ws, key1_col,
                active_only=True,
                sold_col=sheet_io.LISTINGS_COL_SOLD,
                item_id_col=HIGH_LOW_ITEM_ID_COL,
            )
            tup_list = [(k, "") for k in keys if k]
        _ingest_keys(keys, label, tup_list)

    # 公式 SKU詳細 (= schema 異なるため ACTIVE filter は別 phase、 現状全件 index 化)
    print("[*] 公式 SKU詳細 KEY1/KEY2 列 読込...", flush=True)
    official = sheet_io.open_spreadsheet(sheet_io.OFFICIAL_SHEET_ID, client=client)
    try:
        ws_sku = official.worksheet(sheet_io.OFFICIAL_SKU_TAB)
        key1_col = sheet_io.find_key1_column(ws_sku)
        if key1_col is None:
            print("    公式 SKU詳細: KEY1 列が無い. skip.")
        else:
            key2_col = sheet_io.find_key_column(ws_sku, sheet_io.KEY2_COLUMN_HEADER)
            if key2_col is not None:
                tup_list = sheet_io.read_key_columns_tuples(ws_sku, key1_col, key2_col)
                keys = [t[0] for t in tup_list]
            else:
                keys = sheet_io.read_key_column_values(ws_sku, key1_col)
                tup_list = [(k, "") for k in keys if k]
            _ingest_keys(keys, "公式 SKU詳細", tup_list)
    except Exception as exc:
        print(f"    公式 SKU詳細 読込失敗 (skip): {exc}")

    idx = ExistingIndex(
        url_keys=frozenset(url_keys),
        tcg_ids=frozenset(tcg_ids),
        gshock_models=frozenset(gshock_models),
        tuples=frozenset(tuples),
    )
    print(
        f"[*] index 構築完了: url_keys={len(idx.url_keys)} "
        f"tcg_ids={len(idx.tcg_ids)} gshock_models={len(idx.gshock_models)} "
        f"tuples={len(idx.tuples)}"
    )
    return idx


# ============================================================================
# Phase 1a: KEY 列 backfill (= 既存 HIGH/LOW/公式 への 1 回 effort)
# ============================================================================

def run_backfill_keys(dry_run: bool = False, upgrade_url_to_card: bool = False) -> int:
    """HIGH / LOW 商品管理シート + 公式 SKU詳細 に KEY 列 を backfill.

    1. ensure_key_column() で KEY 列 確保 (= header `KEY`)
    2. Phase 1c: HIGH/LOW は B 列 eBay item ID + snapshot 経由で eBay 正規 title 優先
       fallback = C 列 sheet title。 公式 SKU詳細 は snapshot 不使用
    3. 各 row の title から extract_priority_key() で KEY 値抽出
    4. 既に KEY 列に値ある row は skip (= 手動補完を尊重)
    """
    from . import sheet_io
    from . import snapshot_io

    client = sheet_io.authorize_client()
    overall = {
        "total_rows": 0,
        "skipped_existing": 0,
        "skipped_no_extraction": 0,
        "written_card": 0,
        "written_model": 0,
        "written_url": 0,
        "snapshot_hits": 0,
        "snapshot_misses": 0,
        "fallback_to_sheet_title": 0,
        "upgraded_url_to_card": 0,
        "upgraded_url_to_model": 0,
    }

    # Phase 1c: snapshot 読込 (= HIGH/LOW 用)
    snapshot_path = snapshot_io.find_latest_snapshot()
    snapshot_titles = {}
    if snapshot_path:
        snapshot_titles = snapshot_io.load_snapshot_titles(snapshot_path)
        print(
            f"[*] snapshot 読込: {snapshot_path.name}  "
            f"({len(snapshot_titles)} listings)"
        )
    else:
        print(
            "[!] snapshot 不在: HIGH/LOW も C 列 sheet title fallback のみ "
            "(= Phase 1a と同等)"
        )

    # Phase 1k 4.2.1 (= 2026-05-27): catalog valid_pids 読込 (= G-shock 33 件 + Pokemon 等 全 cat fallback)
    from . import catalog_io
    print("[*] iMakCatalog valid_pids 読込 (= 全 category token verify fallback 用)...")
    _cat_con = catalog_io.open_catalog_readonly()
    try:
        catalog_valid_pids = catalog_io.load_valid_product_ids(_cat_con)
    finally:
        _cat_con.close()
    print(f"    valid_pids: {len(catalog_valid_pids)}")

    # HIGH/LOW: itemID col=2 (LISTINGS_COL_ITEM_ID) で snapshot lookup
    # 公式 SKU詳細: itemID 構造違うため snapshot 不使用 (Phase 1c 対象外)
    targets = [
        {
            "label": "HIGH 商品管理シート",
            "sid": sheet_io.HIGH_SHEET_ID,
            "by_gid": sheet_io.LISTINGS_GID,
            "title_col": sheet_io.LISTINGS_COL_TITLE,
            "url_col": sheet_io.LISTINGS_COL_URL,
            "item_id_col": 2,  # B 列 = eBay item ID
            "use_snapshot": True,
        },
        {
            "label": "LOW 商品管理シート",
            "sid": sheet_io.LOW_SHEET_ID,
            "by_gid": sheet_io.LISTINGS_GID,
            "title_col": sheet_io.LISTINGS_COL_TITLE,
            "url_col": sheet_io.LISTINGS_COL_URL,
            "item_id_col": 2,
            "use_snapshot": True,
        },
        {
            "label": "公式 SKU詳細",
            "sid": sheet_io.OFFICIAL_SHEET_ID,
            "by_tab_name": sheet_io.OFFICIAL_SKU_TAB,
            "title_col": sheet_io.OFFICIAL_SKU_COL_TITLE,
            "url_col": None,  # SKU詳細 は URL 列なし
            "item_id_col": None,
            "use_snapshot": False,
        },
    ]

    overall_variants: Dict[str, int] = {}
    for tgt in targets:
        print(f"\n[*] {tgt['label']} backfill 開始 (dry_run={dry_run})...")
        sh = sheet_io.open_spreadsheet(tgt["sid"], client=client)
        if "by_gid" in tgt:
            ws = sheet_io._get_worksheet_by_gid(sh, tgt["by_gid"])
        else:
            ws = sh.worksheet(tgt["by_tab_name"])
        key1_col, key2_col = sheet_io.ensure_key1_key2_columns(ws, dry_run=dry_run)
        print(
            f"    worksheet={ws.title!r}  KEY1 列={key1_col} KEY2 列={key2_col} "
            f"(dry_run={dry_run})"
        )

        # Phase 1q: PSA cert → iMakeBayAPI cache → catalog lookup_* 経路 (= upgrade 補強)
        # HIGH のみ I 列 (= TCG row で cert)、 LOW は cert 列無
        _cert_col_phase_q = (
            sheet_io.HIGH_COL_CERT_OR_ENGTITLE
            if tgt["label"].startswith("HIGH")
            else None
        )
        _psa_lookup_fns_phase_q = (
            {
                "lookup_one_piece": catalog_io.lookup_one_piece,
                "lookup_don": catalog_io.lookup_don,
                "lookup_pokemon": catalog_io.lookup_pokemon,
                "lookup_yugioh": catalog_io.lookup_yugioh,
                "lookup_dragonball": catalog_io.lookup_dragonball,
                "lookup_gundam": catalog_io.lookup_gundam,
            }
            if _cert_col_phase_q
            else None
        )

        # Phase 1r (= 5/28): 写真 URL = HIGH/LOW 商品管理シート G 列 (= col 7)
        # Catalog B 完成時 lookup_don(image_url=...) に渡して画像 hash で tie 解消.
        _image_url_col_phase_r = 7  # G 列 = 写真 URL

        result = sheet_io.backfill_key1_key2(
            ws=ws,
            key1_col=key1_col,
            key2_col=key2_col,
            title_col=tgt["title_col"],
            url_col=tgt["url_col"],
            priority_extractor2=extract_priority_key2,
            dry_run=dry_run,
            item_id_col=tgt["item_id_col"] if tgt["use_snapshot"] else None,
            snapshot_titles=snapshot_titles if tgt["use_snapshot"] else None,
            upgrade_url_to_card=upgrade_url_to_card,
            key_classifier=classify_existing_key,
            catalog_valid_pids=catalog_valid_pids,
            cert_col=_cert_col_phase_q,
            psa_lookup_fns=_psa_lookup_fns_phase_q,
            image_url_col=_image_url_col_phase_r,
        )
        # backfill_key1_key2 の counts に既存 print 用 key を合わせる
        counts = {
            "total_rows": result["total_rows"],
            "skipped_existing": result["skipped_existing"],
            "skipped_no_extraction": result["skipped_no_extraction"],
            "written_card": result["written_card_key1"],
            "written_model": result["written_model_key1"],
            "written_url": result["written_url_key1"],
            "snapshot_hits": result["snapshot_hits"],
            "snapshot_misses": result["snapshot_misses"],
            "fallback_to_sheet_title": 0,  # Phase 1f は snapshot 優先で fallback 区別なし
            "upgraded_url_to_card": result["upgraded_url_to_card"],
            "upgraded_url_to_model": result["upgraded_url_to_model"],
        }
        # variant 集計を overall に merge
        for v, n in result.get("variant_breakdown", {}).items():
            overall_variants[v] = overall_variants.get(v, 0) + n
        # KEY2 書込件数 表示
        counts["written_key2"] = result["written_key2"]
        for k, v in counts.items():
            overall[k] = overall.get(k, 0) + v
        n_written = (
            counts["written_card"] + counts["written_model"] + counts["written_url"]
        )
        snap_part = (
            f"  snap_hit={counts['snapshot_hits']} "
            f"snap_miss={counts['snapshot_misses']} "
            f"sheet_fallback={counts['fallback_to_sheet_title']}"
            if tgt["use_snapshot"]
            else ""
        )
        upgrade_part = (
            f"  upg_card={counts['upgraded_url_to_card']} "
            f"upg_model={counts['upgraded_url_to_model']}"
            if upgrade_url_to_card and tgt["use_snapshot"]
            else ""
        )
        key2_part = f"  KEY2={counts['written_key2']}"
        print(
            f"    rows={counts['total_rows']}  "
            f"既存skip={counts['skipped_existing']}  "
            f"抽出失敗={counts['skipped_no_extraction']}  "
            f"KEY1書込={n_written} "
            f"(card={counts['written_card']} "
            f"model={counts['written_model']} url={counts['written_url']})"
            f"{key2_part}{snap_part}{upgrade_part}"
        )

    print()
    print("=" * 70)
    print(f"Phase 1a/1c backfill 集計 (dry_run={dry_run})")
    print("=" * 70)
    n_written = (
        overall["written_card"] + overall["written_model"] + overall["written_url"]
    )
    print(f"  total rows           : {overall['total_rows']}")
    print(f"  既存値あり skip      : {overall['skipped_existing']}")
    print(f"  抽出失敗 (空欄維持)  : {overall['skipped_no_extraction']}")
    print(f"  書込 計              : {n_written}")
    print(f"    card_id            : {overall['written_card']}")
    print(f"    型番               : {overall['written_model']}")
    print(f"    URL                : {overall['written_url']}")
    print(f"  Phase 1c 経路統計:")
    print(f"    snapshot hit       : {overall['snapshot_hits']}")
    print(f"    snapshot miss      : {overall['snapshot_misses']}")
    print(f"    sheet title 採用   : {overall['fallback_to_sheet_title']}")
    if upgrade_url_to_card:
        n_upgrades = overall["upgraded_url_to_card"] + overall["upgraded_url_to_model"]
        print(f"  Phase 1d-TCG 解釈 B (= URL → card/model upgrade):")
        print(f"    upgraded to card_id: {overall['upgraded_url_to_card']}")
        print(f"    upgraded to model  : {overall['upgraded_url_to_model']}")
        print(f"    upgrade 計          : {n_upgrades}")
    if overall_variants:
        print(f"  Phase 1f variant 内訳:")
        for v in ("sec", "alt", "par", "pro", "spc", "fa"):
            if v in overall_variants:
                print(f"    {v:<4}: {overall_variants[v]}")
    if dry_run:
        print("[*] --dry-run のため 書込 skip.")
    return 0


def _classify_intermediate(
    client,
    existing: ExistingIndex,
    only_tab: Optional[str] = None,
) -> Tuple[dict, Counter, List[Tuple[str, int, str, str]]]:
    """中間スプシ 全タブ (or only_tab) を分類.

    return:
    - flags_by_tab: {tab_name: [(row_index, flag), ...]}
    - counter: Counter({flag: count, ...}) 全体集計
    - samples: 5-10 件 sample [(tab, row, title, flag), ...] (= verify 用)
    """
    from . import sheet_io

    intermediate = sheet_io.open_spreadsheet(sheet_io.INTERMEDIATE_SHEET_ID, client=client)
    flags_by_tab: dict = defaultdict(list)
    counter: Counter = Counter()
    samples: List[Tuple[str, int, str, str]] = []
    SAMPLE_MAX = 10

    for row in sheet_io.read_intermediate_rows(intermediate, only_tab=only_tab):
        flag = classify_row(row.title, row.url, existing)
        flags_by_tab[row.tab_name].append((row.row_index, flag))
        counter[flag] += 1
        if len(samples) < SAMPLE_MAX:
            samples.append((row.tab_name, row.row_index, row.title, flag))

    return flags_by_tab, counter, samples


def _print_summary(counter: Counter, samples: List[Tuple[str, int, str, str]]) -> None:
    total = sum(counter.values())
    print()
    print("=" * 70)
    print(f"突合結果サマリー (= 中間スプシ 全 row 集計)")
    print("=" * 70)
    print(f"  総 row 数            : {total}")
    print(f"  新規 (= 空)          : {counter.get(FLAG_NEW, 0)}")
    print(f"  重複 URL             : {counter.get(FLAG_DUP_URL, 0)}")
    print(f"  重複 card_id (TCG)   : {counter.get(FLAG_DUP_CARD_ID, 0)}")
    print(f"  重複 型番 (G-shock)  : {counter.get(FLAG_DUP_MODEL, 0)}")
    print(f"  不明 (= 目視判断要) : {counter.get(FLAG_UNKNOWN, 0)}")
    print()
    print("sample (最大 10 件):")
    for tab, row, title, flag in samples:
        flag_disp = flag if flag else "(空=新規)"
        title_disp = (title[:50] + "...") if len(title) > 50 else title
        print(f"  [{tab}] row {row:>4}: {flag_disp:<14} | {title_disp}")
    print()


def run(only_tab: Optional[str] = None, dry_run: bool = False) -> int:
    """エントリ. 戻り値 = 終了 code (0 = 正常)."""
    from . import sheet_io

    client = sheet_io.authorize_client()

    print("[*] 既存出品 index 構築 (= HIGH / LOW / 公式)...")
    existing = _build_full_existing_index(client)

    print()
    print(f"[*] 中間スプシ 突合開始 (only_tab={only_tab!r}, dry_run={dry_run})...")
    flags_by_tab, counter, samples = _classify_intermediate(
        client, existing, only_tab=only_tab
    )
    _print_summary(counter, samples)

    if dry_run:
        print("[*] --dry-run のため 書込 skip.")
        return 0

    print("[*] 中間スプシ U 列 (= 「既存出品 chk」) header 確保...")
    intermediate = sheet_io.open_spreadsheet(sheet_io.INTERMEDIATE_SHEET_ID, client=client)
    sheet_io.ensure_check_header(intermediate, only_tab=only_tab)

    print(f"[*] 中間スプシ U 列 書込 ({sum(len(v) for v in flags_by_tab.values())} cell)...")
    sheet_io.write_check_flags(intermediate, flags_by_tab)

    print("[*] 完了.")
    return 0


# ============================================================================
# Phase 1e: eBay Browse API バッチ + API cache 経由 KEY 補完
# ============================================================================

def _collect_no_key_item_ids() -> List[str]:
    """HIGH/LOW で KEY 空 + B 列 itemID あり の item_id list を返す.

    POC で --only-no-key 指定時の対象 (= API quota 節約)。
    """
    from . import sheet_io

    client = sheet_io.authorize_client()
    item_ids: List[str] = []
    for label, sid in [("HIGH", sheet_io.HIGH_SHEET_ID), ("LOW", sheet_io.LOW_SHEET_ID)]:
        sh = sheet_io.open_spreadsheet(sid, client=client)
        ws = sheet_io._get_worksheet_by_gid(sh, sheet_io.LISTINGS_GID)
        values = ws.get_all_values()
        if not values:
            continue
        key_col = sheet_io.find_key_column(ws)
        for row in values[1:]:
            b = (row[1] or "").strip() if len(row) > 1 else ""
            current_key = (row[key_col - 1] or "").strip() if key_col and len(row) >= key_col else ""
            if b and not current_key:
                item_ids.append(b)
        print(f"    {label}: KEY 空 + itemID あり = {sum(1 for x in item_ids if x)} 件累計")
    return item_ids


def _collect_snapshot_item_ids() -> List[str]:
    """snapshot CSV から全 item_id list を返す."""
    from . import snapshot_io

    snap_path = snapshot_io.find_latest_snapshot()
    if snap_path is None:
        return []
    titles = snapshot_io.load_snapshot_titles(snap_path)
    return list(titles.keys())


def run_api_fetch_specifics(
    limit: Optional[int] = None,
    only_no_key: bool = False,
    dry_run: bool = False,
) -> int:
    """Browse API バッチで Item Specifics 取得 → JSON cache 保存."""
    from . import ebay_api

    if only_no_key:
        print("[*] HIGH/LOW から KEY 空 + itemID あり の対象 item_id 収集...")
        item_ids = _collect_no_key_item_ids()
    else:
        print("[*] snapshot CSV から全 item_id 収集...")
        item_ids = _collect_snapshot_item_ids()

    print(f"[*] 候補 item_id 総数: {len(item_ids)}")
    if limit is not None and limit > 0:
        item_ids = item_ids[:limit]
        print(f"[*] --limit={limit} で {len(item_ids)} 件に制限")

    if not item_ids:
        print("[!] 対象 item_id ゼロ. 終了.")
        return 0

    cache_path = ebay_api.build_cache_path()
    print(f"[*] cache path: {cache_path}")

    existing = ebay_api.load_cache_if_exists(cache_path)
    new_targets = [iid for iid in item_ids if iid not in existing]
    print(f"[*] 既存 cache hit={len(item_ids) - len(new_targets)}, 新規 fetch 対象={len(new_targets)}")

    if dry_run:
        print("[*] --dry-run のため API 呼出 skip.")
        return 0

    print("[*] OAuth token 取得...")
    try:
        token = ebay_api.get_token()
    except Exception as exc:
        print(f"[!] token 取得失敗: {exc}")
        return 2

    print(f"[*] Browse API fetch 開始 ({len(new_targets)} 件、 推定 {len(new_targets) * 0.5:.0f}-{len(new_targets):.0f} 秒)...")
    cache = ebay_api.batch_fetch_specifics(
        token=token,
        item_ids=item_ids,
        output_path=cache_path,
        flush_every=20,
        sleep_seconds=0.1,
    )

    # summary
    n_ok = sum(1 for v in cache.values() if "_error" not in v)
    n_err = sum(1 for v in cache.values() if "_error" in v)
    n_with_card = sum(1 for v in cache.values() if v.get("Card Number"))
    n_with_model = sum(1 for v in cache.values() if v.get("Model"))
    n_with_mpn = sum(1 for v in cache.values() if v.get("MPN"))
    print()
    print("=" * 70)
    print(f"Phase 1e fetch 集計")
    print("=" * 70)
    print(f"  cache 件数: {len(cache)} (OK={n_ok} / err={n_err})")
    print(f"  Item Specifics 内訳:")
    print(f"    Card Number あり: {n_with_card}")
    print(f"    Model あり      : {n_with_model}")
    print(f"    MPN あり        : {n_with_mpn}")
    return 0


def run_backfill_keys_from_api(dry_run: bool = False) -> int:
    """API cache + iMakCatalog 参照で HIGH 商品管理シート の KEY1/KEY2 を補完.

    Phase 1i (= 5/27 ユーザー指摘) — catalog 経路を **primary**:
    1. 既存 KEY1 = card_id/model 系 (= 手動 or 自動確定) → 不変
    2. 既存 KEY1 = URL fallback / 空 → API cache の Item Specifics で
       Catalog 参照 reconstruct (= Card Number + Set → 公式 product_id) を試行
    3. KEY2 が空 + Features/Speciality に variant keyword あれば書込

    R='TCG' row のみ対象 (= HIGH B 列 itemID + Item Specifics の整合が取れる商品種別)。
    """
    from . import catalog_io
    from . import ebay_api
    from . import sheet_io
    from .extractors.variant import extract_variant
    import gspread

    cache_path = ebay_api.find_latest_cache()
    if cache_path is None:
        print("[!] API cache 不在. 先に `--api-fetch-specifics` を実行してください.")
        return 2
    cache = ebay_api.load_cache_if_exists(cache_path)
    print(f"[*] API cache 読込: {cache_path.name} ({len(cache)} entries)")

    # iMakCatalog 読込 (= read-only)
    print("[*] iMakCatalog 読込 (= 共有 products.sqlite)...")
    con = catalog_io.open_catalog_readonly()
    try:
        set_map = catalog_io.load_set_name_map(con)
        valid_pids = catalog_io.load_valid_product_ids(con)
    finally:
        con.close()
    print(
        f"    set_map: {len(set_map)} entries  "
        f"valid product_ids: {len(valid_pids)}"
    )

    client = sheet_io.authorize_client()
    sh = sheet_io.open_spreadsheet(sheet_io.HIGH_SHEET_ID, client=client)
    ws = sheet_io._get_worksheet_by_gid(sh, sheet_io.LISTINGS_GID)
    values = ws.get_all_values()
    key1_col, key2_col = sheet_io.ensure_key1_key2_columns(ws, dry_run=dry_run)

    stats = {
        "tcg_rows": 0,
        "skipped_existing_card": 0,
        "skipped_no_itemid_or_cache": 0,
        "skipped_reconstruct_failed": 0,
        "upgraded_to_card": 0,
        "wrote_new_card": 0,
        "wrote_key2": 0,
    }
    reason_counts: Dict[str, int] = {}
    samples: List[str] = []
    updates = []

    for offset, row in enumerate(values[1:], start=1):
        row_idx = offset + 1
        cat = (row[sheet_io.HIGH_COL_CATEGORY - 1] or "").strip() if len(row) >= sheet_io.HIGH_COL_CATEGORY else ""
        if cat != sheet_io.HIGH_CATEGORY_TCG_VALUE:
            continue
        stats["tcg_rows"] += 1

        current_k1 = (row[key1_col - 1] or "").strip() if len(row) >= key1_col else ""
        current_k2 = (row[key2_col - 1] or "").strip() if len(row) >= key2_col else ""

        # KEY1 が既に card/model = 確定済 → skip
        if current_k1 and not (
            current_k1.startswith("item:") or current_k1.startswith("shops:")
        ):
            # unknown / card / model はすべて尊重
            t = classify_existing_key(current_k1)
            if t in ("card", "model", "unknown"):
                stats["skipped_existing_card"] += 1
                continue

        item_id = (row[1] or "").strip() if len(row) > 1 else ""
        specs = cache.get(item_id, {}) if item_id else {}
        if not specs or "_error" in specs:
            stats["skipped_no_itemid_or_cache"] += 1
            continue

        card_id, reason = catalog_io.reconstruct_card_id(
            specs.get("Card Number", ""),
            specs.get("Set", ""),
            set_map,
            valid_pids,
        )
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if not card_id:
            stats["skipped_reconstruct_failed"] += 1
            continue

        # KEY1 書込
        if current_k1 and (
            current_k1.startswith("item:") or current_k1.startswith("shops:")
        ):
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_idx, key1_col),
                    "values": [[card_id]],
                }
            )
            stats["upgraded_to_card"] += 1
        elif not current_k1:
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_idx, key1_col),
                    "values": [[card_id]],
                }
            )
            stats["wrote_new_card"] += 1

        # KEY2: variant 抽出 (= Features + Speciality aspect)
        features = specs.get("Features", "") or ""
        speciality = specs.get("Speciality", "") or ""
        variant = extract_variant(features + " " + speciality)
        if not current_k2 and variant:
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_idx, key2_col),
                    "values": [[variant]],
                }
            )
            stats["wrote_key2"] += 1

        if len(samples) < 10:
            samples.append(
                f"row {row_idx}: → KEY1={card_id!r} KEY2={variant!r}  ({reason})"
            )

    if updates and not dry_run:
        CHUNK = 500
        for i in range(0, len(updates), CHUNK):
            ws.batch_update(updates[i : i + CHUNK], value_input_option="USER_ENTERED")

    print()
    print("=" * 70)
    print(f"Phase 1i catalog-based backfill (dry_run={dry_run})")
    print("=" * 70)
    print(f"  R=TCG total rows                : {stats['tcg_rows']}")
    print(f"  既存 KEY1 確定 skip              : {stats['skipped_existing_card']}")
    print(f"  itemID/cache 無 skip             : {stats['skipped_no_itemid_or_cache']}")
    print(f"  catalog 復元失敗 skip            : {stats['skipped_reconstruct_failed']}")
    print(f"  KEY1 upgrade (URL→card)         : {stats['upgraded_to_card']}")
    print(f"  KEY1 新規 (= 空→card)            : {stats['wrote_new_card']}")
    print(f"  KEY2 新規 (variant)              : {stats['wrote_key2']}")
    if samples:
        print()
        print(f"  samples (max 10):")
        for s in samples:
            print(f"    {s}")
    print()
    print(f"  reconstruct reason breakdown:")
    for r, n in sorted(reason_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"    {r}: {n}")
    if dry_run:
        print("[*] --dry-run のため 書込 skip.")
    return 0


# ============================================================================
# Phase 1g: 入稿前 CSV 自動物理除外 chain hook
# ============================================================================

def run_check_csv(csv_path: str, dry_run: bool = False) -> int:
    """eBay File Exchange CSV を読込んで (KEY1, KEY2) tuple で既存と突合 → 物理除外.

    chain hook 用: control_panel の csv_postprocess 後段に統合可能。
    """
    from pathlib import Path
    from . import csv_check
    from . import sheet_io

    path = Path(csv_path)
    if not path.exists():
        print(f"[!] CSV not found: {path}")
        return 2

    print(f"[*] CSV check 開始: {path}  (dry_run={dry_run})")
    print(f"[*] 既存出品 (KEY1, KEY2) tuple index 構築 (HIGH/LOW/公式)...")
    client = sheet_io.authorize_client()
    existing = _build_full_existing_index(client)

    # Phase 1k: catalog valid_pids + set_map 経由 fallback
    from . import catalog_io
    print(f"[*] iMakCatalog valid_pids + set_map 読込 (= 全 category fallback 用)...")
    _cat_con = catalog_io.open_catalog_readonly()
    try:
        _catalog_valid_pids = catalog_io.load_valid_product_ids(_cat_con)
        _catalog_set_map = catalog_io.load_set_name_map(_cat_con)
    finally:
        _cat_con.close()
    print(f"    valid_pids: {len(_catalog_valid_pids)}  set_map: {len(_catalog_set_map)}")

    print(f"\n[*] CSV row 突合中...")
    from . import image_hash as _ih
    result = csv_check.check_csv(
        csv_path=path,
        existing_tuples=existing.tuples,
        priority_extractor2=extract_priority_key2,
        dry_run=dry_run,
        catalog_valid_pids=_catalog_valid_pids,
        catalog_set_map=_catalog_set_map,
        lookup_yugioh_fn=catalog_io.lookup_yugioh,
        lookup_don_fn=catalog_io.lookup_don,
        extract_variant_alias_fn=catalog_io.extract_variant_alias,
        get_variant_meta_fn=catalog_io.get_variant_meta,
        get_category_fn=catalog_io.get_category_by_product_id,
        get_catalog_variants_fn=catalog_io.get_catalog_variants,
        identify_variant_by_image_fn=_ih.identify_variant_by_image,
    )

    print()
    print("=" * 70)
    print(f"Phase 1g CSV check 結果 (dry_run={dry_run})")
    print("=" * 70)
    print(f"  total rows           : {result['total']}")
    print(f"  重複除外             : {result['removed']}")
    print(f"  残存 (= 出品候補)   : {result['kept']}")
    print(f"  不明 (KEY1 取れず)  : {result['unknown']}")
    if result["removed_titles"]:
        print()
        print(f"  除外 row 詳細:")
        for t in result["removed_titles"][:20]:
            print(f"    {t}")
        if len(result["removed_titles"]) > 20:
            print(f"    (... and {len(result['removed_titles']) - 20} more)")
    if result["backup_path"]:
        print()
        print(f"  bak 保存             : {result['backup_path']}")
        print(f"  上書き保存           : {result['csv_path']}")
    if dry_run:
        print("[*] --dry-run のため 書込 / bak 保存 skip.")
    return 0


# ============================================================================
# Phase 1h: 入稿前 CSV → HIGH 事前 KEY 書込 (cert 経由)
# ============================================================================

def run_write_keys_from_csv(csv_path: str, dry_run: bool = False) -> int:
    """CSV から HIGH スプシ R='TCG' row の AI/AJ 列に KEY1/KEY2 を事前書込.

    lag 0 連続入稿対応 (= cron 撤回、 chain hook で完結).
    """
    from pathlib import Path
    from . import csv_write_keys
    from . import sheet_io

    path = Path(csv_path)
    if not path.exists():
        print(f"[!] CSV not found: {path}")
        return 2

    print(f"[*] Phase 1h: 入稿前 KEY 事前書込 開始: {path}  (dry_run={dry_run})")
    client = sheet_io.authorize_client()
    sh = sheet_io.open_spreadsheet(sheet_io.HIGH_SHEET_ID, client=client)
    ws = sheet_io._get_worksheet_by_gid(sh, sheet_io.LISTINGS_GID)
    key1_col, key2_col = sheet_io.ensure_key1_key2_columns(ws, dry_run=dry_run)
    print(
        f"[*] HIGH worksheet={ws.title!r}  "
        f"KEY1 列={key1_col} KEY2 列={key2_col}  "
        f"cert 列={sheet_io.HIGH_COL_CERT_OR_ENGTITLE} "
        f"category 列={sheet_io.HIGH_COL_CATEGORY}"
    )

    # Phase 1j: DON カード fallback (= catalog lookup_don 経由)
    # Phase 1k: catalog token verify + reconstruct fallback (= 全 category 統合)
    from . import catalog_io
    print("[*] iMakCatalog valid_pids + set_map 読込 (= 全 category 統合 fallback 用)...")
    _cat_con = catalog_io.open_catalog_readonly()
    try:
        _catalog_valid_pids = catalog_io.load_valid_product_ids(_cat_con)
        _catalog_set_map = catalog_io.load_set_name_map(_cat_con)
    finally:
        _cat_con.close()
    print(f"    valid_pids: {len(_catalog_valid_pids)}  set_map: {len(_catalog_set_map)}")

    from . import image_hash as _ih
    result = csv_write_keys.write_keys_to_high(
        ws=ws,
        csv_path=path,
        priority_extractor2=extract_priority_key2,
        key1_col=key1_col,
        key2_col=key2_col,
        cert_col=sheet_io.HIGH_COL_CERT_OR_ENGTITLE,
        category_col=sheet_io.HIGH_COL_CATEGORY,
        tcg_category_value=sheet_io.HIGH_CATEGORY_TCG_VALUE,
        dry_run=dry_run,
        lookup_don_fn=catalog_io.lookup_don,
        catalog_valid_pids=_catalog_valid_pids,
        catalog_set_map=_catalog_set_map,
        lookup_yugioh_fn=catalog_io.lookup_yugioh,
        extract_variant_alias_fn=catalog_io.extract_variant_alias,
        get_variant_meta_fn=catalog_io.get_variant_meta,
        get_category_fn=catalog_io.get_category_by_product_id,
        get_catalog_variants_fn=catalog_io.get_catalog_variants,
        identify_variant_by_image_fn=_ih.identify_variant_by_image,
    )

    print()
    print("=" * 70)
    print(f"Phase 1h 事前書込 結果 (dry_run={dry_run})")
    print("=" * 70)
    print(f"  CSV total rows         : {result['csv_rows']}")
    print(f"    cert あり            : {result['csv_with_cert']}")
    print(f"    cert 空 skip         : {result['skipped_no_cert']}")
    print(f"  HIGH 対象 row (R='TCG'): {result['high_tcg_rows']}")
    print(f"    cert 一致 row        : {result['matched']}")
    print(f"    cert 不一致 skip     : {result['skipped_cert_unmatched']}")
    print(f"  書込 KEY1              : {result['written_key1']}")
    print(f"  書込 KEY2              : {result['written_key2']}")
    print(f"  KEY1 既存 skip          : {result['skipped_existing_key1']}")
    print(f"  KEY2 既存 skip          : {result['skipped_existing_key2']}")
    print(f"  KEY1 取得失敗 skip      : {result['skipped_no_key1']}")
    if result["samples"]:
        print()
        print(f"  書込 sample (max 10):")
        for s in result["samples"]:
            print(f"    {s}")
    if dry_run:
        print("[*] --dry-run のため 書込 skip.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dedupe.checker",
        description="重複くん — 中間スプシ ↔ 既存出品スプシ 突合 (重複 flag 書込)",
    )
    parser.add_argument(
        "--backfill-keys",
        action="store_true",
        help="Phase 1a: HIGH/LOW/公式 SKU詳細 の KEY 列を backfill (= 1 回 effort、 以降は増分).",
    )
    parser.add_argument(
        "--upgrade-url-to-card",
        action="store_true",
        help=(
            "Phase 1d-TCG 解釈 B: 既存 URL KEY を 強化 regex + snapshot title で "
            "card_id / 型番 に upgrade. --backfill-keys と組合せて使う. "
            "手動補完 KEY は不変."
        ),
    )
    parser.add_argument(
        "--api-fetch-specifics",
        action="store_true",
        help="Phase 1e: eBay Browse API バッチで Item Specifics を取得 → JSON cache 保存.",
    )
    parser.add_argument(
        "--backfill-keys-from-api",
        action="store_true",
        help="Phase 1e: API cache の Item Specifics で HIGH/LOW KEY 列 補完.",
    )
    parser.add_argument(
        "--backfill-keys-from-cert",
        action="store_true",
        help=(
            "2026-07-15: HIGH R='TCG' AND B(itemID)空 の KEー空 row を cert 経由で "
            "canonical KEー 解決 → 空 KEー に書込 (= 補URL 実効化)。 product_id 限定 "
            "(url封じ)・fail-closed・冪等。 --dry-run で件数のみ。"
        ),
    )
    parser.add_argument(
        "--upgrade-keys-to-category",
        action="store_true",
        help=(
            "2026-07-27 案B Phase3: HIGH の既存 bare KEー を {category}:{product_id} に "
            "upgrade。 resolver が category 確定 かつ 再導出 pid が既存 bare と一致する時のみ "
            "(= 二重 fail-closed)。 曖昧は bare 据置。 --dry-run で件数のみ。"
        ),
    )
    parser.add_argument(
        "--check-csv",
        metavar="CSV_PATH",
        default=None,
        help=(
            "Phase 1g: eBay File Exchange CSV を読込んで (KEY1, KEY2) tuple で既存出品と "
            "突合 → 重複 row を物理除外 (= .bak backup). chain hook 用."
        ),
    )
    parser.add_argument(
        "--write-keys-from-csv",
        metavar="CSV_PATH",
        default=None,
        help=(
            "Phase 1h: CSV の cert + card_id を HIGH スプシ (= R='TCG' row) の AI/AJ 列に "
            "事前書込. lag 0 で連続入稿対応."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Phase 1e POC 用: 取得件数を制限 (= 例 30、 quota 節約 + 動作確認).",
    )
    parser.add_argument(
        "--only-no-key",
        action="store_true",
        help="Phase 1e POC 用: HIGH/LOW で KEY 空 row の item_id のみ対象.",
    )
    parser.add_argument(
        "--tab",
        default=None,
        help="中間スプシで突合対象とする 1 タブのみ (例: seller_623636774). 省略時は全タブ.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="判定のみ実施、 スプシへの書込は skip (= POC / 動作確認用).",
    )
    parser.add_argument(
        "--legacy-tuple-mode",
        action="store_true",
        help=(
            "Step 4 (= 2026-06-10) 移行用 flag: 旧 (KEY1, KEY2) tuple 経路を実行 (互換). "
            "デフォルト = single-key mode (= resolver 経由 canonical KEY 単一突合)."
        ),
    )
    parser.add_argument(
        "--archive-key2",
        action="store_true",
        help=(
            "Step 4: HIGH/LOW スプシの KEY2 列 header を KEY2_ARCHIVED にリネーム (= 履歴保持). "
            "1 回 effort、 以降は KEY2 列書込なし. spec §7."
        ),
    )
    parser.add_argument(
        "--fullscan-dup-mark",
        action="store_true",
        help=(
            "2026-06-12: LOW R='G-shock' の B空 AND D空 全件を resolver 解決 → 既存出品と一致した "
            "row の D列に 'DUP' 書込 (= 初回フルスキャン)。 --dry-run で件数のみ。"
        ),
    )
    parser.add_argument(
        "--mark-dups",
        action="store_true",
        help=(
            "2026-06-12: --check-csv と組合せ。 重複除外 row に対応する LOW B空 row の D列 "
            "に 'DUP' 自動書込 (= scope1 都度)。 --dry-run で件数のみ。"
        ),
    )
    parser.add_argument(
        "--strict-skip-unresolved",
        action="store_true",
        help=(
            "2026-06-16: --check-csv の opt-in。 解決不能 (unresolved) row も物理除外する "
            "(= 旧 strict_mode=True 挙動、 listing-safety 用途)。 既定は keep-unresolved "
            "(= unresolved は残し、 除外は真の重複のみ。 failclosed_must_skip 準拠)。"
        ),
    )
    args = parser.parse_args(argv)

    if args.archive_key2:
        return run_archive_key2(dry_run=args.dry_run)

    if args.fullscan_dup_mark:
        return run_fullscan_dup_mark(dry_run=args.dry_run)

    if args.backfill_keys:
        return run_backfill_keys(
            dry_run=args.dry_run,
            upgrade_url_to_card=args.upgrade_url_to_card,
        )
    if args.api_fetch_specifics:
        return run_api_fetch_specifics(
            limit=args.limit,
            only_no_key=args.only_no_key,
            dry_run=args.dry_run,
        )
    if args.backfill_keys_from_api:
        return run_backfill_keys_from_api(dry_run=args.dry_run)
    if args.backfill_keys_from_cert:
        return run_backfill_keys_from_cert(dry_run=args.dry_run)
    if args.upgrade_keys_to_category:
        return run_upgrade_keys_to_category(dry_run=args.dry_run)
    if args.check_csv:
        # Step 4: --legacy-tuple-mode 明示なしなら single-key (= resolver 経由) で実行
        if args.legacy_tuple_mode:
            return run_check_csv(csv_path=args.check_csv, dry_run=args.dry_run)
        return run_check_csv_canonical(
            csv_path=args.check_csv,
            dry_run=args.dry_run,
            mark_dups=args.mark_dups,
            strict_mode=args.strict_skip_unresolved,
        )
    if args.write_keys_from_csv:
        # Step 4: --legacy-tuple-mode 明示なしなら single-key (= resolver 経由) で実行
        if args.legacy_tuple_mode:
            return run_write_keys_from_csv(
                csv_path=args.write_keys_from_csv, dry_run=args.dry_run
            )
        return run_write_keys_from_csv_canonical(
            csv_path=args.write_keys_from_csv, dry_run=args.dry_run
        )
    return run(only_tab=args.tab, dry_run=args.dry_run)


# ============================================================================
# Step 4 (= 2026-06-10) CLI 経路: single-key mode 実行関数群
# ============================================================================

def run_archive_key2(dry_run: bool = False) -> int:
    """HIGH/LOW スプシの KEY2 列 header を KEY2_ARCHIVED rename (= 1 回 effort)."""
    from . import sheet_io
    client = sheet_io.authorize_client()
    for label, sid in [("HIGH", sheet_io.HIGH_SHEET_ID), ("LOW", sheet_io.LOW_SHEET_ID)]:
        try:
            sh = sheet_io.open_spreadsheet(sid, client=client)
            ws = sh.worksheet("商品管理シート")
            col = sheet_io.archive_key2_column(ws, dry_run=dry_run)
            if col is None:
                print(f"[{label}] KEY2 列なし → rename skip")
            else:
                action = "skip (dry-run)" if dry_run else "rename 完了"
                print(f"[{label}] KEY2 列 (= col {col}) → KEY2_ARCHIVED  ({action})")
        except Exception as exc:
            print(f"[{label}] エラー: {exc}", file=sys.stderr)
    return 0


def run_check_csv_canonical(
    csv_path: str,
    dry_run: bool = False,
    mark_dups: bool = False,
    strict_mode: bool = False,
) -> int:
    """Step 4 single-key check_csv: resolver 経由 canonical KEY 突合 + 表示/実体 SSOT.

    mark_dups (= 2026-06-12 scope1): 重複除外 row に対応する LOW B空 row の D列に
    "DUP" 自動書込。 dry-run=True なら件数のみ、 False なら本書込 + .bak 保存。

    strict_mode (= 2026-06-16 デフォルト False に是正):
    - **False (デフォルト)**: 解決不能 (unresolved) row は **keep**。 物理除外するのは
      既存 KEY 完全一致の **真の重複だけ**。 これがグローバル原則
      `failclosed_must_skip_not_destructive` (= 判定不能は skip、 破壊的動作に倒さない)
      の正。 6/16 Mercari (Porter/montbell/tshirt/reel) 全除外事故の根本対応:
      catalog KEY を持たない 1 点もの商品が全 unresolved → 全除外 → CSV 0 行、 を防ぐ。
    - True (opt-in、 `--strict-skip-unresolved`): 解決不能 row も物理除外 (= 出品 skip)。
      「dedup で解決できない = 出品もしない」 を明示的に選ぶ listing-safety 用途のみ。
      ※ 出品可否の fail-closed は listing script (psa_to_csv) が既に identity で担保済の
        ため、 dedup 段で unresolved を消すのは原則 over-reach。 既定では使わない。
    """
    from pathlib import Path
    from . import csv_check, sheet_io

    print(f"[*] CSV check (single-key mode, dry_run={dry_run}): {csv_path}", flush=True)
    client = sheet_io.authorize_client()

    # HIGH/LOW から既存 canonical KEY set 構築 (= 真の live filter)
    # 2026-07-13 是正 (BUILD `..._livefilter_itemid_fix_build.md`):
    #   ACTIVE = **itemID(B)非空 AND sold(D)空** = 今 eBay に live 出品中の個体のみ。
    #   旧: item_id_col=A(URL) 代用 → A(仕入元URL)だけ有り B 空の **未出品キュー行(orphan)** を
    #       既存扱いに混入 → 未出品なのに新規候補を誤ブロック + 補URL の live 保証崩壊。
    #   → item_id_col=B(itemID) に是正。 これで「弾いた = live 出品中」を構造保証。
    existing_keys: set = set()
    for label, sid in [("HIGH", sheet_io.HIGH_SHEET_ID), ("LOW", sheet_io.LOW_SHEET_ID)]:
        sh = sheet_io.open_spreadsheet(sid, client=client)
        ws = sh.worksheet("商品管理シート")
        key_col = sheet_io.find_canonical_key_column(ws)
        if key_col is None:
            print(f"[{label}] KEY 列なし、 skip")
            continue
        keys = sheet_io.read_canonical_keys(
            ws,
            key_col=key_col,
            active_only=True,
            sold_col=sheet_io.LISTINGS_COL_SOLD,
            item_id_col=sheet_io.LISTINGS_COL_ITEMID,  # B(itemID) = live の真実 (= 2026-07-13 是正)
        )
        for k in keys:
            if k:
                existing_keys.add(k.strip())
        print(f"[{label}] 既存 canonical KEY 数 (= live のみ): {len(keys)}")

    result = csv_check.check_csv_canonical(
        csv_path=Path(csv_path),
        existing_canonical_keys=frozenset(existing_keys),
        dry_run=dry_run,
        strict_mode=strict_mode,
    )

    # 2026-07-13: 既存 set は itemID(B) 基準 = live 出品中のみ で構築したため、
    # removed_canonical_keys は **全て live 出品中の個体に一致** = 補URL の live 保証 True。
    # HQ 側 補URL plumbing (= 除外KEY の live primary 行に補URL を貯める) で使う。
    result["live_guaranteed"] = True
    result["removed_keys_live"] = list(result.get("removed_canonical_keys") or [])

    print()
    print(f"  mode            : {'strict (unresolved も除外)' if strict_mode else 'keep-unresolved (= 既定、 除外は真の重複のみ)'}")
    print(f"  existing set     : live のみ (= itemID(B)非空 AND sold(D)空)、 live_guaranteed={result['live_guaranteed']}")
    print(f"  total           : {result['total']}")
    print(f"  removed (真の重複・全て live 一致): {result['removed']}")
    print(f"  kept (残存)     : {result['kept']}  (= unresolved {result['unknown']} 件を含む)" if not strict_mode else f"  kept (残存)     : {result['kept']}")
    print(f"  unknown (解決不能・keep): {result['unknown']}")
    print(f"  skipped_unresolved (= strict 除外): {result['skipped_unresolved']}")
    if result["backup_path"]:
        print(f"  backup_path     : {result['backup_path']}")
    if result["removed_titles"][:5]:
        print(f"  removed sample:")
        for t in result["removed_titles"][:5]:
            print(f"    {t}")

    # === 2026-06-12 scope1: DUP マーカー書込 (= --mark-dups オプション) ===
    removed_keys = result.get("removed_canonical_keys") or []
    if mark_dups and removed_keys:
        from . import dup_marker
        from datetime import datetime
        # HIGH/LOW 再 fetch (= 上で open 済の sh は閉じてないが、 dup_marker 内で再 get_all_values)
        ws_high = sh_h = sheet_io.open_spreadsheet(sheet_io.HIGH_SHEET_ID, client=client).worksheet("商品管理シート")
        ws_low = sheet_io.open_spreadsheet(sheet_io.LOW_SHEET_ID, client=client).worksheet("商品管理シート")
        bak_path = None
        if not dry_run:
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            bak_path = Path(f"C:/dev/iMak_data/dedupe/requests/{ts}_dup_mark_scope1_LOW.bak.json")
        mark_result = dup_marker.mark_dup_in_low(
            ws_high, ws_low,
            removed_canonical_keys=removed_keys,
            dry_run=dry_run,
            category_filter="G-shock",
            backup_path=bak_path,
        )
        print()
        print(f"  === DUP マーカー書込 (scope1) ===")
        print(f"  removed canonical KEYs: {len(removed_keys)} 件 → {removed_keys[:5]}...")
        print(f"  LOW marked (= D列 DUP): {mark_result['marked']} (dry_run={mark_result['dry_run']})")
        if mark_result["backup_path"]:
            print(f"  .bak: {mark_result['backup_path']}")
        if mark_result["sample"][:5]:
            print(f"  sample:")
            for s in mark_result["sample"][:5]:
                print(f"    {s}")
    return 0


def run_fullscan_dup_mark(dry_run: bool = True) -> int:
    """2026-06-12 scope2: LOW R='G-shock' B空 AND D空 全件 → resolver 解決 → 既存と一致を一括 DUP マーク.

    依頼書 §scope2 (= 初回フルスキャン、 ユーザー必須要望):
    - 146 件規模 (= 6/12 時点) を一括処理
    - dry-run で件数のみ報告 → ユーザー確認 → 本実行
    - fail-closed: 既存出品 KEY 完全一致のみ
    """
    from datetime import datetime
    from pathlib import Path
    from . import dup_marker, resolver_io, sheet_io

    print(f"[*] fullscan DUP mark (scope2, dry_run={dry_run})", flush=True)
    client = sheet_io.authorize_client()

    ws_high = sheet_io.open_spreadsheet(sheet_io.HIGH_SHEET_ID, client=client).worksheet("商品管理シート")
    ws_low = sheet_io.open_spreadsheet(sheet_io.LOW_SHEET_ID, client=client).worksheet("商品管理シート")

    bak_path = None
    if not dry_run:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        bak_path = Path(f"C:/dev/iMak_data/dedupe/requests/{ts}_dup_mark_scope2_LOW.bak.json")

    result = dup_marker.fullscan_dup_mark(
        ws_high, ws_low,
        resolve_sheet_row_fn=resolver_io.resolve_sheet_row,
        dry_run=dry_run,
        category_filter="G-shock",
        backup_path=bak_path,
    )

    print()
    print(f"  scanned (B空 AND D空 G-shock 行) : {result['scanned']}")
    print(f"  resolved (canonical KEY 取得)    : {result['resolved']}")
    print(f"  unresolved (= fail-closed keep)  : {result['unresolved']}")
    print(f"  existing 出品 KEY 数 (HIGH+LOW)  : {result['existing_keys_count']}")
    print(f"  matched 既存 (= DUP マーク対象)  : {result['matched_existing']}")
    print(f"  marked (= 実書込件数)             : {result['marked']} (dry_run={result['dry_run']})")
    if result["backup_path"]:
        print(f"  .bak: {result['backup_path']}")
    if result["sample"][:10]:
        print(f"  sample (top 10):")
        for s in result["sample"][:10]:
            print(f"    {s}")
    return 0


def run_write_keys_from_csv_canonical(csv_path: str, dry_run: bool = False) -> int:
    """Step 4 single-key write_keys_from_csv: resolver 経由 canonical KEY 書込."""
    from pathlib import Path
    from . import csv_write_keys, sheet_io

    print(
        f"[*] write_keys_from_csv (single-key mode, dry_run={dry_run}): {csv_path}",
        flush=True,
    )
    client = sheet_io.authorize_client()
    sh = sheet_io.open_spreadsheet(sheet_io.HIGH_SHEET_ID, client=client)
    ws = sh.worksheet("商品管理シート")
    key_col = sheet_io.find_canonical_key_column(ws)
    if key_col is None:
        print("HIGH スプシ KEY 列なし、 abort")
        return 1
    cert_col = sheet_io.HIGH_COL_CERT_OR_ENGTITLE
    category_col = sheet_io.HIGH_COL_CATEGORY

    result = csv_write_keys.write_canonical_key_to_high(
        ws=ws,
        csv_path=Path(csv_path),
        key_col=key_col,
        cert_col=cert_col,
        category_col=category_col,
        tcg_category_value="TCG",
        dry_run=dry_run,
    )

    print()
    print(f"  csv rows                : {result['csv_rows']}")
    print(f"  csv with cert           : {result['csv_with_cert']}")
    print(f"  HIGH TCG rows           : {result['high_tcg_rows']}")
    print(f"  matched                 : {result['matched']}")
    print(f"  written_key (新規)      : {result['written_key']}")
    print(f"    ├ written_with_category: {result.get('written_with_category', 0)}  (= {{category}}:{{pid}} 新形式)")
    print(f"    └ written_bare_pid     : {result.get('written_bare_pid', 0)}  (= category 空 bare。 0 のはず)")
    print(f"  upgraded url→product_id : {result['upgraded_url_to_product_id']}")
    print(f"  skipped_no_cert         : {result['skipped_no_cert']}")
    print(f"  skipped_cert_unmatched  : {result['skipped_cert_unmatched']}")
    print(f"  skipped_no_resolution   : {result['skipped_no_resolution']}")
    print(f"  skipped_existing_product_id: {result['skipped_existing_product_id']}")
    if result["samples"][:5]:
        print(f"  samples:")
        for s in result["samples"][:5]:
            print(f"    {s}")
    return 0


def run_backfill_keys_from_cert(dry_run: bool = False) -> int:
    """cert→canonical KEー backfill (= 補URL 実効化、 2026-07-15 BUILD).

    依頼: iMak_data/dedupe/requests/2026-07-15_dedup_cert_backfill_cli_build.md

    HIGH 商品管理シートの **R='TCG' AND B(itemID)空** row のうち KEー 空を対象に、
    cert 経由 (= resolve_sheet_row 内で PSA cache→brand/subject→catalog exact) で
    canonical KEー を解決し空 KEー セルに書込。

    補URL 用途 = product_id 限定:
    - url_col=None → url-key 経路封じ (= 2枚目の仕入URL 由来 url-key は primary と
      不一致で無意味。 backfill_canonical_key は product_id / url_key を書き得るが、
      url 非渡しで product_id か "" のみに絞る)。
    - image_url_col=None → DON image-hash 経路は本 BUILD 対象外 (= 取りこぼし許容)。

    fail-closed / 冪等:
    - 解決不能 ("") は書込まない。
    - 空 KEー セルにのみ書込。 既存 product_id は上書き/削除しない。
    - 再実行で追加 0 (= idempotent)。
    """
    from . import sheet_io

    print(f"[*] cert→KEー backfill (B空・product_id限定, dry_run={dry_run})", flush=True)
    client = sheet_io.authorize_client()
    sh = sheet_io.open_spreadsheet(sheet_io.HIGH_SHEET_ID, client=client)
    ws = sh.worksheet("商品管理シート")
    key_col = sheet_io.find_canonical_key_column(ws)
    if key_col is None:
        print("HIGH スプシ KEー 列なし、 abort")
        return 1

    counts = sheet_io.backfill_canonical_key(
        ws,
        key_col=key_col,
        title_col=sheet_io.LISTINGS_COL_TITLE,          # C
        url_col=None,                                   # product_id 限定 (url-key 封じ)
        cert_col=sheet_io.HIGH_COL_CERT_OR_ENGTITLE,    # I (= R='TCG' なら cert)
        image_url_col=None,                             # DON image 経路は対象外
        dry_run=dry_run,
        item_id_col=sheet_io.LISTINGS_COL_ITEMID,       # B
        upgrade_url_to_card=False,
        only_item_id_empty=True,                        # B空限定
        category_col=sheet_io.HIGH_COL_CATEGORY,        # R
        category_value=sheet_io.HIGH_CATEGORY_TCG_VALUE,  # 'TCG'
    )

    print()
    print(f"  total_rows              : {counts['total_rows']}")
    print(f"  skipped_category_mismatch: {counts['skipped_category_mismatch']}")
    print(f"  skipped_item_id_present : {counts['skipped_item_id_present']}  (= B非空=live/出品済)")
    print(f"  skipped_existing        : {counts['skipped_existing']}  (= KEー既存)")
    print(f"  skipped_no_resolution   : {counts['skipped_no_resolution']}  (= 解決不能 fail-closed)")
    print(f"  written_product_id      : {counts['written_product_id']}  ← 付与行数")
    print(f"    ├ written_with_category: {counts['written_with_category']}  (= {{category}}:{{pid}} 新形式)")
    print(f"    └ written_bare_pid     : {counts['written_bare_pid']}  (= category 空 bare。 0 のはず)")
    print(f"  written_url_key         : {counts['written_url_key']}  (= 0 のはず, url封じ)")
    print(f"  upgraded_url→product_id : {counts['upgraded_url_to_product_id']}")
    if counts["written_url_key"]:
        print("  [!] WARNING: url_key が書かれた (= url封じの想定外)。 要確認")
    if counts["written_bare_pid"]:
        print("  [!] WARNING: category 空の bare pid が書かれた (= Phase2b prefix 想定外)。 要確認")
    return 0


def run_upgrade_keys_to_category(dry_run: bool = False) -> int:
    """既存 bare KEー を {category}:{product_id} に upgrade (= 案B Phase3).

    依頼: 2026-07-27 HQ 返信 (案2 dual-mode 先行 + dedupe が 641+9 を一貫振り直し)。
    HIGH 商品管理シートの bare KEー を、resolver がカテゴリ確定 かつ 再導出 pid が
    既存 bare と一致する時のみ prefix 化 (= 二重 fail-closed)。曖昧は据置 (dual-mode が拾う)。
    """
    from . import sheet_io

    print(f"[*] bare KEー → {{category}}:{{pid}} upgrade (Phase3, dry_run={dry_run})", flush=True)
    client = sheet_io.authorize_client()
    sh = sheet_io.open_spreadsheet(sheet_io.HIGH_SHEET_ID, client=client)
    ws = sh.worksheet("商品管理シート")
    key_col = sheet_io.find_canonical_key_column(ws)
    if key_col is None:
        print("HIGH スプシ KEー 列なし、 abort")
        return 1

    counts = sheet_io.upgrade_bare_keys_to_category(
        ws,
        key_col=key_col,
        title_col=sheet_io.LISTINGS_COL_TITLE,          # C
        cert_col=sheet_io.HIGH_COL_CERT_OR_ENGTITLE,    # I
        url_col=sheet_io.LISTINGS_COL_URL,              # A
        image_url_col=7,                                # G = 写真URL
        dry_run=dry_run,
    )

    print()
    print(f"  total_rows              : {counts['total_rows']}")
    print(f"  skipped_empty           : {counts['skipped_empty']}")
    print(f"  skipped_url_key         : {counts['skipped_url_key']}")
    print(f"  skipped_already_prefixed: {counts['skipped_already_prefixed']}  (= 新形式済)")
    print(f"  skipped_no_category     : {counts['skipped_no_category']}  (= category 未確定 fail-closed 据置)")
    print(f"  skipped_pid_mismatch    : {counts['skipped_pid_mismatch']}  (= 再導出pid≠既存 fail-closed 据置)")
    _via_direct = counts.get("upgraded_via_direct_lookup", 0)
    print(f"  upgraded                : {counts['upgraded']}  ← prefix 付与行数")
    print(f"    ├ via resolver        : {counts['upgraded'] - _via_direct}")
    print(f"    └ via direct lookup   : {_via_direct}  (= 2026-07-29 新経路 catalog 直接照会)")
    if counts["by_category"]:
        print(f"  by_category             :")
        for c, n in sorted(counts["by_category"].items(), key=lambda x: -x[1]):
            print(f"    {c}: {n}")
    if counts["samples"]:
        print(f"  samples:")
        for s in counts["samples"][:12]:
            print(f"    {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
