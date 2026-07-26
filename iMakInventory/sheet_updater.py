"""sheet_updater - SKU シート (Google Sheets) の読込・更新 (独立モジュール).

設計原則:
  - 既存の gspread + サービスアカウント (`double-hold-421922-...json`) を再利用
  - 既存スプシ・タブ構成を一切壊さない (列構成は SKU 詳細シートに準拠)
  - 失敗時は例外送出、main 側でログ + retry 判断

スプシ構造 (SKU 詳細タブ、列 A-L):
  A: 対処要 (TRUE/FALSE chkbox)
  B: 対処済 (TRUE/FALSE chkbox)
  C: 対処日 (YYYY/MM/DD)
  D: listing ID
  E: title
  F: eBay SKU ID
  G: サイズ
  H: 色
  I: 仕入元在庫 (◎ / ✕)
  J: 仕入元価格
  K: eBay 現Qty
  L: 自動CHK日

メインシート構造 (本ファイルが参照):
  A: FLG (1 で除外、それ以外は active)
  D: listing ID
  E: title
  F: 仕入元 URL (uniqlo.com / montbell.com / amazon.co.jp 等)

使用例:
    from sheet_updater import open_sheet, read_main_active_uniqlo_rows, update_sku_rows
    sh = open_sheet()
    rows = read_main_active_uniqlo_rows(sh)
    update_sku_rows(sh, [{...}, {...}])
"""
from __future__ import annotations

import os
import urllib.parse
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials


SPREADSHEET_ID = "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0"
SKU_TAB_NAME = "SKU詳細"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# メインシート列マッピング (1-based)
# 実シート (シート1) header: A=FLG, B=title, C=item ID, D=(空), E=ebay URL, F=URL(仕入元), G=CHK date
MAIN_COL_FLG = 1         # A
MAIN_COL_TITLE = 2       # B
MAIN_COL_LISTING_ID = 3  # C
MAIN_COL_URL = 6         # F (仕入元URL)


# ============================================================================
# HIGH/LOW 商品管理シート (Phase 2 監視対象)
# ============================================================================
HIGH_SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
LOW_SHEET_ID = "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0"
LISTINGS_GID = 851100680  # 商品管理シート タブ (両 spreadsheet で共通)

# HIGH/LOW 商品管理シート列マッピング (1-based)
# header (row 1): A=URL, B=itemID, C=タイトル, D=売り切れ, E=状態, F=商品価格,
#                 G=写真URL, H=商品説明, I=Title, J=Description, K=出品する価格(ドル),
#                 L=ConditionID, M=価格上昇有無, N=仕入れ価格(円), O=売り切れチェック時間
#                 (中略 P-AB は listing 側のメタ列)
#                 AC-AG=補 URL 1〜5 (HIGH のみ、2026-05-10 追加 / multi-sourcing fallback)
LISTINGS_COL_URL = 1          # A: 仕入元 URL (Mercari/Amazon)
LISTINGS_COL_ITEM_ID = 2      # B: eBay listing ID
LISTINGS_COL_TITLE = 3        # C: タイトル (日本語)
LISTINGS_COL_SOLD = 4         # D: 売り切れ ← Inventory が "○" を書く
LISTINGS_COL_PRICE = 6        # F: 出品時の価格 (¥) ← 触らない (履歴保存)
# ★ 2026-07-22 HQ 依頼: 「書き手は観測値のみ・N はシート関数」設計へ移行。
#   監視くんの書き先を N(14) → M(12) に変更。 N は誰も書かず HQ が =(M or F)−K の ARRAYFORMULA 化。
#   K(11)=基本ポイント(円) を amazon 行に追加書込。 切替順序: Inventory deploy(本変更) → HQ 関数化。
LISTINGS_COL_POINTS = 11      # K: 基本ポイント (¥) ← Inventory(amazon 毎 cycle) + Harvest(capture 時)
# ★ 実シートのヘッダを実機確認して確定 (2026-07-22): 依頼書の「M列(12)」は番号誤記。
#   実際は col11=K'ポイント(円)' / col12=L'ConditionID'(既存) / col13=M'現在価格(円)' / col14=N'仕入れ価格（円）'。
#   現在価格は列13(=文字M)。列12(L)は ConditionID なので書込厳禁 (破損する)。
LISTINGS_COL_PRICE_NOW_M = 13  # M: 現在価格 (¥) ← Inventory が毎 cycle 上書き (None なら維持)
LISTINGS_COL_PRICE_NOW = 14   # N: =(M or F)−K の関数 (誰も書かない)。read は AH(前期N) の退避元に使う
LISTINGS_COL_CHECKED_AT = 15  # O: 売り切れチェック時間
LISTINGS_COL_BACKUP_URL_1 = 29  # AC: 補仕入URL #1 (空欄 OK、HIGH のみ)
LISTINGS_COL_BACKUP_URL_2 = 30  # AD: 補仕入URL #2
LISTINGS_COL_BACKUP_URL_3 = 31  # AE: 補仕入URL #3
LISTINGS_COL_BACKUP_URL_4 = 32  # AF: 補仕入URL #4
LISTINGS_COL_BACKUP_URL_5 = 33  # AG: 補仕入URL #5
LISTINGS_COL_BACKUP_URLS = (
    LISTINGS_COL_BACKUP_URL_1, LISTINGS_COL_BACKUP_URL_2,
    LISTINGS_COL_BACKUP_URL_3, LISTINGS_COL_BACKUP_URL_4,
    LISTINGS_COL_BACKUP_URL_5,
)
LISTINGS_COL_PRICE_PREV = 34  # AH: 前期 N (毎 cycle で旧 N がコピーされる、Revise が短期 trend に利用)
LISTINGS_COL_KEY = 35         # AI: KEY (= 型番/productNumber)。yodobashi snapshot lookup のキー (2026-07-26)
# AK: 巡回ERR (scrape error / 在庫不能 row のマーカー、成功で clear)。2026-06-11 追加。
# AJ=KEY2_ARCHIVED の次の空き列に append (= 既存列の挿入/ズレ無し、grid は BA=53 まで存在)。
LISTINGS_COL_ERR_FLG = 37     # AK
LISTINGS_ERR_FLG_HEADER = "巡回ERR"
# 売切日時 (行が完全売切=newly_sold になった瞬間の日時、1 回記録)。churn 型番チューニング用 (HQ 消費)。
# ★ 2026-07-25 実機ヘッダ確認: 依頼書「AL=38 が空」は誤り (AL=38='値下FLG(pp)' 使用中 / AM=39 は
#   ヘッダ空だが 463 セルにデータ有=使用中 / AN=40='仕入override(手動)')。header 長=40、AO=41 は
#   完全未使用 (col_values=0) → AK と同じ末尾 append 方式で AO=41 に新設。HQ に列訂正を報告済。
LISTINGS_COL_SOLD_AT = 41     # AO
LISTINGS_SOLD_AT_HEADER = "売切日時"

# ── 補URL 売切消込 急増ガード (2026-07-25) ─────────────────────────────────
# 1 cycle の補URL消込数が異常に多い = scraper の系統的誤 is_sold=True でデータ不具合の疑い
# (2026-06-03 偽OOS 95件型)。閾値超で一括自動消込を止めて告知 (誤一括消去防止)。
CLEAR_SURGE_THRESHOLD = 20    # 1 cycle でこの件数超の補URL消込が出たら HOLD + ALERT

# ── 価格急増ガード (M/K 書込側、2026-07-23) ──────────────────────────────
# scraper の DOM 構造変化で 1 supplier が丸ごと誤パースし、多数行に「plausible だが誤った」
# 現在価格が一括で M に landing する事故 (履歴: 2026-06 amazon buybox DOM 化で全滅 /
# scraper_price_vulnerability「最初の¥」誤採用) を防ぐ。発火単位は supplier (真の failure
# mode に一致)。閾値超で「その supplier の M/K 書込のみ HOLD」+ ALERT。D/O (取下げ) は
# 絶対に止めない (fail-OPEN=取下げ漏れ が最悪、価格汚染防止とは別レイヤ)。
# グローバル原則 #4「急増ガード (誤一括防止)」の価格版。
PRICE_SURGE_THRESHOLD = 0.5    # 前 M からの |Δ| がこの割合超 = 「急変行」(±50%)
PRICE_SURGE_MIN_ROWS = 10      # 判定に要する supplier あたり最小 (prev-M ありの) 価格行数
PRICE_SURGE_MIN_RATIO = 0.5    # 急変行 / 判定対象行 がこの割合以上 → 系統崩壊とみなし HOLD


# ============================================================================
# 認証 / スプシオープン
# ============================================================================
def open_sheet():
    """サービスアカウント認証 → spreadsheet オブジェクト返却."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"サービスアカウント JSON が見つかりません: {CREDS_PATH}")
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(SPREADSHEET_ID)


def get_main_worksheet(sh):
    """メインシート (1番目のシート想定、または 'メイン' / 'main' 名の検索)."""
    for name_candidate in ("メイン", "main", "Main", "Sheet1"):
        try:
            return sh.worksheet(name_candidate)
        except gspread.WorksheetNotFound:
            continue
    # フォールバック: 最初のシート
    return sh.get_worksheet(0)


def get_sku_worksheet(sh):
    """SKU 詳細シート."""
    return sh.worksheet(SKU_TAB_NAME)


# ============================================================================
# HIGH/LOW 商品管理シート (Phase 2)
# ============================================================================
def open_sheet_by_id(spreadsheet_id: str):
    """指定 spreadsheet_id を開く (HIGH/LOW 等の別 spreadsheet 用)."""
    if not os.path.exists(CREDS_PATH):
        raise FileNotFoundError(f"サービスアカウント JSON が見つかりません: {CREDS_PATH}")
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(spreadsheet_id)


def get_listings_worksheet(sh, gid: int = LISTINGS_GID):
    """商品管理シート (gid=851100680 想定) を取得.
    指定 gid が無ければ最初の worksheet にフォールバック.
    """
    for ws in sh.worksheets():
        if ws.id == gid:
            return ws
    return sh.get_worksheet(0)


def read_listings_rows(
    ws,
    start_row: int = 2,
    end_row: Optional[int] = None,
    only_with_url: bool = True,
) -> list:
    """商品管理シートの URL 一覧を読込.

    Args:
        ws:           gspread worksheet (HIGH or LOW の商品管理シート)
        start_row:    開始行 (1-based, header をスキップするため default=2)
        end_row:      終了行 (1-based, inclusive, None なら最終行まで)
        only_with_url: A 列が空の行を skip する (default True)

    Returns: [
        {
            "row_index":     2 (1-based シート行),
            "url":           "https://jp.mercari.com/item/m...",
            "item_id":       "356700921169" (eBay listing ID),
            "title":         "...",
            "current_sold":  "○" / "" (D 列の現状値),
            "price":         "¥1,500" (生文字列、parse は呼出側),
            "checked_at":    "2026/4/29 16:00:25",
        },
        ...
    ]
    """
    all_values = ws.get_all_values()
    if not all_values:
        return []

    rows = []
    last = end_row if end_row is not None else len(all_values)
    for idx in range(start_row, last + 1):
        if idx > len(all_values):
            break
        row = all_values[idx - 1]
        url = (row[LISTINGS_COL_URL - 1] if len(row) >= LISTINGS_COL_URL else "").strip()
        if only_with_url and not url:
            continue
        # backup_urls: 空を詰めた list (後方互換、位置情報なし)。
        # backup_url_slots: 固定 5 枠 positional (AC-AG に 1:1、空セルは None)。
        # ★ 2026-07-25: 補URL消込/売切stamp/色塗りは「どの列か」の位置精度が Precision 100% の前提。
        #   空詰め backup_urls は消込で穴 (AC消→AD残) ができると index↔列 がズレ誤セルを消す →
        #   positional slots を正とする (懸念1 解消)。
        backup_urls = []
        backup_url_slots = []
        for col in LISTINGS_COL_BACKUP_URLS:
            v = (row[col - 1] if len(row) >= col else "").strip()
            backup_url_slots.append(v if v else None)
            if v:
                backup_urls.append(v)
        rows.append({
            "row_index":    idx,
            "url":          url,
            "item_id":      (row[LISTINGS_COL_ITEM_ID - 1] if len(row) >= LISTINGS_COL_ITEM_ID else "").strip(),
            "title":        (row[LISTINGS_COL_TITLE - 1] if len(row) >= LISTINGS_COL_TITLE else "").strip(),
            "current_sold": (row[LISTINGS_COL_SOLD - 1] if len(row) >= LISTINGS_COL_SOLD else "").strip(),
            "price":        (row[LISTINGS_COL_PRICE - 1] if len(row) >= LISTINGS_COL_PRICE else "").strip(),
            "checked_at":   (row[LISTINGS_COL_CHECKED_AT - 1] if len(row) >= LISTINGS_COL_CHECKED_AT else "").strip(),
            "backup_urls":  backup_urls,  # AC-AG (#29-33) のうち空でないもの (後方互換)
            "backup_url_slots": backup_url_slots,  # AC-AG 固定 5 枠 positional (空=None)。消込/stamp/色塗り用
            "key_number":   (row[LISTINGS_COL_KEY - 1] if len(row) >= LISTINGS_COL_KEY else "").strip(),  # AI: 型番 (yodobashi lookup)
            # 現在の N 列値 (生文字列、空欄も含む)。次 cycle で AH (前期 N) にコピーされる
            "current_n_jpy_str": (row[LISTINGS_COL_PRICE_NOW - 1] if len(row) >= LISTINGS_COL_PRICE_NOW else "").strip(),
            # 現在の M 列値 (=前 cycle に書いた現在価格、移行済 LOW/HIGH 両シート)。価格急増ガードの
            # like-with-like 比較元 (prev-M vs 新 price_jpy)。N(=M-K) で代用すると points 分オフセットが乗る。
            "current_m_jpy_str": (row[LISTINGS_COL_PRICE_NOW_M - 1] if len(row) >= LISTINGS_COL_PRICE_NOW_M else "").strip(),
            # AK 列 (巡回ERR) の現状値 = 前 cycle までの連続エラー marker。re-mark 時の回数累積に使う
            "err_flag_prev": (row[LISTINGS_COL_ERR_FLG - 1] if len(row) >= LISTINGS_COL_ERR_FLG else "").strip(),
        })
    return rows


def _parse_price_jpy(s) -> Optional[int]:
    """スプシ生文字列 (¥1,500 / '1500' / '' 等) を int(円) へ。parse 不能 → None."""
    if s is None:
        return None
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def detect_price_surge(updates: list,
                       threshold: float = PRICE_SURGE_THRESHOLD,
                       min_rows: int = PRICE_SURGE_MIN_ROWS,
                       min_ratio: float = PRICE_SURGE_MIN_RATIO) -> tuple:
    """supplier 単位の価格急増 (= scraper 系統崩壊疑い) を検出.

    prev-M (current_m_jpy_str) と新 price_jpy を like-with-like 比較し、|Δ|/prev > threshold
    の「急変行」割合が min_ratio 以上 かつ 判定対象が min_rows 以上の supplier を HOLD 対象とする。
    prev-M が無い/parse 不能な行、price_jpy 未セット行は判定母数から除外 (= 初回 cycle は誤発火しない)。

    Returns: (held_suppliers: set[str], stats: dict[str, {"total","surged","ratio"}])
    """
    per_supplier: dict = {}
    for u in updates:
        pj = u.get("price_jpy")
        if not (isinstance(pj, int) and not isinstance(pj, bool) and pj >= 0):
            continue
        prev = _parse_price_jpy(u.get("current_m_jpy_str"))
        if prev is None or prev <= 0:
            continue
        sup = u.get("supplier") or "unknown"
        d = per_supplier.setdefault(sup, {"total": 0, "surged": 0})
        d["total"] += 1
        if abs(pj - prev) / prev > threshold:
            d["surged"] += 1

    held = set()
    stats = {}
    for sup, d in per_supplier.items():
        tot, surg = d["total"], d["surged"]
        ratio = (surg / tot) if tot else 0.0
        stats[sup] = {"total": tot, "surged": surg, "ratio": round(ratio, 3)}
        if tot >= min_rows and ratio >= min_ratio:
            held.add(sup)
    return held, stats


def update_listings_sold_marks(ws, updates: list,
                               price_col_idx: int = LISTINGS_COL_PRICE_NOW_M,
                               enable_points: bool = True,
                               enable_price_surge_guard: bool = True) -> dict:
    """商品管理シートの D 列 (売り切れ) / O 列 (チェック時間) / 現在価格列 / K 列 (ポイント) を batch 更新.

    ★ 2026-07-22 HQ 依頼で書き先を N→M へ変更 + K 追加 (N は関数化するため誰も書かない)。

    price_col_idx: 現在価格の書込先列 (1-based)。移行済シート(LOW)=M(13)、未移行(HIGH)=N(14)。
                   caller が sheet 毎に指定する (HIGH は HQ 準備前のため従来の N 書込を維持する)。
    enable_points: K(ポイント) 書込を有効化するか。★2026-07-22 HQ hold notice でポイント抽出の
                   欠陥調査中につき運用上は False (K 汚染再発防止)。Harvest 修正確定後に True へ戻す。

    Args:
        ws:      gspread worksheet
        updates: [
            {
                "row_index":  2 (1-based),
                "is_sold":    True / False (o_only=True 時は無視),
                "checked_at": "2026/04/29 17:00:00" (省略時は now),
                "o_only":     True なら D 列を触らず O 列のみ更新 (Phase 9 fix),
                "price_jpy":  int (現在価格、None or 省略時は M 列を触らない = 既存値維持),
                "points_jpy": int (基本ポイント¥、amazon 行のみ caller が載せる。表示なし→0。
                              省略/None → K 列を触らない = 既存値維持),
            },
            ...
        ]

    書込ルール:
      - o_only=True → O 列のみ書込 (エラー行 / 変化なし行で D 列を上書きしない)
      - o_only 省略 / False → D + O 両方書込
      - D 列: is_sold=True → "○", False → "" (人手 ○ を上書きしない場合は呼出側で制御)
      - O 列: 全 update に timestamp を書く (= trabajo 同等仕様、巡回チェック日時)
      - M 列: price_jpy が int (>=0) で渡された行のみ書込。None / 省略 → 既存値維持
        (一時的取得失敗で価値情報を消すリスク回避、trabajo SheetRow.cs n_nowPrice 同等仕様)
        ※ D/O 列のロジックには一切影響しない (purely additive)
      - K 列: points_jpy が int (>=0) で渡された行のみ書込 (= M を書く行に限る)。None / 省略 → 既存値維持。
        caller は amazon 在庫あり行でのみ points_jpy をセット (表示なし→0 の確定観測 / fetch 失敗→不触)。
      - N 列: 一切書かない (HQ が =(M or F)−K の ARRAYFORMULA を設置)。
      - AH 列 (前期 N): M 列を書く前に prev_n_jpy_str (= read 時の N 計算値) を AH にコピー。
        prev_n_jpy_str が空なら touch しない (= 初回 cycle の AH は空のまま、Revise 側で考慮)。
        このコピーは "M 列 を新値で上書きする時のみ" 走る = 価格の動きに連動した historical snapshot。
      - AK 列 (巡回ERR): update dict に "err_flag" キーがあれば (空文字含む) AK 列に書込。
        エラー行 → marker 文字列 / 成功行 → "" (clear)。キー不在の行は AK を touch しない。

    Returns: {"updated": N, "d_writes": N, "o_writes": N, "m_writes": N, "k_writes": N,
              "ah_writes": N, "err_writes": N, "surge_held": [supplier...], "surge_stats": {...}}
    """
    if not updates:
        return {"updated": 0, "d_writes": 0, "o_writes": 0, "m_writes": 0, "k_writes": 0,
                "ah_writes": 0, "err_writes": 0, "sold_at_writes": 0,
                "surge_held": [], "surge_stats": {}}

    # ── 価格急増ガード (supplier 単位) ──
    # scraper 系統崩壊で多数行に誤価格が一括 landing する事故を防ぐ。HOLD 対象 supplier の行は
    # M/K 書込のみ skip (D/O は下で通常どおり書く = 取下げは絶対止めない)。
    surge_held: set = set()
    surge_stats: dict = {}
    if enable_price_surge_guard:
        surge_held, surge_stats = detect_price_surge(updates)

    cell_updates = []
    d_writes = 0
    o_writes = 0
    m_writes = 0
    k_writes = 0
    ah_writes = 0
    err_writes = 0
    sold_at_writes = 0   # AO 売切日時 書込行数
    m_held = 0   # 急増ガードで M 書込を見送った行数
    for u in updates:
        row_idx = u["row_index"]
        checked_at = u.get("checked_at") or datetime.now().strftime("%Y/%m/%d %H:%M:%S")

        if not u.get("o_only", False):
            is_sold = bool(u.get("is_sold", False))
            cell_updates.append({
                "range": f"D{row_idx}",
                "values": [["○" if is_sold else ""]],
            })
            d_writes += 1

        cell_updates.append({
            "range": f"O{row_idx}",
            "values": [[checked_at]],
        })
        o_writes += 1

        # M 列 (現在価格): price_jpy が int で渡された場合のみ書込。None / 不在 / 非 int は触らない。
        # ★ 2026-07-22: 旧実装は N(14) に書いていたが、 N はシート関数化するため書き先を M(12) に変更。
        # ★ 2026-07-23: 価格急増ガードで HOLD 対象 supplier の行は M/K 書込を skip (D/O は通常どおり)。
        price_jpy = u.get("price_jpy")
        if (u.get("supplier") or "unknown") in surge_held:
            if isinstance(price_jpy, int) and not isinstance(price_jpy, bool) and price_jpy >= 0:
                m_held += 1   # 本来 M を書く行を急増ガードで見送った (= stale 維持、fail-closed)
        elif isinstance(price_jpy, int) and not isinstance(price_jpy, bool) and price_jpy >= 0:
            # AH 列 (前期 N): M を上書きする前に read 時の N 計算値 (prev_n_jpy_str) をコピー
            # (= "前 cycle の N" を保存)。 N 関数化後は N セルの計算値を退避する形になる。
            prev_n_str = u.get("prev_n_jpy_str", "")
            if prev_n_str:
                cell_updates.append({
                    "range": f"AH{row_idx}",
                    "values": [[prev_n_str]],
                })
                ah_writes += 1
            cell_updates.append({
                "range": f"{_col_letter(price_col_idx)}{row_idx}",  # 移行済=M(13) / 未移行=N(14)
                "values": [[price_jpy]],
            })
            m_writes += 1

            # K 列 (基本ポイント ¥): amazon 行のみ caller が points_jpy を載せる (表示なし→0)。
            # fetch 失敗行は price_jpy=None で上の gate に入らず、 ここも実行されない = K 不触。
            # 「同一フェッチで M と K を一貫更新」= 旧M−現pt の N過小を構造的に回避 (HQ 2026-07-22)。
            # ★ enable_points=False (HQ hold notice 2026-07-22) の間は K を書かない (欠陥調査中)。
            points_jpy = u.get("points_jpy")
            if (enable_points and isinstance(points_jpy, int)
                    and not isinstance(points_jpy, bool) and points_jpy >= 0):
                cell_updates.append({
                    "range": f"{_col_letter(LISTINGS_COL_POINTS)}{row_idx}",  # K
                    "values": [[points_jpy]],
                })
                k_writes += 1

        # AK 列 (巡回ERR): "err_flag" キーがあれば書込 (空文字 = clear も明示書込)。
        # キー不在 = AK 非対応 caller (= 既存呼出元) → AK を一切 touch しない (後方互換)。
        if "err_flag" in u:
            cell_updates.append({
                "range": f"{_col_letter(LISTINGS_COL_ERR_FLG)}{row_idx}",
                "values": [[u["err_flag"]]],
            })
            err_writes += 1

        # AO 列 (売切日時): "sold_at" キー (非空 str) があれば書込。行が完全売切 (newly_sold) に
        # なった瞬間の日時を 1 回記録 (churn 型番チューニング用、HQ 消費)。空/None → 触らない。
        sold_at = u.get("sold_at")
        if isinstance(sold_at, str) and sold_at.strip():
            cell_updates.append({
                "range": f"{_col_letter(LISTINGS_COL_SOLD_AT)}{row_idx}",  # AO
                "values": [[sold_at]],
            })
            sold_at_writes += 1

    ws.batch_update(cell_updates, value_input_option="USER_ENTERED")
    return {"updated": len(updates), "d_writes": d_writes, "o_writes": o_writes,
            "m_writes": m_writes, "k_writes": k_writes, "ah_writes": ah_writes,
            "err_writes": err_writes, "m_held": m_held, "sold_at_writes": sold_at_writes,
            "surge_held": sorted(surge_held), "surge_stats": surge_stats}


def _col_letter(n: int) -> str:
    """1-based 列番号 → A1 列文字 (例 37 -> 'AK')."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def ensure_listings_err_header(ws) -> bool:
    """商品管理シート AK1 に「巡回ERR」ヘッダを設定 (未設定時のみ).

    Returns: True なら新規書込、False なら既に設定済 (no-op)。
    """
    col = LISTINGS_COL_ERR_FLG
    try:
        cur = ws.cell(1, col).value
    except Exception:
        cur = None
    if (cur or "").strip() == LISTINGS_ERR_FLG_HEADER:
        return False
    ws.update(values=[[LISTINGS_ERR_FLG_HEADER]],
              range_name=f"{_col_letter(col)}1",
              value_input_option="USER_ENTERED")
    return True


def ensure_sold_at_header(ws) -> bool:
    """商品管理シート AO1 に「売切日時」ヘッダを設定 (未設定時のみ).

    ★ 2026-07-25: AO=41 は実機ヘッダ確認で完全未使用 (col_values=0) を確認した末尾 append 先。
      依頼書の「AL=38」は使用中 (値下FLG) だったため訂正。header 書込前に現値を確認し、別ラベルが
      入っていたら **上書きせず False を返す** (他列の誤上書き=破損を防ぐ、M12/M13 事故の教訓)。

    Returns: True なら新規書込、False なら既設 or 別ラベル在で no-op。
    """
    col = LISTINGS_COL_SOLD_AT
    try:
        cur = (ws.cell(1, col).value or "").strip()
    except Exception:
        cur = None
    if cur == LISTINGS_SOLD_AT_HEADER:
        return False
    if cur:
        # 想定外の既存ラベル → 触らない (安全側)。caller が warning を出す。
        return False
    ws.update(values=[[LISTINGS_SOLD_AT_HEADER]],
              range_name=f"{_col_letter(col)}1",
              value_input_option="USER_ENTERED")
    return True


# ============================================================================
# 補 URL セル (AC-AG) の色塗り
# ============================================================================
# AC-AG (#29-33) のセル列レター
_BACKUP_URL_COLUMN_LETTERS = ("AC", "AD", "AE", "AF", "AG")

# 売切 URL = 赤字 (default 黒に対する明示的な color override)
_RED_RGB = {"red": 1.0, "green": 0.0, "blue": 0.0}
_DEFAULT_RGB = {"red": 0.0, "green": 0.0, "blue": 0.0}   # 黒 (= clear と同等)


def paint_backup_url_cells(ws, paints: list) -> dict:
    """補 URL セル (AC-AG) のフォント色を batch 更新.

    Args:
        ws: gspread worksheet
        paints: [
            {
                "row_index": 100 (1-based シート行),
                "states":    ["sold", "in_stock", "sold", "unknown", "in_stock"],
                # 各補 URL の状態。長さ 5 (= AC-AG)。空欄 row や未確認は "unknown"
                # "sold"     → 赤字
                # "in_stock" → 黒字 (default)
                # "error"    → 黒字 (default、不確定なので赤字にしない)
                # "unknown"  → 黒字 (default、補 URL 空欄 or 未 scrape)
            },
            ...
        ]

    Returns: {"painted": N, "red_cells": N, "default_cells": N}

    実装メモ: Sheets API の repeatCell リクエストで cell range を batch 更新。
    既存 batch_update API ではなく Spreadsheet 直 batchUpdate を使う必要がある
    (ws.format() は 1 range / 呼出だが、複数 range の batch を 1 call にまとめる)。
    """
    if not paints:
        return {"painted": 0, "red_cells": 0, "default_cells": 0}

    requests = []
    red_cells = 0
    default_cells = 0
    sheet_id = ws.id

    for p in paints:
        row_idx = p["row_index"]
        states = p.get("states") or []
        for col_offset, col_letter in enumerate(_BACKUP_URL_COLUMN_LETTERS):
            state = states[col_offset] if col_offset < len(states) else "unknown"
            if state == "sold":
                rgb = _RED_RGB
                red_cells += 1
            else:
                rgb = _DEFAULT_RGB   # 黒字 (in_stock / error / unknown)
                default_cells += 1
            # AC-AG = column index 28-32 (0-based)
            col_index_0based = 28 + col_offset
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row_idx - 1,    # 0-based
                        "endRowIndex": row_idx,
                        "startColumnIndex": col_index_0based,
                        "endColumnIndex": col_index_0based + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {
                                "foregroundColor": rgb,
                            }
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.foregroundColor",
                }
            })

    if requests:
        ws.spreadsheet.batch_update({"requests": requests})

    return {"painted": len(paints), "red_cells": red_cells, "default_cells": default_cells}


def clear_sold_backup_cells(ws, clear_candidates: list,
                            enable_surge_guard: bool = True) -> dict:
    """売切確定 (is_sold=True) の補URL (AC-AG) セルを compare-and-clear で消込.

    ★ 2026-07-25 実装 (HQ 補URL能動充填 Phase2 の消し手)。役割分離: HQ=空き枠に足す /
      監視=売切確定セルを消す。狙い=死んだ補URLが枠を埋め続けて HQ が新供給を足せなくなるのを防ぐ。

    必須ガード (全AI共通原則):
      - fail-closed: caller は is_sold=True 確定の候補のみ渡す (error/uncertain は渡さない)。
      - compare-and-clear (懸念2 解消): 書込直前にセルを **re-read** し、監視が is_sold=True と確認した
        URL 文字列とセル現在値が一致する時だけ消す。HQ が別の生きた新URLに差し替えていれば不一致 →
        消さない (skipped_mismatch = 要対応、silent drop しない)。役割分離のタイミングの穴を構造的に塞ぐ。
      - 主URL(col A) は対象外 (candidates は補URL 列のみ)。
      - 消込急増ガード: 候補が CLEAR_SURGE_THRESHOLD 超なら一括自動消込を止めて HOLD (誤一括消去防止)。

    Args:
        clear_candidates: [{"row_index": int, "slot": 0-4, "expected_url": str}]
                          slot 0-4 = AC-AG (列 29+slot)。expected_url = 監視が is_sold=True と見た URL。
        enable_surge_guard: 消込急増ガードを有効化 (default True、緊急 override 用に False 可)。

    Returns: {"cleared": N, "skipped_mismatch": [...], "held": bool,
              "candidate_count": N, "surge": bool}
    """
    n = len(clear_candidates)
    if n == 0:
        return {"cleared": 0, "skipped_mismatch": [], "held": False,
                "candidate_count": 0, "surge": False, "cleared_entries": []}

    # 消込急増ガード: 異常件数なら消込せず HOLD (caller が ALERT)。
    if enable_surge_guard and n > CLEAR_SURGE_THRESHOLD:
        return {"cleared": 0, "skipped_mismatch": [], "held": True,
                "candidate_count": n, "surge": True, "cleared_entries": []}

    # 対象 row の AC-AG を書込直前に re-read (compare-and-clear)。
    rows = sorted({c["row_index"] for c in clear_candidates})
    ac = _col_letter(LISTINGS_COL_BACKUP_URL_1)   # AC
    ag = _col_letter(LISTINGS_COL_BACKUP_URL_5)   # AG
    ranges = [f"{ac}{r}:{ag}{r}" for r in rows]
    got = ws.batch_get(ranges)
    cur = {}
    for r, g in zip(rows, got):
        vals = (list(g[0]) if g else [])
        cur[r] = vals

    cell_updates = []
    cleared = 0
    skipped = []
    cleared_entries = []   # ★ 消した内容 (row/slot/col/url) = 復元用アーカイブに載せる (データ安全)
    for c in clear_candidates:
        r = c["row_index"]
        slot = c["slot"]
        expected = (c["expected_url"] or "").strip()
        vals = cur.get(r, [])
        actual = (vals[slot].strip() if slot < len(vals) and vals[slot] else "")
        if expected and actual == expected:
            col = _col_letter(LISTINGS_COL_BACKUP_URL_1 + slot)
            cell_updates.append({"range": f"{col}{r}", "values": [[""]]})   # クリア
            cleared += 1
            cleared_entries.append({"row_index": r, "slot": slot, "col": col, "url": expected})
        else:
            # HQ 差替 / 既に変化 / 空 → 消さない (silent drop 禁止、要対応として返す)
            skipped.append({"row_index": r, "slot": slot,
                            "expected_url": expected, "actual": actual})

    if cell_updates:
        ws.batch_update(cell_updates, value_input_option="USER_ENTERED")

    return {"cleared": cleared, "skipped_mismatch": skipped, "held": False,
            "candidate_count": n, "surge": False, "cleared_entries": cleared_entries}


RESCUE_LOG_TAB = "補URL救済ログ"
RESCUE_LOG_HEADER = ["日付", "itemID", "タイトル", "生存backupSlot", "主URL状態", "backupURL"]


def append_rescue_log_rows(sh, events: list) -> dict:
    """補URL救済イベントを `補URL救済ログ` タブに追記 (フック2、2026-07-25)。

    救済 = 主URL(A) 売切確定 AND 補URL≥1本 在庫あり (= 補が取下げを防いだ = Phase1 救済率の signal)。
    caller (monitor) が遷移ベース dedup 済の新規救済のみ渡す。

    ★ gspread の append_rows は false success があるため使わない ([[gspread_append_rows_unreliable]])。
      col A の現行行数を読み、次行から明示 range で ws.update する。

    Args:
        events: [{"item_id","title","backup_slot","main_status","backup_url","date"}]

    Returns: {"appended": N, "tab": RESCUE_LOG_TAB}
    """
    if not events:
        return {"appended": 0, "tab": RESCUE_LOG_TAB}

    # タブ取得 or 新規作成 (header 付き)
    try:
        ws_log = sh.worksheet(RESCUE_LOG_TAB)
    except gspread.WorksheetNotFound:
        ws_log = sh.add_worksheet(title=RESCUE_LOG_TAB, rows=1000, cols=len(RESCUE_LOG_HEADER))
        ws_log.update(values=[RESCUE_LOG_HEADER], range_name="A1",
                      value_input_option="USER_ENTERED")

    # header 未設定 (空タブ) なら設定
    existing = ws_log.col_values(1)
    if not existing:
        ws_log.update(values=[RESCUE_LOG_HEADER], range_name="A1",
                      value_input_option="USER_ENTERED")
        existing = [RESCUE_LOG_HEADER[0]]

    next_row = len(existing) + 1
    rows = [[
        e.get("date", ""),
        e.get("item_id", ""),
        (e.get("title", "") or "")[:80],
        e.get("backup_slot", ""),
        e.get("main_status", ""),
        (e.get("backup_url", "") or "")[:200],
    ] for e in events]
    end_row = next_row + len(rows) - 1
    ws_log.update(values=rows,
                  range_name=f"A{next_row}:F{end_row}",
                  value_input_option="USER_ENTERED")
    return {"appended": len(rows), "tab": RESCUE_LOG_TAB}


# ============================================================================
# メインシート読込
# ============================================================================
def _domain_of(url: str) -> str:
    """URL から netloc (ドメイン) を返す.

    protocol 抜けの URL ("amazon.co.jp/dp/...") も許容する:
    urllib.parse.urlparse はスキーム無しだと netloc を空に解釈するため、
    "://" が無ければ "https://" を仮プレフィックスして再 parse する。
    入力ミスで supplier 判定失敗 → 在庫漏れになるのを防ぐ (漏れ NG 原則)。
    """
    if not url:
        return ""
    s = url.strip()
    if "://" not in s:
        s = "https://" + s
    try:
        return urllib.parse.urlparse(s).netloc.lower()
    except Exception:
        return ""


def detect_supplier(domain: str) -> str:
    """URL ドメインから supplier 名を判定.
    対応: uniqlo / montbell / mercari / amazon / fril / other (= 未対応)
    """
    d = (domain or "").lower()
    if "uniqlo.com" in d:
        return "uniqlo"
    if "montbell.jp" in d:
        return "montbell"
    if "mercari.com" in d or "mercari.jp" in d:
        return "mercari"
    if "amazon.co.jp" in d or "amazon.com" in d:
        return "amazon"
    if "fril.jp" in d:
        return "fril"
    if "snkrdunk.com" in d:
        return "snkrdunk"
    if "yodobashi.com" in d:
        return "yodobashi"   # G-shock 補仕入元 (Harvest の HTTP snapshot を型番で lookup、2026-07-26)
    return "other"


def read_main_active_rows(sh, supplier_filter: str = "all") -> list:
    """メインシートから FLG ≠ 1 (= active) の listing 行を抽出.

    Args:
        supplier_filter: "uniqlo" / "montbell" / "mercari" / "amazon" / "all"
    """
    main_ws = get_main_worksheet(sh)
    all_values = main_ws.get_all_values()
    if not all_values:
        return []

    rows = []
    for idx, row in enumerate(all_values[1:], start=2):
        flg = (row[MAIN_COL_FLG - 1] if len(row) >= MAIN_COL_FLG else "").strip()
        if flg == "1":
            continue
        listing_id = (row[MAIN_COL_LISTING_ID - 1] if len(row) >= MAIN_COL_LISTING_ID else "").strip()
        title = (row[MAIN_COL_TITLE - 1] if len(row) >= MAIN_COL_TITLE else "").strip()
        url = (row[MAIN_COL_URL - 1] if len(row) >= MAIN_COL_URL else "").strip()
        domain = _domain_of(url)
        if not listing_id or not url:
            continue

        supplier = detect_supplier(domain)

        if supplier_filter != "all" and supplier != supplier_filter:
            continue
        if supplier_filter == "all" and supplier == "other":
            continue  # 未対応 supplier はスキップ
        rows.append({
            "row_index": idx,
            "listing_id": listing_id,
            "title": title,
            "url": url,
            "domain": domain,
            "supplier": supplier,
        })
    return rows


# 後方互換: 既存呼出元のため残す
def read_main_active_uniqlo_rows(sh) -> list:
    """[Deprecated] read_main_active_rows(sh, 'uniqlo') と同等."""
    return read_main_active_rows(sh, supplier_filter="uniqlo")


# ============================================================================
# SKU シート読込 / 書込
# ============================================================================
def read_sku_rows(sh) -> list:
    """SKU 詳細シートの全行 (header 除く) を返す."""
    sku_ws = get_sku_worksheet(sh)
    all_values = sku_ws.get_all_values()
    if len(all_values) < 2:
        return []
    return all_values[1:]


def update_sku_rows(sh, updates: list) -> dict:
    """SKU 詳細シートに update を適用.

    Args:
        updates: [
            {
                "row_index":  6 (1-based シート行、None なら append),
                "listing_id": "357401200653",
                "title":      "マンガキュレーション UT",
                "sku_id":     "MK-UT-S-Black" (空可、scraper 由来は communication_code を使う),
                "size":       "S",
                "color":      "BLACK",
                "supplier_stock_mark": "◎" or "✕",
                "supplier_price":     1500,
                "ebay_qty":           1,
                "auto_check_at":      "2026/04/27 10:00",
                "needs_action":       True / False (A列 update 用),
            },
            ...
        ]

    Returns: {"updated": N, "appended": M}
    """
    if not updates:
        return {"updated": 0, "appended": 0}

    sku_ws = get_sku_worksheet(sh)
    all_values = sku_ws.get_all_values()
    last_row = len(all_values)  # 1-based 行数 = 最終行 index

    # append が必要な件数を事前計算 → grid 拡張 (Range exceeds grid limits 対策)
    append_needed = sum(1 for u in updates if u.get("row_index") is None)
    if append_needed > 0:
        target_total_rows = last_row + append_needed + 50  # +50 はバッファ
        if target_total_rows > sku_ws.row_count:
            sku_ws.add_rows(target_total_rows - sku_ws.row_count)

    # batch_update でまとめて書込 (API quota 節約)
    cell_updates = []
    appended_count = 0
    updated_count = 0

    for u in updates:
        row_idx = u.get("row_index")
        if row_idx is None:
            # append: 末尾の次の行
            last_row += 1
            row_idx = last_row
            appended_count += 1
        else:
            updated_count += 1

        row_values = [
            bool(u.get("needs_action", False)),                  # A: 対処要
            False,                                                # B: 対処済 (新規 update では触らないが、新規 append は False)
            "",                                                   # C: 対処日 (新規 append のみ空)
            str(u.get("listing_id", "")),                         # D
            str(u.get("title", "")),                              # E
            str(u.get("sku_id", "")),                             # F
            str(u.get("size", "")),                               # G
            str(u.get("color", "")),                              # H
            str(u.get("supplier_stock_mark", "")),                # I
            u.get("supplier_price") if u.get("supplier_price") is not None else "",  # J
            u.get("ebay_qty") if u.get("ebay_qty") is not None else "",  # K
            str(u.get("auto_check_at", datetime.now().strftime("%Y/%m/%d %H:%M"))),  # L
        ]

        # 既存行 update 時は B/C 列 (対処済/対処日) を上書きしない (人手判断を尊重)
        if u.get("row_index") is not None:
            existing = all_values[row_idx - 1] if row_idx - 1 < len(all_values) else []
            existing_b = (existing[1] if len(existing) >= 2 else "").strip()
            existing_c = (existing[2] if len(existing) >= 3 else "").strip()
            row_values[1] = existing_b == "TRUE" or existing_b == "True"
            row_values[2] = existing_c

        cell_updates.append({
            "range": f"A{row_idx}:L{row_idx}",
            "values": [row_values],
        })

    sku_ws.batch_update(cell_updates, value_input_option="USER_ENTERED")

    return {"updated": updated_count, "appended": appended_count}


# ============================================================================
# 対処要判定ヘルパー
# ============================================================================
def determine_needs_action(supplier_in_stock: bool, ebay_qty: int) -> bool:
    """対処要フラグ判定:
      - 仕入元 ✕ かつ eBay Qty > 0  → True (在庫切れだが eBay 出品中、停止検討)
      - 仕入元 ◎ かつ eBay Qty = 0  → True (仕入復活、再開検討)
      - それ以外                    → False
    """
    if supplier_in_stock and ebay_qty == 0:
        return True
    if (not supplier_in_stock) and ebay_qty > 0:
        return True
    return False


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    import sys
    print("=== Open spreadsheet ===")
    sh = open_sheet()
    print(f"  title: {sh.title}")

    print("\n=== Main sheet UNIQLO active rows ===")
    rows = read_main_active_uniqlo_rows(sh)
    print(f"  count: {len(rows)}")
    for r in rows[:5]:
        print(f"  row{r['row_index']}: listing={r['listing_id']} title={r['title'][:30]} url={r['url'][:60]}")

    print("\n=== SKU sheet existing rows (sample) ===")
    sku_rows = read_sku_rows(sh)
    print(f"  count: {len(sku_rows)}")
    for r in sku_rows[:3]:
        print(f"  {r}")
