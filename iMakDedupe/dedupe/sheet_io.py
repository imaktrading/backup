"""Google Sheets read/write helper.

接続情報 (= Phase 1 依頼書 §1 / §2 で確定):
- service account json: `c:\\dev\\iMak\\double-hold-421922-7c0d38d3f73d.json`
  (= 抽出くん / 監視くん 共通利用、 重複くんも同じ json で読込)
- 中間スプシ (= 入力): 全 worksheet が対象、 抽出くん書込 schema
- 既存 HIGH / LOW スプシ: 商品管理シート (GID 851100680)、 col A=URL / C=title
- 既存 公式 スプシ: シート1 (col B=title / F=URL) + SKU詳細 (col E=title)

重複くんは **読込が主、 書込は中間スプシの U 列 (= 「既存出品 chk」 列) のみ**。
既存 HIGH/LOW/公式 への書込は **絶対禁止** (= 「触らない」 ルール)。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials


CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# === スプシ ID (Phase 1 依頼書 §1) ===
INTERMEDIATE_SHEET_ID = "1hTdFVGkni4Ih4kZGsBgiCKxpTlOeoO_wJdk8Ek5n41Q"
HIGH_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
LOW_SHEET_ID = "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"
OFFICIAL_SHEET_ID = "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0"

# === HIGH/LOW 商品管理シート (= LISTINGS_GID は両 spreadsheet で共通) ===
LISTINGS_GID = 851100680
LISTINGS_COL_URL = 1     # A — 仕入元URL (= 抽出くん書込。 未出品キュー行にも存在する)
LISTINGS_COL_ITEMID = 2  # B — eBay itemID (= 出品済 = live の唯一の真実。 未出品行は空)
                          # 2026-07-13: 既存判定 filter の live 基準はこれ (= A=URL 代用の是正)
LISTINGS_COL_TITLE = 3   # C
LISTINGS_COL_SOLD = 4    # D — 売切/取下げフラグ (= 空欄=ACTIVE / `○`等=非 ACTIVE)
                          # 2026-05-27: false positive 修正 (= 過去出品との誤一致 防止)
# R 列 = TCG の場合のみ I 列 = PSA cert 番号 (= 5/27 ユーザー指摘 / 重複くん Phase 1h 用)
HIGH_COL_CATEGORY = 18   # R
HIGH_COL_CERT_OR_ENGTITLE = 9  # I — R='TCG' なら cert 番号、 他カテゴリは英語 Title
HIGH_CATEGORY_TCG_VALUE = "TCG"

# === 中間スプシ schema (= 抽出くん書込 sheet_writer.py 流用元と同じ) ===
INT_COL_URL = 1          # A
INT_COL_TITLE = 3        # C
INT_COL_CHECK = 21       # U (= 「既存出品 chk」、 Phase 1 で新設)
INT_CHECK_HEADER = "既存出品 chk"

# === 公式 (101KL6...) ===
OFFICIAL_MAIN_TAB = "シート1"     # メインシート (= 監視くん sheet_updater MAIN_*)
OFFICIAL_MAIN_COL_TITLE = 2       # B
OFFICIAL_MAIN_COL_URL = 6         # F
OFFICIAL_SKU_TAB = "SKU詳細"
OFFICIAL_SKU_COL_TITLE = 5        # E

# === ヘッダー行 検出マーカー (= 1 行目 A 列 が "URL" なら header 扱い) ===
HEADER_MARKERS = {"URL", "url", "仕入元URL", "仕入元 URL"}

# === KEY 列 (Phase 1a 資産化 → Phase 1f で 2 列化) ===
KEY_COLUMN_HEADER = "KEY"  # = Phase 1a/1c で書込済 = Phase 1f で KEY1 に rename
KEY1_COLUMN_HEADER = "KEY1"  # Phase 1f: card_id / 型番 / URL (= 既存 KEY ヘッダ表記の別名)
KEY2_COLUMN_HEADER = "KEY2"  # Phase 1f: variant code (= alt / sec / par / pro / spc / fa / 空)
# Step 4 (= 2026-06-10): KEY2 列廃止に伴う ARCHIVED rename header.
# 履歴保持 + rollback 用、 物理削除はしない。 spec §7.
KEY2_ARCHIVED_HEADER = "KEY2_ARCHIVED"
# 旧 "KEY" ヘッダは KEY1 として継続使用 (= 既存 backfill 結果を破壊しない、 上位互換)


@dataclass(frozen=True)
class IntermediateRow:
    """中間スプシ 1 row.

    - tab_name: worksheet 名 (= 例 `seller_623636774`)
    - row_index: 1-based 行番号 (= 書込時の range 指定に使用)
    - title: C 列
    - url: A 列
    """

    tab_name: str
    row_index: int
    title: str
    url: str


def _credentials_path_or_raise() -> str:
    """credentials json の存在確認. 無ければ raise."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(
            f"service account JSON not found: {CREDS_PATH}\n"
            "= 既存 worker (抽出くん / 監視くん) と共通 path、 環境構築要確認"
        )
    return CREDS_PATH


def authorize_client() -> gspread.Client:
    """gspread client を返す. credentials path は既存 worker と共通."""
    path = _credentials_path_or_raise()
    creds = Credentials.from_service_account_file(path, scopes=SCOPES)
    return gspread.authorize(creds)


def open_spreadsheet(sheet_id: str, client: Optional[gspread.Client] = None):
    gc = client or authorize_client()
    return gc.open_by_key(sheet_id)


def _get_worksheet_by_gid(spreadsheet, gid: int):
    """gid (= 数値の worksheet ID) から worksheet を取得."""
    for ws in spreadsheet.worksheets():
        if ws.id == gid:
            return ws
    raise ValueError(f"gid={gid} worksheet not found in {spreadsheet.title}")


def _is_header_row(first_cell: str) -> bool:
    """1 行目 A 列が header marker なら True."""
    return (first_cell or "").strip() in HEADER_MARKERS


def _safe_cell(row: List[str], col_1based: int) -> str:
    """1-based 列番号 で row から cell 取得. 範囲外なら "" 返す."""
    idx = col_1based - 1
    if 0 <= idx < len(row):
        return (row[idx] or "").strip()
    return ""


# ============================================================================
# 中間スプシ I/O
# ============================================================================

def read_intermediate_rows(
    spreadsheet,
    only_tab: Optional[str] = None,
) -> Iterator[IntermediateRow]:
    """中間スプシ全 worksheet から row を yield.

    only_tab を指定すれば 1 タブのみ (= POC 用)。
    """
    worksheets = spreadsheet.worksheets()
    if only_tab is not None:
        worksheets = [ws for ws in worksheets if ws.title == only_tab]
        if not worksheets:
            raise ValueError(f"tab {only_tab!r} not found in intermediate sheet")

    for ws in worksheets:
        values = ws.get_all_values()
        if not values:
            continue
        start_idx = 1 if _is_header_row(_safe_cell(values[0], INT_COL_URL)) else 0
        for offset, row in enumerate(values[start_idx:], start=start_idx):
            url = _safe_cell(row, INT_COL_URL)
            title = _safe_cell(row, INT_COL_TITLE)
            if not url and not title:
                continue  # 空行 skip
            yield IntermediateRow(
                tab_name=ws.title,
                row_index=offset + 1,  # 1-based
                title=title,
                url=url,
            )


def ensure_check_header(spreadsheet, only_tab: Optional[str] = None) -> None:
    """中間スプシ 各タブ の U1 (= 「既存出品 chk」 header) を確実に書込.

    既に同じ値なら skip。
    """
    worksheets = spreadsheet.worksheets()
    if only_tab is not None:
        worksheets = [ws for ws in worksheets if ws.title == only_tab]

    for ws in worksheets:
        cell = ws.cell(1, INT_COL_CHECK)
        if (cell.value or "").strip() != INT_CHECK_HEADER:
            ws.update_cell(1, INT_COL_CHECK, INT_CHECK_HEADER)


def write_check_flags(
    spreadsheet,
    flags_by_tab: dict,
) -> None:
    """中間スプシ U 列 (= 「既存出品 chk」) に flag をまとめて書込.

    flags_by_tab: {tab_name: [(row_index, flag_string), ...]}
    既存値がある cell は **上書き** (= Phase 1 依頼書 §6 仕様)。
    """
    for ws in spreadsheet.worksheets():
        flags = flags_by_tab.get(ws.title)
        if not flags:
            continue
        # gspread batch_update format: A1 notation range + values
        batch = [
            {
                "range": gspread.utils.rowcol_to_a1(row_index, INT_COL_CHECK),
                "values": [[flag]],
            }
            for row_index, flag in flags
        ]
        if batch:
            ws.batch_update(batch, value_input_option="USER_ENTERED")


# ============================================================================
# 既存 HIGH / LOW スプシ 読込 (= 商品管理シート、 GID 851100680)
# ============================================================================

def read_listings_titles_and_urls(
    spreadsheet,
) -> List[Tuple[str, str]]:
    """商品管理シート (LISTINGS_GID) から (title, url) ペアを返す.

    A 列 = URL / C 列 = title。 header 行 skip。
    """
    ws = _get_worksheet_by_gid(spreadsheet, LISTINGS_GID)
    values = ws.get_all_values()
    if not values:
        return []
    start_idx = 1 if _is_header_row(_safe_cell(values[0], LISTINGS_COL_URL)) else 0
    out: List[Tuple[str, str]] = []
    for row in values[start_idx:]:
        title = _safe_cell(row, LISTINGS_COL_TITLE)
        url = _safe_cell(row, LISTINGS_COL_URL)
        if title or url:
            out.append((title, url))
    return out


# ============================================================================
# 既存 公式 スプシ 読込 (= シート1 + SKU詳細)
# ============================================================================

# ============================================================================
# KEY 列 (Phase 1a 資産化) helper
# ============================================================================

def _detect_next_column(ws) -> int:
    """全 row scan で 最大 col + 1 を返す (= sparse header 対応).

    LOW のように row 1 (header) が sparse で col 21 header 空だが col 21 body に
    日付データある等のケースを正しく検出するため、 全 row scan が必須。
    O(rows × cols) だが ~1500 row × ~35 col 規模なら問題なし。
    """
    values = ws.get_all_values()
    max_col = 0
    for row in values:
        for i, v in enumerate(row, start=1):
            if (v or "").strip():
                max_col = max(max_col, i)
    return max_col + 1


def find_key_column(ws, header: str = KEY_COLUMN_HEADER) -> Optional[int]:
    """KEY 列を探す (= read-only). 無ければ None.

    Phase 1b で KEY 列読込前に「Phase 1a 未実行」 を検出するため。
    """
    row1 = ws.row_values(1)
    for i, v in enumerate(row1, start=1):
        if (v or "").strip() == header:
            return i
    return None


def find_key1_column(ws) -> Optional[int]:
    """KEY1 列を探す: 'KEY1' / 'KEY' どちらの header でも reuse 可.

    Phase 1a/1c で書込まれた既存 'KEY' 列をそのまま KEY1 として継続使用する。
    """
    row1 = ws.row_values(1)
    for i, v in enumerate(row1, start=1):
        s = (v or "").strip()
        if s == KEY1_COLUMN_HEADER or s == KEY_COLUMN_HEADER:
            return i
    return None


def ensure_key_column(
    ws,
    header: str = KEY_COLUMN_HEADER,
    dry_run: bool = False,
) -> int:
    """KEY 列 確保. 既存なら位置 reuse、 無ければ末尾 append.

    - dry_run=True: 検出のみ、 header 書込しない (= 真の read-only)
    - grid 不足 (col > col_count) なら add_cols で expand
    """
    existing = find_key_column(ws, header)
    if existing is not None:
        return existing

    next_col = _detect_next_column(ws)
    if dry_run:
        return next_col

    if next_col > ws.col_count:
        ws.add_cols(next_col - ws.col_count)
    ws.update_cell(1, next_col, header)
    return next_col


def ensure_key1_key2_columns(
    ws,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """KEY1 + KEY2 両列を確保.

    - KEY1: 既存 'KEY' or 'KEY1' header reuse (= Phase 1a の書込結果保持)
    - KEY2: 'KEY2' header 探索、 無ければ KEY1 列の次に append (= AJ 列等)
    返り値: (key1_col, key2_col)
    """
    # KEY1
    key1_col = find_key1_column(ws)
    if key1_col is None:
        next_col = _detect_next_column(ws)
        if not dry_run:
            if next_col > ws.col_count:
                ws.add_cols(next_col - ws.col_count)
            ws.update_cell(1, next_col, KEY1_COLUMN_HEADER)
        key1_col = next_col

    # KEY2
    key2_col = find_key_column(ws, KEY2_COLUMN_HEADER)
    if key2_col is None:
        # 既存 KEY1 列の次に配置 (= AI → AJ 等)
        next_col = max(key1_col + 1, _detect_next_column(ws))
        if not dry_run:
            if next_col > ws.col_count:
                ws.add_cols(next_col - ws.col_count)
            ws.update_cell(1, next_col, KEY2_COLUMN_HEADER)
        key2_col = next_col

    return key1_col, key2_col


def read_key_columns_tuples(
    ws,
    key1_col: int,
    key2_col: int,
    active_only: bool = False,
    sold_col: Optional[int] = None,
    item_id_col: Optional[int] = None,
) -> List[Tuple[str, str]]:
    """KEY1 / KEY2 列を同時読込んで (key1, key2) tuple list を返す.

    Phase 1f 突合用 (= tuple 完全一致で「真の重複」 判定)。
    空 key1 行は除外 (= 突合対象外)。

    2026-05-27 (= ACTIVE filter): ACTIVE 条件 = **itemID 列あり + sold 列空欄**.
    - item_id_col 指定: 空欄 row 除外 (= 未出品)
    - sold_col 指定: 値あり row 除外 (= 売切 / 取下げ)
    どちらか指定があれば該当 filter 適用 (= 両方指定が推奨).
    """
    values = ws.get_all_values()
    if not values:
        return []
    out: List[Tuple[str, str]] = []
    for row in values[1:]:
        if active_only:
            if item_id_col is not None:
                item_id = _safe_cell(row, item_id_col)
                if not item_id:  # 空 = 未出品 → skip
                    continue
            if sold_col is not None:
                sold = _safe_cell(row, sold_col)
                if sold:  # 値あり = 売切 / 取下げ → skip
                    continue
        k1 = _safe_cell(row, key1_col)
        k2 = _safe_cell(row, key2_col)
        if k1:
            out.append((k1, k2))
    return out


def read_key_column_values(
    ws,
    key_col: int,
    active_only: bool = False,
    sold_col: Optional[int] = None,
    item_id_col: Optional[int] = None,
) -> List[str]:
    """ws の KEY 列 (= key_col) から header 除いた全 cell 値を返す.

    Phase 1b の existing index 構築用。 空 cell は "" のまま含む (= 呼出側で filter)。

    2026-05-27 (= ACTIVE filter): ACTIVE 条件 = itemID あり + sold 空欄.
    """
    if active_only and (sold_col is not None or item_id_col is not None):
        values = ws.get_all_values()
        if not values:
            return []
        out: List[str] = []
        for row in values[1:]:
            if item_id_col is not None and not _safe_cell(row, item_id_col):
                continue
            if sold_col is not None and _safe_cell(row, sold_col):
                continue
            out.append(_safe_cell(row, key_col))
        return out
    col_vals = ws.col_values(key_col)
    return col_vals[1:] if col_vals else []


def backfill_key1_key2(
    ws,
    key1_col: int,
    key2_col: int,
    title_col: int,
    url_col: Optional[int],
    priority_extractor2,
    dry_run: bool = False,
    item_id_col: Optional[int] = None,
    snapshot_titles: Optional[dict] = None,
    upgrade_url_to_card: bool = False,
    key_classifier=None,
    catalog_valid_pids: Optional[frozenset] = None,
    cert_col: Optional[int] = None,
    psa_lookup_fns: Optional[Dict] = None,
    image_url_col: Optional[int] = None,
) -> dict:
    """Phase 1f: KEY1 + KEY2 を同時 backfill.

    priority_extractor2: callable(title, url, extra_text="") -> (key1, type1, key2)
        (= dedupe.checker.extract_priority_key2 を渡す)

    動作 (= 各 row):
    1. snapshot title 優先 (= 出品くん生成 eBay 正規 title) → 取れなければ sheet C 列 title
    2. (key1, type1, key2) 抽出
    3. KEY1 列:
       - 既存値 = unknown (= 手動補完) → 完全 skip (KEY2 も触らない)
       - 既存値 = card/model/url (= 自動書込) → URL→card upgrade OR variant 反映で必要なら上書き
       - 既存値 空 → key1 を書込
    4. KEY2 列:
       - 既存値あり → 手動補完尊重で skip
       - 既存値 空 + key2 あり → 書込
    """
    values = ws.get_all_values()
    counts = {
        "total_rows": 0,
        "skipped_existing": 0,
        "skipped_no_extraction": 0,
        "written_card_key1": 0,
        "written_model_key1": 0,
        "written_url_key1": 0,
        "written_key2": 0,
        "snapshot_hits": 0,
        "snapshot_misses": 0,
        "upgraded_url_to_card": 0,
        "upgraded_url_to_model": 0,
    }
    variant_counts: Dict[str, int] = {}
    if not values:
        return {**counts, "variant_breakdown": variant_counts}

    use_snapshot = item_id_col is not None and snapshot_titles is not None

    updates = []
    for offset, row in enumerate(values[1:], start=1):
        row_idx = offset + 1
        counts["total_rows"] += 1

        current_key1 = _safe_cell(row, key1_col)
        current_key2 = _safe_cell(row, key2_col)

        # === title source 選択 (= snapshot 優先、 sheet C 列 fallback) ===
        sheet_title = _safe_cell(row, title_col)
        url = _safe_cell(row, url_col) if url_col else ""
        chosen_title = sheet_title
        if use_snapshot:
            item_id = _safe_cell(row, item_id_col)
            if item_id:
                snap_title = snapshot_titles.get(item_id, "")
                if snap_title:
                    counts["snapshot_hits"] += 1
                    chosen_title = snap_title
                else:
                    counts["snapshot_misses"] += 1

        new_key1, new_type1, new_key2 = priority_extractor2(chosen_title, url)

        # Phase 1k (= 4.2.1 / 2026-05-27): catalog token verify fallback.
        # priority_extractor2 で取れない場合、 title token を catalog valid_pids で
        # 完全一致 verify (= G-shock token 取りこぼし 33 件 / Pokemon 等 統合 cover).
        if not new_key1 and catalog_valid_pids:
            # 遅延 import (= sheet_io が catalog_io に依存しないため module-level 回避)
            from . import catalog_io as _cat
            for source_text in (chosen_title, sheet_title):
                if not source_text:
                    continue
                hit = _cat.find_product_id_in_text(source_text, catalog_valid_pids)
                if hit:
                    new_key1 = hit[0]
                    new_type1 = "card"  # catalog 由来 = product_id 確定
                    break

        # Phase 1q (= 2026-05-28 体系再設計): PSA cert → iMakeBayAPI cache → catalog lookup_*
        # 既存 KEY = URL key の row が対象 (= card key 一気 upgrade 用)。
        # cache hit → brand/subject 取得 → 各 catalog lookup 試行 → product_id 確定 → upgrade.
        # Phase 1r (= 2026-05-28 image_url 渡し): catalog lookup_don が image_url kwarg 対応した場合、
        # signature inspect で自動的に image_url 渡す (= forward-compat、 Catalog B 完成前後で安全動作).
        # Phase 1s (= 2026-05-28 not new_key1 条件削除): priority_extractor2 は URL ありの行で
        # new_key1=URL key を返すため、 `not new_key1` だと PSA cert 経路が永遠に skip される。
        # = current_key1 が URL key の row なら、 priority_extractor2 結果に関係なく PSA cert 試行する。
        if (
            cert_col is not None
            and psa_lookup_fns is not None
            and upgrade_url_to_card
            and current_key1
            and (current_key1.startswith("item:") or current_key1.startswith("shops:"))
            and (not new_key1 or new_type1 == "url")
        ):
            cert_val = _safe_cell(row, cert_col)
            if cert_val:
                from . import iMakeBayAPI_psa_io as _psa_io
                import inspect as _inspect
                psa_meta = _psa_io.get_cached_psa(cert_val)
                if psa_meta:
                    brand = (psa_meta.get("Brand") or "").strip()
                    subject = (psa_meta.get("Subject") or "").strip()
                    # Phase 1s (= 2026-05-28): CardNumber 渡し追加.
                    # lookup_one_piece (= Catalog A 効果) が CardNumber 必須のため、
                    # PSA cache の CardNumber を取得して渡す (= 既存 "" 固定だと None 返却)
                    card_number = (psa_meta.get("CardNumber") or "").strip()
                    image_url = (
                        _safe_cell(row, image_url_col) if image_url_col else ""
                    )
                    if brand or subject:
                        for fn_name, lookup_fn in psa_lookup_fns.items():
                            try:
                                # signature inspect で image_url parameter 対応判定
                                sig = _inspect.signature(lookup_fn)
                                supports_image = "image_url" in sig.parameters
                                if fn_name == "lookup_don":
                                    if supports_image and image_url:
                                        record = lookup_fn(
                                            brand=brand,
                                            subject=subject,
                                            image_url=image_url,
                                        )
                                    else:
                                        record = lookup_fn(
                                            brand=brand, subject=subject
                                        )
                                else:
                                    # 他 lookup (= one_piece/pokemon/yugioh/etc.) も
                                    # image_url 対応すれば自動的に渡す
                                    if supports_image and image_url:
                                        record = lookup_fn(
                                            brand=brand,
                                            card_number=card_number,
                                            subject=subject,
                                            image_url=image_url,
                                        )
                                    else:
                                        record = lookup_fn(
                                            brand=brand,
                                            card_number=card_number,
                                            subject=subject,
                                        )
                            except Exception:
                                record = None
                            # Phase 1s (= 2026-05-28): record key 不整合吸収.
                            # lookup_don = product_id key、 lookup_one_piece = card_id key で
                            # catalog 側 SSOT 統一されていない (= 既知)。 dedupe で吸収。
                            if record:
                                pid = record.get("product_id") or record.get("card_id")
                                if pid:
                                    new_key1 = pid
                                    new_type1 = "card"
                                    break

        # === KEY1 既存値の取扱 ===
        wrote_anything = False
        if current_key1:
            if key_classifier is None:
                # classifier 不在 → 既存値尊重で skip
                pass
            else:
                cur_type = key_classifier(current_key1)
                if cur_type == "unknown":
                    # 手動補完 → 一切触らない
                    counts["skipped_existing"] += 1
                    continue
                # 自動書込値 → upgrade 判定
                if upgrade_url_to_card and cur_type == "url" and new_key1 and new_type1 in ("card", "model"):
                    updates.append(
                        {
                            "range": gspread.utils.rowcol_to_a1(row_idx, key1_col),
                            "values": [[new_key1]],
                        }
                    )
                    if new_type1 == "card":
                        counts["upgraded_url_to_card"] += 1
                    else:
                        counts["upgraded_url_to_model"] += 1
                    wrote_anything = True
        else:
            # KEY1 空 → 新規書込
            if new_key1:
                updates.append(
                    {
                        "range": gspread.utils.rowcol_to_a1(row_idx, key1_col),
                        "values": [[new_key1]],
                    }
                )
                if new_type1 == "card":
                    counts["written_card_key1"] += 1
                elif new_type1 == "model":
                    counts["written_model_key1"] += 1
                elif new_type1 == "url":
                    counts["written_url_key1"] += 1
                wrote_anything = True

        # === KEY2 既存値の取扱 ===
        # KEY1 が unknown (手動補完) のケースは continue で上で skip 済、 ここに来ない
        if not current_key2 and new_key2:
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_idx, key2_col),
                    "values": [[new_key2]],
                }
            )
            counts["written_key2"] += 1
            variant_counts[new_key2] = variant_counts.get(new_key2, 0) + 1
            wrote_anything = True

        if not wrote_anything and current_key1:
            counts["skipped_existing"] += 1
        elif not wrote_anything and not current_key1 and not new_key1:
            counts["skipped_no_extraction"] += 1

    if updates and not dry_run:
        CHUNK = 500
        for i in range(0, len(updates), CHUNK):
            ws.batch_update(updates[i : i + CHUNK], value_input_option="USER_ENTERED")

    return {**counts, "variant_breakdown": variant_counts}


def backfill_key_column(
    ws,
    key_col: int,
    title_col: int,
    url_col: Optional[int],
    priority_extractor,
    dry_run: bool = False,
    item_id_col: Optional[int] = None,
    snapshot_titles: Optional[dict] = None,
    upgrade_url_to_card: bool = False,
    key_classifier=None,
) -> dict:
    """ws の KEY 列に regex 抽出値を backfill.

    既に値ある cell は skip (= 手動補完を尊重)。
    title/URL 両方空の row は skip。

    title 優先順位 (Phase 1c):
      1. snapshot_titles (= eBay 正規 title、 出品くん生成 = card_id / 型番含む確率高)
         - item_id_col / snapshot_titles 両方 set のときのみ有効
      2. スプシ C 列 title (= fallback、 抽出くん書込)
      URL は最後の resort (= extract_priority_key の責務)

    Phase 1d-TCG 解釈 B (= upgrade_url_to_card=True):
      既存 KEY 値が URL 型 (= 自動書込 fallback) の場合、 強化 regex + snapshot title で
      card_id / 型番 抽出を再試行。 取れたら URL → card_id/型番 で上書き。
      手動補完 (= classify_existing_key で "unknown") / 既 card_id / 既 型番 は不変。
      key_classifier: callable(key_str) -> type ("url"/"card"/"model"/"unknown"/...)
        (= dedupe.checker.classify_existing_key を渡す)

    priority_extractor: callable(title: str, url: str) -> (key, key_type)
        (= dedupe.checker.extract_priority_key を渡す)

    Return counts:
        - total_rows / skipped_existing / skipped_no_extraction
        - written_card / written_model / written_url
        - snapshot_hits (= snapshot title から抽出成功)
        - snapshot_misses (= item ID あったが snapshot に無い、 例 売切)
        - fallback_to_sheet_title (= snapshot 抽出失敗 or 不在で C 列 fallback 成功)
        - upgraded_url_to_card / upgraded_url_to_model (= Phase 1d-TCG 解釈 B)
    """
    values = ws.get_all_values()
    counts = {
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
    if not values:
        return counts

    use_snapshot = item_id_col is not None and snapshot_titles is not None

    updates = []
    for offset, row in enumerate(values[1:], start=1):
        row_idx = offset + 1  # 1-based
        counts["total_rows"] += 1

        current_key = _safe_cell(row, key_col)
        if current_key:
            # Phase 1d-TCG 解釈 B: 既存 URL KEY → card_id/型番 upgrade 試行
            if upgrade_url_to_card and key_classifier is not None:
                current_type = key_classifier(current_key)
                if current_type == "url":
                    # snapshot title or sheet title から 強化 regex で再抽出
                    item_id = _safe_cell(row, item_id_col) if item_id_col else ""
                    new_title = ""
                    if use_snapshot and item_id:
                        new_title = snapshot_titles.get(item_id, "") or ""
                    if not new_title:
                        new_title = _safe_cell(row, title_col)
                    new_key, new_type = priority_extractor(new_title, "")
                    if new_key and new_type in ("card", "model"):
                        updates.append(
                            {
                                "range": gspread.utils.rowcol_to_a1(row_idx, key_col),
                                "values": [[new_key]],
                            }
                        )
                        if new_type == "card":
                            counts["upgraded_url_to_card"] += 1
                        else:
                            counts["upgraded_url_to_model"] += 1
                        continue
            counts["skipped_existing"] += 1
            continue

        sheet_title = _safe_cell(row, title_col)
        url = _safe_cell(row, url_col) if url_col else ""

        # Phase 1c: snapshot 優先抽出
        key, key_type = None, ""
        snapshot_attempted = False
        if use_snapshot:
            item_id = _safe_cell(row, item_id_col)
            if item_id:
                snapshot_title = snapshot_titles.get(item_id)
                if snapshot_title:
                    snapshot_attempted = True
                    key, key_type = priority_extractor(snapshot_title, url)
                    if key:
                        counts["snapshot_hits"] += 1
                else:
                    counts["snapshot_misses"] += 1

        # fallback: C 列 sheet title
        if not key:
            key, key_type = priority_extractor(sheet_title, url)
            if key and snapshot_attempted:
                counts["fallback_to_sheet_title"] += 1
            elif key and use_snapshot and not snapshot_attempted:
                # snapshot 試行せず (= item ID 空 or snapshot 未使用) に sheet title で成功
                counts["fallback_to_sheet_title"] += 1

        if not sheet_title and not url and not key:
            counts["skipped_no_extraction"] += 1
            continue

        if not key:
            counts["skipped_no_extraction"] += 1
            continue

        updates.append(
            {
                "range": gspread.utils.rowcol_to_a1(row_idx, key_col),
                "values": [[key]],
            }
        )
        counts[f"written_{key_type}"] += 1

    if updates and not dry_run:
        # gspread は 1 リクエスト 数千 update OK だが安全策で chunk 化
        CHUNK = 500
        for i in range(0, len(updates), CHUNK):
            ws.batch_update(updates[i : i + CHUNK], value_input_option="USER_ENTERED")

    return counts


def read_official_titles_and_urls(
    spreadsheet,
) -> List[Tuple[str, str]]:
    """公式スプシ から (title, url) ペアを返す.

    - メインシート (`シート1`): col B=title / col F=URL
    - SKU詳細: col E=title / URL なし → url="" で append

    どちらも 1 行目は header 扱い (= 既知 schema)。
    """
    out: List[Tuple[str, str]] = []

    # メインシート
    try:
        ws_main = spreadsheet.worksheet(OFFICIAL_MAIN_TAB)
        values = ws_main.get_all_values()
        for row in values[1:]:  # row 0 = header
            title = _safe_cell(row, OFFICIAL_MAIN_COL_TITLE)
            url = _safe_cell(row, OFFICIAL_MAIN_COL_URL)
            if title or url:
                out.append((title, url))
    except gspread.exceptions.WorksheetNotFound:
        pass  # tab 不在は許容 (= 公式 schema は時期で変動)

    # SKU詳細
    try:
        ws_sku = spreadsheet.worksheet(OFFICIAL_SKU_TAB)
        values = ws_sku.get_all_values()
        for row in values[1:]:
            title = _safe_cell(row, OFFICIAL_SKU_COL_TITLE)
            if title:
                out.append((title, ""))
    except gspread.exceptions.WorksheetNotFound:
        pass

    return out


# ============================================================================
# Step 4 (= 2026-06-10): canonical KEY 単一化 API
# spec: iMak_data/KEY_REDESIGN_SPEC.md §2, §7
# - KEY2 列 ARCHIVED rename (= 物理削除しない、 履歴保持)
# - KEY1 列を canonical KEY 列として継続使用
# - read / backfill ともに resolver 経由
# ============================================================================

def archive_key2_column(ws, dry_run: bool = False) -> Optional[int]:
    """KEY2 列の header を KEY2_ARCHIVED に rename (= 履歴保持、 物理削除しない).

    Step 4 spec §7、 ユーザー判断 (= ARCHIVED rename 採用)。

    Returns:
        rename した列番号 (1-based) / 既に ARCHIVED 済なら同位置 / KEY2 列無し なら None
    """
    archived = find_key_column(ws, KEY2_ARCHIVED_HEADER)
    if archived is not None:
        return archived  # 既に ARCHIVED 済 (= idempotent)
    key2_col = find_key_column(ws, KEY2_COLUMN_HEADER)
    if key2_col is None:
        return None  # KEY2 列無し → rename 不要
    if not dry_run:
        ws.update_cell(1, key2_col, KEY2_ARCHIVED_HEADER)
    return key2_col


def find_canonical_key_column(ws) -> Optional[int]:
    """canonical KEY 列を探す.

    Step 4 spec: KEY1 列 (= 既存 'KEY' or 'KEY1' header) をそのまま canonical 列として継続。
    """
    return find_key1_column(ws)


def read_canonical_keys(
    ws,
    key_col: int,
    active_only: bool = False,
    sold_col: Optional[int] = None,
    item_id_col: Optional[int] = None,
) -> List[str]:
    """ws の canonical KEY 列から header 除いた値 list を返す (= 単一値).

    Step 4 spec §2: 単一値で突合 (= tuple 廃止).
    既存 read_key_column_values と同型 signature だが、 戻り値は明示的に「単一 canonical 値」 と扱う。

    ACTIVE filter: itemID 列あり + sold 列空欄 (= 2026-05-27 仕様維持).
    """
    return read_key_column_values(
        ws,
        key_col=key_col,
        active_only=active_only,
        sold_col=sold_col,
        item_id_col=item_id_col,
    )


def backfill_canonical_key(
    ws,
    key_col: int,
    title_col: int,
    url_col: Optional[int] = None,
    cert_col: Optional[int] = None,
    image_url_col: Optional[int] = None,
    dry_run: bool = False,
    item_id_col: Optional[int] = None,
    snapshot_titles: Optional[dict] = None,
    upgrade_url_to_card: bool = False,
    only_item_id_empty: bool = False,
    category_col: Optional[int] = None,
    category_value: Optional[str] = None,
) -> dict:
    """Step 4: canonical KEY を resolver 経由で取得し KEY 列 (= 単一列) に書込.

    spec §1, §2: 単一 canonical KEY (= product_id | url-key | "").
    旧 backfill_key1_key2 と異なり:
    - KEY2 列を touch しない (= ARCHIVED 済前提)
    - 抽出は extract_canonical_key (= resolver 経由) 1 箇所のみ
    - 解決不能 ("") は書込しない (= fail-closed、 keep over remove)

    upgrade_url_to_card: True なら url 既存値を product_id で上書き許容 (= 5/28 互換挙動).

    2026-07-15 (= cert-backfill CLI BUILD、 補URL 実効化):
    - only_item_id_empty: True なら item_id_col(B) 非空 row を skip
      (= B空=2枚目候補/未出品行のみ対象、 live 出品行の KEー は触らない)。
      True 時は item_id_col 必須。
    - category_col + category_value: 指定時、 当該列が値と一致する row のみ対象
      (= 例 R='TCG' 限定。 cert 由来 backfill は TCG scope に閉じる)。
    """
    import gspread  # 遅延
    from .checker import (
        classify_canonical_key,
        extract_canonical_key_with_category,
        KEY_TYPE_FAILED,
        KEY_TYPE_PRODUCT_ID,
        KEY_TYPE_URL_KEY,
    )

    if only_item_id_empty and item_id_col is None:
        raise ValueError("only_item_id_empty=True には item_id_col が必須")

    values = ws.get_all_values()
    counts = {
        "total_rows": 0,
        "skipped_existing": 0,
        "skipped_no_resolution": 0,
        "written_product_id": 0,
        "written_url_key": 0,
        "snapshot_hits": 0,
        "snapshot_misses": 0,
        "upgraded_url_to_product_id": 0,
        "skipped_item_id_present": 0,
        "skipped_category_mismatch": 0,
        # 2026-07-27 Phase2b: カテゴリ prefix 内訳
        "written_with_category": 0,   # {category}:{pid} で書いた分
        "written_bare_pid": 0,        # category 空で bare pid を書いた分 (= 想定外・要確認)
    }
    if not values:
        return counts

    use_snapshot = item_id_col is not None and snapshot_titles is not None
    updates = []

    for offset, row in enumerate(values[1:], start=1):
        row_idx = offset + 1
        counts["total_rows"] += 1

        # category 限定 (= 例 R='TCG' のみ。 指定なければ全 category)
        if category_col is not None and category_value is not None:
            if _safe_cell(row, category_col).strip() != category_value:
                counts["skipped_category_mismatch"] += 1
                continue

        # B空限定 (= item_id 非空 = live 出品行は touch しない)
        if only_item_id_empty:
            if _safe_cell(row, item_id_col).strip():
                counts["skipped_item_id_present"] += 1
                continue

        current_key = _safe_cell(row, key_col)

        # title source 選択 (= snapshot 優先、 sheet C 列 fallback)
        sheet_title = _safe_cell(row, title_col)
        url = _safe_cell(row, url_col) if url_col else ""
        chosen_title = sheet_title
        if use_snapshot:
            item_id = _safe_cell(row, item_id_col)
            if item_id:
                snap_title = snapshot_titles.get(item_id, "")
                if snap_title:
                    counts["snapshot_hits"] += 1
                    chosen_title = snap_title
                else:
                    counts["snapshot_misses"] += 1

        cert = _safe_cell(row, cert_col) if cert_col else ""
        image_url = _safe_cell(row, image_url_col) if image_url_col else ""

        # 2026-07-27 Phase2b: カテゴリ prefix 込みで解決 ({category}:{product_id})。
        # url-key / 未解決は prefix 無 (build_key が category 空で判別)。
        new_key, new_type = extract_canonical_key_with_category(
            title=chosen_title,
            url=url,
            cert=cert,
            image_url=image_url,
            purpose="dedup",
        )

        if new_type == KEY_TYPE_FAILED:
            if not current_key:
                counts["skipped_no_resolution"] += 1
            else:
                counts["skipped_existing"] += 1
            continue

        wrote = False
        if not current_key:
            # 空 → 書込
            updates.append(
                {
                    "range": gspread.utils.rowcol_to_a1(row_idx, key_col),
                    "values": [[new_key]],
                }
            )
            if new_type == KEY_TYPE_PRODUCT_ID:
                counts["written_product_id"] += 1
                # prefix 内訳 (= `:` 含み かつ url-key でない = catalog-backed)
                if ":" in new_key:
                    counts["written_with_category"] += 1
                else:
                    counts["written_bare_pid"] += 1
            else:
                counts["written_url_key"] += 1
            wrote = True
        else:
            current_type = classify_canonical_key(current_key)
            if (
                upgrade_url_to_card
                and current_type == KEY_TYPE_URL_KEY
                and new_type == KEY_TYPE_PRODUCT_ID
                and current_key != new_key
            ):
                # URL key → product_id upgrade
                updates.append(
                    {
                        "range": gspread.utils.rowcol_to_a1(row_idx, key_col),
                        "values": [[new_key]],
                    }
                )
                counts["upgraded_url_to_product_id"] += 1
                wrote = True
            else:
                counts["skipped_existing"] += 1

        if not wrote and not current_key:
            counts["skipped_no_resolution"] += 1

    if updates and not dry_run:
        CHUNK = 500
        for i in range(0, len(updates), CHUNK):
            ws.batch_update(updates[i : i + CHUNK], value_input_option="USER_ENTERED")

    return counts


def upgrade_bare_keys_to_category(
    ws,
    key_col: int,
    title_col: int,
    cert_col: Optional[int] = None,
    url_col: Optional[int] = None,
    image_url_col: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """既存 bare KEー を `{category}:{product_id}` に upgrade (= 案B Phase3).

    依頼: iMak_data/dedupe/requests/2026-07-27_key_category_phase3_sync_needed.md
          + `_hq_response_phase3_and_cache_warming.md`（HQ が dedupe 一貫振り直しを採用）

    対象: KEー **非空・bare(`:` 無し)・非 url-key** の row。

    二重 fail-closed（誤カテゴリ・別 pid 焼き込み防止）:
    - resolver が **category を確定** (= 非空) しない → 据置（bare のまま）
    - resolver 再導出 product_id が **既存 bare KEー と不一致** → 据置
      （= 同一カードの KEー に prefix を足すだけ、という不変を保証）
    これで曖昧 9 行も cert→PSA brand で確定できる分のみ upgrade、
    決められない分は bare 据置（dual-mode が拾う）。

    既存の product_id 自体は変えない（prefix を足すだけ）。url-key は対象外。
    """
    import gspread  # 遅延
    from .checker import extract_canonical_key_with_category
    from .key_format import parse_key

    values = ws.get_all_values()
    counts = {
        "total_rows": 0,
        "skipped_empty": 0,
        "skipped_url_key": 0,
        "skipped_already_prefixed": 0,
        "skipped_no_category": 0,   # resolver が category 確定できず（fail-closed 据置）
        "skipped_pid_mismatch": 0,  # 再導出 pid ≠ 既存 bare（fail-closed 据置）
        "upgraded": 0,
        "by_category": {},
        "samples": [],
    }
    if not values:
        return counts

    updates = []
    SAMPLE_MAX = 12

    for offset, row in enumerate(values[1:], start=1):
        row_idx = offset + 1
        counts["total_rows"] += 1

        current = _safe_cell(row, key_col).strip()
        if not current:
            counts["skipped_empty"] += 1
            continue
        if current.startswith(("item:", "shops:")):
            counts["skipped_url_key"] += 1
            continue
        cat0, _pid0 = parse_key(current)
        if cat0:  # 既に prefixed
            counts["skipped_already_prefixed"] += 1
            continue

        # bare key = current。 resolver で再導出 (= 独立にカテゴリ + pid 確定)
        title = _safe_cell(row, title_col)
        cert = _safe_cell(row, cert_col) if cert_col else ""
        url = _safe_cell(row, url_col) if url_col else ""
        image_url = _safe_cell(row, image_url_col) if image_url_col else ""

        new_key, _new_type = extract_canonical_key_with_category(
            title=title, url=url, cert=cert, image_url=image_url, purpose="dedup",
        )
        rcat, rpid = parse_key(new_key)
        if not rcat:
            # url-key / 未解決 / category 不明 → 据置（fail-closed）
            counts["skipped_no_category"] += 1
            continue
        if rpid != current:
            # 再導出 pid が既存 bare と不一致 → 据置（別カードに化ける事故防止）
            counts["skipped_pid_mismatch"] += 1
            continue

        # safe: 同 pid + category 確定 → prefix を足して upgrade
        updates.append(
            {
                "range": gspread.utils.rowcol_to_a1(row_idx, key_col),
                "values": [[new_key]],
            }
        )
        counts["upgraded"] += 1
        counts["by_category"][rcat] = counts["by_category"].get(rcat, 0) + 1
        if len(counts["samples"]) < SAMPLE_MAX:
            counts["samples"].append(f"row {row_idx}: {current} → {new_key}")

    if updates and not dry_run:
        CHUNK = 500
        for i in range(0, len(updates), CHUNK):
            ws.batch_update(updates[i : i + CHUNK], value_input_option="USER_ENTERED")

    return counts
