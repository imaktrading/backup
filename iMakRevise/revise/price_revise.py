"""price_revise.py - 価格 revise (新 logic 2026-05-22 = 現状 vs V8 理想 直接比較).

新 logic (2026-05-22 全面置換):
  filter (= スプシ条件):
    - A 列空欄 → skip (no_url)
    - D 列 = SOLD マーカー → skip (sold)
    - N 列空欄 / range 外 → skip (no_cost)

  異常検出 (= scrape miss ガード):
    - AH↔N delta > 200% → skip + alert (abnormal_delta)

  起動判定 (= 現状 vs V8 理想 直接比較):
    1. N で V8 計算 → V8 USD + V8 Policy 出力
    2. eBay 側 現状 取得:
       - 現USD = HQ snapshot CSV (eBay-all-active-listings-report-*.csv)
       - 現Policy = Trading API GetItem (cache + 不足分 fetch)
    3. 比較:
       - 現USD or 現Policy 未取得 → skip (no_snapshot)
       - 現Policy ≠ V8Policy → **revise** (policy_change)
       - 現USD ≠ V8USD → **revise** (price_diff)
       - 完全一致 → skip (aligned)

  fail-closed:
    - 比較前 normalize 必須 (= revise/normalize.py: policy/usd/url/sold)
    - V8 計算失敗 (Unknown category 等) → skip (v8_calc_failed)
    - 赤字 (profit_jpy < 0) → skip (loss、5/15 事故再発防止)
    - 1 cycle 上限 50 件 (default、--mode all で解除)

スプシ列構成 (商品管理シート):
  A: URL [0] / B: ItemID [1] / C: タイトル [2] / D: 売切 [3]
  F: 出品時¥ [5] / M: フラグ [12] / N: 現仕入¥ [13] / O: CHK [14]
  R: カテゴリ [17] / AH: 前期N¥ [33]

修正連鎖回避:
  - 監視くん (iMakInventory) に修正なし
  - 本元 iMakeBayAPI/pricing_engine は read-only import (SSOT)
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ============================================================================
# パス
# ============================================================================
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REPO_ROOT = PROJECT_ROOT.parent
CSV_OUTPUT_DIR = PROJECT_ROOT / "csv_output"
DECISION_LOG_DIR = PROJECT_ROOT / "decision_log"

# ============================================================================
# スプシ
# ============================================================================
# ============================================================================
# 対象スプシ (2026-05-21 multi-sheet 化): 3 固定 sheet
#   HIGH / LOW: 既存 schema (A=URL, B=ItemID, F=出品¥, N=仕入¥, R=カテゴリ, AH=前期N¥)
#   公式 (UNIQLO/GU drop-shipping): SKU詳細 tab, D=listing ID, J=仕入¥ のみ
#                                    AH/F/R 列なし → 初回 cycle は "no_baseline" で skip (fail-closed)
# ============================================================================
SHEETS = {
    "HIGH": {
        "id": "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk",
        "tab": "商品管理シート",
        "schema": "high_low",
        "label": "HIGH (高価格帯)",
    },
    "LOW": {
        "id": "1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0",
        "tab": "商品管理シート",
        "schema": "high_low",
        "label": "LOW (低価格帯)",
    },
    "公式": {
        "id": "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0",
        "tab": "SKU詳細",
        "schema": "official",
        "label": "公式 (UNIQLO/GU drop-shipping)",
    },
}
ALL_SHEET_KEYS = list(SHEETS.keys())

# 後方互換 (= 既存 cron / smoke で REVISE_SPREADSHEET_ID 渡してた場合)
DEFAULT_SPREADSHEET_ID = SHEETS["HIGH"]["id"]
SPREADSHEET_ID = os.environ.get("REVISE_SPREADSHEET_ID") or DEFAULT_SPREADSHEET_ID
DEFAULT_TAB_NAME = SHEETS["HIGH"]["tab"]
TAB_NAME = os.environ.get("REVISE_TAB_NAME") or DEFAULT_TAB_NAME

DEFAULT_GOOGLE_CREDS_PATH = r"C:/dev/iMak/double-hold-421922-7c0d38d3f73d.json"


def _get_google_creds_path() -> str:
    return os.environ.get("GOOGLE_CREDS_PATH") or DEFAULT_GOOGLE_CREDS_PATH


# 列インデックス (0-based) — HIGH/LOW schema (統合Hight_商品管理シート 準拠)
COL_URL = 0          # A
COL_ITEM_ID = 1      # B (itemID)
COL_TITLE = 2        # C (タイトル、V8 title-based category mapping 用)
COL_SOLD_FLAG = 3    # D (売り切れ)
COL_F_PRICE = 5      # F (商品価格 = 出品時 ¥)
COL_FLAG = 12        # M (価格上昇有無)
COL_N_PRICE = 13     # N (仕入れ価格 ¥)
COL_CHECK_TIME = 14  # O (売り切れチェック時間)
COL_CATEGORY = 17    # R (カテゴリ)
COL_AH_PRICE = 33    # AH (前期 N ¥)
COL_PRICEDOWN_FLG = 37  # AL (値下FLG(pp) = NO_CONVERT 値下げ幅%、HQ noconvert がフル同期書込)
# AL 列は 2026-07-01 から数値pp (既定"5"、人手で"8"等に上書き可、空=非対象)。
# 旧: 文字列 "値下5pp" 固定 → 廃止。

# 公式 SKU詳細 schema
COL_OFFICIAL_LISTING_ID = 3  # D
COL_OFFICIAL_TITLE = 4       # E (商品名)
COL_OFFICIAL_SKU = 5         # F (eBay SKU ID = UUID、2026-05-24 variation 対応)
COL_OFFICIAL_SIZE = 6        # G (サイズ、2026-05-24 variation 対応)
COL_OFFICIAL_COLOR = 7       # H (色、2026-05-24 variation 対応)
COL_OFFICIAL_STOCK = 8       # I (仕入元在庫: ◎=あり / ✕=なし)
COL_OFFICIAL_COST = 9        # J (仕入元価格 = 現在の N 相当)
COL_OFFICIAL_CATEGORY = 15   # P (カテゴリ)
COL_OFFICIAL_PREV_COST = 16  # Q (前期仕入元価格 = AH 相当)

HEADER_ROWS = 1

# ============================================================================
# 検知 / 安全範囲パラメータ (config/revise_params.json から動的読込)
# 計算パラメータ (net_ratio / buffer / shipping) は V8 移行で廃止
# ============================================================================
from . import config_loader  # noqa: E402


def _refresh_constants():
    """config を再読込してモジュールレベル定数を更新."""
    global MIN_JPY, MAX_JPY, ABNORMAL_DELTA_PCT_THRESHOLD
    MIN_JPY = config_loader.get_min_jpy()
    MAX_JPY = config_loader.get_max_jpy()
    ABNORMAL_DELTA_PCT_THRESHOLD = config_loader.get_abnormal_delta_pct_threshold()


# 旧 logic 互換 (= test compat、新 logic では未使用)
DEFAULT_THRESHOLD_PCT = 3.0
MIN_JPY = config_loader.get_min_jpy()
MAX_JPY = config_loader.get_max_jpy()
ABNORMAL_DELTA_PCT_THRESHOLD = config_loader.get_abnormal_delta_pct_threshold()

# 売切フラグ判定値
SOLD_VALUES = {"○", "TRUE", "true", "1", "YES", "yes"}

# eBay revise CSV ヘッダ (FileExchange Revise 形式, 2026-05-21 6 列拡張)
# HQ 5/20 手動 697 件 revise で Failure 0 達成方針 (Option C):
#   - ShippingProfileName 同時更新 (= 価格 tier 変動時の Policy ズレ防止)
#   - BestOfferAutoAcceptPrice + MinimumBestOfferPrice 空欄 (= 23004/22003 衝突回避)
#   - BestOfferEnabled は列追加しない (= eBay 既存設定 維持、Allow offers ON のまま)
REVISE_CSV_HEADER = [
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "ItemID",
    "ShippingProfileName",
    "*StartPrice",
    "BestOfferAutoAcceptPrice",
    "MinimumBestOfferPrice",
]

# ============================================================================
# $X.98 丸め (自前実装、修正連鎖回避)
# ============================================================================
def round_98(price_usd: float) -> float:
    """$X.98 形式に丸め。$10 以下はそのまま round 2 桁."""
    p = round(price_usd, 2)
    if p > 10:
        return int(p) + 0.98
    return p


# ============================================================================
# データ構造
# ============================================================================
@dataclass
class ReviseCandidate:
    row_index: int
    item_id: str
    category: str
    new_jpy: float                                 # N 列 (= 現仕入¥)
    ah_jpy: Optional[float]                        # AH 列 (= 前期 N¥、異常検出のみに使う)
    f_jpy: Optional[float]                         # F 列 (= 出品時¥、参考表示のみ)
    delta_pct: float                               # (N-AH)/AH × 100 (= 異常検出基準)
    basis: str                                     # "decision" (= 新 logic 起動) / "skip" / "abnormal"
    title: str = ""
    source_sheet: str = "HIGH"
    url: str = ""                                  # A 列 (= filter 用)
    sold_flag: str = ""                            # D 列 (= filter 用)
    # V8 計算結果
    new_usd: Optional[float] = None
    shipping_usd: Optional[float] = None
    shipping_profile_name: Optional[str] = None
    buyer_total_usd: Optional[float] = None
    profit_jpy: Optional[float] = None
    # eBay 側 現状 (新 logic で必須)
    current_usd: Optional[float] = None            # snapshot CSV から
    current_policy: Optional[str] = None           # Trading API GetItem から
    available_qty: Optional[int] = None            # snapshot CSV から (= 在庫数)
    # 判定結果
    decision_reason: Optional[str] = None          # "policy_change"/"price_diff"/"aligned"/"sold"/etc
    decision_details: str = ""                     # 詳細 (= log/xlsx 用)
    revise_content: str = ""                       # "USD のみ"/"Policy のみ"/"USD+Policy" (xlsx 用)
    skip_reason: Optional[str] = None              # 旧互換 (= 非 None なら CSV から除外)
    is_abnormal: bool = False                      # AH↔N delta > threshold
    # パック商品 (2026-05-22 追加)
    pack_count: int = 1                            # mapping の pack数 (= 1=通常 listing)
    effective_cost: Optional[float] = None         # N × pack_count (= V8 計算に渡した cost)
    pack_suspect: bool = False                     # title に pack keyword + 未登録 (= 漏れ疑い)
    # variation listing (2026-05-24 追加)
    sku: str = ""                                  # eBay SKU ID (= variation 固有、空なら single listing)
    variation_size: str = ""                       # スプシ G 列
    variation_color: str = ""                      # スプシ H 列
    is_variation: bool = False                     # True なら variation listing の 1 SKU
    # NO_CONVERT 値下げ override (2026-06-30 追加、HIGH/LOW のみ)
    pricedown_flag: str = ""                        # AL 列 (= 正の数値pp なら値下げ対象、cut_pct に使用)
    pricedown_applied: bool = False                 # 実際に override が適用されたか (gate 通過)


@dataclass
class InitTarget:
    """F+AH 両空欄 + N 値あり → F=N で初期化する行 (revise しない)."""
    row_index: int
    item_id: str
    new_jpy: float


@dataclass
class ReviseRunResult:
    candidates: list = field(default_factory=list)
    revisable: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    abnormal: list = field(default_factory=list)  # 異常 delta で skip した分
    init_targets: list = field(default_factory=list)
    csv_path: Optional[str] = None
    var_price_path: Optional[str] = None       # variation 価格 UP CSV
    var_shipping_path: Optional[str] = None     # variation 送料 UP CSV
    review_xlsx_path: Optional[str] = None      # レビュー xlsx (日次自動UP のメール添付用)
    alert_log_path: Optional[str] = None
    cap_exceeded: bool = False  # 旧 logic 互換 (新 logic では常に False)


# ============================================================================
# スプシ読込 (schema-aware)
# ============================================================================
def _gspread_client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        raise RuntimeError(f"gspread / google-auth 未インストール: {e}")

    creds_path = _get_google_creds_path()
    if not Path(creds_path).exists():
        raise FileNotFoundError(
            f"認証 JSON が見つかりません: {creds_path} "
            f"(env var GOOGLE_CREDS_PATH で override 可)"
        )

    creds = Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    import gspread as _gs
    return _gs.authorize(creds)


# variation 用 metadata 専用 列 (= HIGH/LOW schema の未使用 index に格納)
# row[34] = SKU, row[35] = Size, row[36] = Color (= row[33] AH の外側、35 列拡張)
COL_VAR_SKU = 34
COL_VAR_SIZE = 35
COL_VAR_COLOR = 36
ROW_TOTAL_COLS = 37  # AH(33) + SKU/Size/Color の 拡張


def _normalize_official_row(row: list) -> list:
    """公式 SKU詳細 row → HIGH/LOW schema 互換 row に変換 (1 row 1 SKU、variation 対応).

    HIGH/LOW: B=ItemID(1), C=Title(2), D=Sold(3), F=F¥(5), N=N¥(13), R=Cat(17), AH=AH¥(33)
    公式:     D=ListingID(3), E=Title(4), F=SKU(5), G=Size(6), H=Color(7),
              J=Cost(9), P=Category(15)
    """
    listing_id = (row[COL_OFFICIAL_LISTING_ID] if len(row) > COL_OFFICIAL_LISTING_ID else "").strip()
    cost_j = (row[COL_OFFICIAL_COST] if len(row) > COL_OFFICIAL_COST else "").strip()
    title = (row[COL_OFFICIAL_TITLE] if len(row) > COL_OFFICIAL_TITLE else "").strip()
    category = (row[COL_OFFICIAL_CATEGORY] if len(row) > COL_OFFICIAL_CATEGORY else "").strip()
    sku = (row[COL_OFFICIAL_SKU] if len(row) > COL_OFFICIAL_SKU else "").strip()
    size = (row[COL_OFFICIAL_SIZE] if len(row) > COL_OFFICIAL_SIZE else "").strip()
    color = (row[COL_OFFICIAL_COLOR] if len(row) > COL_OFFICIAL_COLOR else "").strip()
    stock = (row[COL_OFFICIAL_STOCK] if len(row) > COL_OFFICIAL_STOCK else "").strip()
    prev_cost = str(row[COL_OFFICIAL_PREV_COST]).strip() if len(row) > COL_OFFICIAL_PREV_COST else ""
    # 2026-05-24: P 列空欄なら title からカテゴリ推定 (= スプシ P 列 未入力でも V8 計算可能に)
    if not category and title:
        category = _infer_official_category_from_title(title)
    out = [""] * ROW_TOTAL_COLS
    out[COL_ITEM_ID] = listing_id
    out[COL_TITLE] = title
    out[COL_N_PRICE] = cost_j
    out[COL_CATEGORY] = category
    out[COL_VAR_SKU] = sku
    out[COL_VAR_SIZE] = size
    out[COL_VAR_COLOR] = color
    # I 列 仕入元在庫 ✕ = 在庫なし → sold_flag に流して既存 skip logic で除外
    if stock == "✕":
        out[COL_SOLD_FLAG] = "○"
    # Q 列 前期仕入元価格 → AH 相当 (= 仕入変動検出に使用)
    if prev_cost and prev_cost != "0":
        out[COL_AH_PRICE] = prev_cost
    return out


def _infer_official_category_from_title(title: str) -> str:
    """公式 sheet の title からカテゴリ推定 (P 列空欄時の fail-soft fallback).

    UNIQLO/GU drop-shipping の listing 大半が UT graphic T-Shirt 想定。
    title に明示的な keyword あれば それを優先、 無ければ Tシャツ(UT) default。
    """
    t = title.lower()
    if "t-shirt" in t or "tシャツ" in t:
        return "Tシャツ(UT)"
    if "スウェット" in t or "sweatshirt" in t or "sweat shirt" in t:
        return "スウェット"
    if "パーカー" in t or "hoodie" in t:
        return "パーカー"
    if "パンツ" in t or "pants" in t:
        return "パンツ"
    # 公式 sheet (UNIQLO/GU drop-shipping) の default は UT Tシャツ
    return "Tシャツ(UT)"


def load_sheet_rows(sheet_key: str = "HIGH"):
    """指定 sheet の全行を取得 (schema-aware).

    Returns: (header, rows: list[list[str]] HIGH/LOW 互換 format, worksheet, schema)
    """
    if sheet_key not in SHEETS:
        raise ValueError(f"Unknown sheet_key: {sheet_key}")
    cfg = SHEETS[sheet_key]
    gc = _gspread_client()
    sh = gc.open_by_key(cfg["id"])
    ws = sh.worksheet(cfg["tab"])

    if cfg["schema"] == "high_low":
        # AL列(値下FLG, index37)まで読む (2026-06-30 NO_CONVERT 値下げ対応)。
        # ※ index34-36 は KEY/KEY2/巡回ERR で variation 列(COL_VAR_SKU=34)と衝突するが、
        #   detect_candidates は variation 列を official schema 限定で読むため high_low では無害。
        all_rows = ws.get_values(f"A1:AL{ws.row_count}")
        if not all_rows:
            return [], [], ws, cfg["schema"]
        return all_rows[0], all_rows[HEADER_ROWS:], ws, cfg["schema"]

    if cfg["schema"] == "official":
        # 公式: SKU詳細 を P 列まで読込 (= D=ItemID/E=Title/F=SKU/G=Size/H=Color/J=Cost/P=Category)
        # 2026-05-24 variation 対応: SKU 単位で行展開 (= 旧 listing 単位集約は廃止)
        all_rows = ws.get_values(f"A1:P{ws.row_count}")
        if not all_rows:
            return [], [], ws, cfg["schema"]
        header = all_rows[0]
        normalized = []
        # SKU 単位で展開 (= variation listing は ItemID + SKU でユニーク)
        seen = set()
        for row in all_rows[HEADER_ROWS:]:
            listing_id = (row[COL_OFFICIAL_LISTING_ID] if len(row) > COL_OFFICIAL_LISTING_ID else "").strip()
            sku = (row[COL_OFFICIAL_SKU] if len(row) > COL_OFFICIAL_SKU else "").strip()
            if not listing_id:
                continue
            # 重複 key: (ItemID, SKU) で判定 (= 同 SKU 2 行は最初の値採用)
            key = (listing_id, sku)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(_normalize_official_row(row))
        return header, normalized, ws, cfg["schema"]

    raise ValueError(f"Unknown schema: {cfg['schema']}")


def _to_float(s) -> Optional[float]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(",", "").replace("¥", "").replace("$", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _is_sold(cell_value: str) -> bool:
    """D 列の値が "売切" を意味するかどうか."""
    return (cell_value or "").strip() in SOLD_VALUES


def _is_valid_jpy(v: Optional[float]) -> bool:
    """¥が有効値か (range check)."""
    return v is not None and MIN_JPY <= v <= MAX_JPY


_LEGACY_PRICEDOWN_RE = re.compile(r"^値下(\d+(?:\.\d+)?)pp$")


def parse_pricedown_pp(flag) -> Optional[float]:
    """AL列(値下FLG) を値下げ幅% に解釈 (2026-07-01 数値化).

    正の数値なら float (= cut_pct)、空/非数値/0以下は None (= 非対象)。
    例: "5"→5.0 / "8"→8.0 / ""→None。
    後方互換: 旧文字列 "値下5pp" → 5.0 (noconvert の数値化 sync が未走の移行期を安全に跨ぐ)。
    """
    s = str(flag or "").strip()
    if not s:
        return None
    m = _LEGACY_PRICEDOWN_RE.match(s)
    if m:
        s = m.group(1)
    try:
        pp = float(s)
    except ValueError:
        return None
    return pp if pp > 0 else None


# ============================================================================
# should_revise (新 logic 2026-05-22: 現状 vs V8 理想 直接比較)
# ============================================================================
from . import normalize as _normalize  # noqa: E402


def should_revise(
    item_id: str,
    sold_flag: str,
    n_jpy: Optional[float],
    ah_jpy: Optional[float],
    current_usd: Optional[float],
    current_policy: Optional[str],
    v7_usd: Optional[float],
    v7_policy: Optional[str],
    in_snapshot: bool = True,
    available_qty: Optional[int] = None,
    abnormal_delta_threshold: float = 200.0,
) -> tuple[bool, str, dict]:
    """新 logic 起動判定 (純関数, 2026-05-22 / 公式 sheet + 在庫 check 対応).

    Returns: (revise_yes, reason, extras)
      reason 一覧:
        - "no_item_id" / "sold" / "no_cost"            : スプシ条件 NG (= eBay listing 実在性なし)
        - "abnormal_delta"                              : AH↔N delta > threshold (= scrape miss)
        - "not_in_snapshot"                             : snapshot に ItemID なし (= 取下げ済 listing 想定)
        - "out_of_stock"                                : Available quantity < 1 (= eBay 在庫切れ表示)
        - "no_snapshot"                                 : snapshot にはあるが price/policy 取得失敗
        - "policy_change"                               : 現Policy ≠ V8Policy → revise
        - "price_diff"                                  : 現USD ≠ V8USD → revise
        - "aligned"                                     : 完全一致 → skip
      extras: {"delta_pct": ..., "is_abnormal": bool, "details": str}

    URL filter は廃止 (= 公式 sheet には URL 列がない、ItemID が真の eBay listing 実在性基準)
    """
    extras: dict = {"delta_pct": None, "is_abnormal": False, "details": ""}

    # スプシ filter (= eBay listing 実在性基準)
    if not (item_id or "").strip():
        return False, "no_item_id", extras
    if _normalize.is_sold(sold_flag):
        return False, "sold", extras
    if not _is_valid_jpy(n_jpy):
        return False, "no_cost", extras

    # 異常検出 (= AH↔N delta > threshold)
    abnormal = False
    if ah_jpy is not None and ah_jpy > 0:
        delta_pct = (n_jpy - ah_jpy) / ah_jpy * 100
        extras["delta_pct"] = delta_pct
        abnormal = delta_pct > abnormal_delta_threshold

    if abnormal:
        # RESTOCK 整合 reconciliation (2026-06-25):
        # AH↔N が急騰でも、eBay 実価格が N 計算値 (= v7_usd/v7_policy) と一致するなら
        # RESTOCK 時に監視くん側で既に値上げ反映済 = 整合 = aligned (alert 不要)。
        # 一致しない場合のみ scrape 誤り疑いとして従来通り abnormal alert (fail-closed)。
        base = f"AH=¥{ah_jpy:,.0f} → N=¥{n_jpy:,.0f} (+{delta_pct:.0f}%)"
        reconciled = (
            in_snapshot
            and current_usd is not None and current_policy is not None
            and (available_qty is None or available_qty >= 1)
            and _normalize.normalize_usd(current_usd) == _normalize.normalize_usd(v7_usd)
            and _normalize.normalize_policy_name(current_policy)
            == _normalize.normalize_policy_name(v7_policy)
        )
        if reconciled:
            extras["is_abnormal"] = False
            extras["details"] = base + " | eBay価格=N計算値で整合 (RESTOCK反映済)"
            return False, "aligned", extras
        extras["is_abnormal"] = True
        extras["details"] = base
        return False, "abnormal_delta", extras

    # snapshot 在籍 check (= 取下げ済 listing 想定)
    if not in_snapshot:
        extras["details"] = "snapshot に ItemID 不在 (= 取下げ済 listing 想定)"
        return False, "not_in_snapshot", extras

    # eBay Available quantity check (= 在庫=0 listing は revise しても意味なし)
    if available_qty is not None and available_qty < 1:
        extras["details"] = f"Available quantity={available_qty}"
        return False, "out_of_stock", extras

    # 現状 (eBay) 取得失敗 → 比較不能で skip
    if current_usd is None or current_policy is None:
        extras["details"] = (
            f"current_usd={current_usd} current_policy={current_policy!r}"
        )
        return False, "no_snapshot", extras

    # normalize して比較
    n_cur_usd = _normalize.normalize_usd(current_usd)
    n_v7_usd = _normalize.normalize_usd(v7_usd)
    n_cur_policy = _normalize.normalize_policy_name(current_policy)
    n_v7_policy = _normalize.normalize_policy_name(v7_policy)

    if n_cur_policy != n_v7_policy:
        extras["details"] = f"policy {n_cur_policy!r} → {n_v7_policy!r}"
        return True, "policy_change", extras
    if n_cur_usd != n_v7_usd:
        extras["details"] = f"USD ${n_cur_usd} → ${n_v7_usd}"
        return True, "price_diff", extras

    return False, "aligned", extras


# ============================================================================
# detect_candidates / detect_init_targets
# ============================================================================
def detect_candidates(rows, threshold_pct: float = DEFAULT_THRESHOLD_PCT,
                       mode: str = "normal", source_sheet: str = "HIGH",
                       abnormal_delta_threshold: Optional[float] = None,
                       schema: str = "high_low") -> list:
    """各行を ReviseCandidate に変換 (= スプシ filter pass のみ).

    新 logic (2026-05-22): 起動判定はここでは行わない。eligible 行を返すだけ。
    後段の run_price_revise で V8 計算 + snapshot/cache 取得 + should_revise で最終判定。

    filter (= eBay listing 実在性基準、URL filter 廃止 2026-05-22):
      - len(row) <= N 列        → skip (短い行)
      - ItemID 空欄              → skip (= eBay 上 listing 不在)
      - D 列 SOLD マーカー        → skip
      - N 列 invalid             → skip

    mode は 後段 run_price_revise の上限制御だけに使う (= "normal" は max_revises 適用、
    "all" は上限なし)。新 logic では起動 logic 自体は mode 不依存。

    Returns: list[ReviseCandidate] (= filter pass 行のみ、未評価)
    """
    if abnormal_delta_threshold is None:
        abnormal_delta_threshold = ABNORMAL_DELTA_PCT_THRESHOLD
    candidates = []
    for i, row in enumerate(rows):
        row_index = i + HEADER_ROWS + 1
        if len(row) <= COL_N_PRICE:
            continue
        item_id = (row[COL_ITEM_ID] or "").strip() if len(row) > COL_ITEM_ID else ""
        if not item_id:
            continue
        url = (row[COL_URL] or "").strip() if len(row) > COL_URL else ""
        sold_flag = row[COL_SOLD_FLAG] if len(row) > COL_SOLD_FLAG else ""
        f_jpy = _to_float(row[COL_F_PRICE]) if len(row) > COL_F_PRICE else None
        n_jpy = _to_float(row[COL_N_PRICE]) if len(row) > COL_N_PRICE else None
        ah_jpy = _to_float(row[COL_AH_PRICE]) if len(row) > COL_AH_PRICE else None
        category = (row[COL_CATEGORY] or "").strip() if len(row) > COL_CATEGORY else ""
        title = (row[COL_TITLE] or "").strip() if len(row) > COL_TITLE else ""
        # variation 関連 (2026-05-24): index34-36 は official synthetic row のみ SKU/Size/Color。
        # high_low 実シートでは 34-36 = KEY/KEY2/巡回ERR なので読まない (= 空のまま、変動は snapshot 由来)。
        if schema == "official":
            sku = (row[COL_VAR_SKU] or "").strip() if len(row) > COL_VAR_SKU else ""
            var_size = (row[COL_VAR_SIZE] or "").strip() if len(row) > COL_VAR_SIZE else ""
            var_color = (row[COL_VAR_COLOR] or "").strip() if len(row) > COL_VAR_COLOR else ""
        else:
            sku = var_size = var_color = ""
        # NO_CONVERT 値下FLG (AL列、high_low のみ。official synthetic row は 37 幅で index37 不在 → 空)
        pricedown_flag = (row[COL_PRICEDOWN_FLG] or "").strip() if len(row) > COL_PRICEDOWN_FLG else ""

        # スプシ filter (= スプシ条件 NG はここで弾く、URL filter 廃止)
        if _normalize.is_sold(sold_flag):
            continue
        if not _is_valid_jpy(n_jpy):
            continue

        # 異常検出 (= AH↔N delta > threshold で is_abnormal タグ)
        delta_pct = 0.0
        is_abnormal = False
        if ah_jpy is not None and ah_jpy > 0:
            delta_pct = (n_jpy - ah_jpy) / ah_jpy * 100
            if delta_pct > abnormal_delta_threshold:
                is_abnormal = True

        candidates.append(ReviseCandidate(
            row_index=row_index,
            item_id=item_id,
            category=category,
            new_jpy=n_jpy,
            ah_jpy=ah_jpy,
            f_jpy=f_jpy,
            delta_pct=delta_pct,
            basis="pending",
            title=title,
            source_sheet=source_sheet,
            url=url,
            sold_flag=sold_flag,
            is_abnormal=is_abnormal,
            # skip_reason は付けない (2026-06-25): 異常 delta も V8/snapshot まで流し、
            # should_revise の RESTOCK 整合照合で aligned / abnormal_delta に振り分ける。
            skip_reason=None,
            sku=sku,
            variation_size=var_size,
            variation_color=var_color,
            # variation listing 判定: SKU OR Size OR Color のいずれか持つ
            # 2026-05-24 fix: 監視くんが SKU UUID 取り損ねても Size/Color あれば
            #                 RelationshipDetails (= Size=XS|Color=BLACK) で variation 特定可能
            #                 eBay FileExchange は SKU 列を変動特定に使わない (公式 doc)
            is_variation=bool(sku) or bool(var_size) or bool(var_color),
            pricedown_flag=pricedown_flag,
        ))
    return candidates


def detect_init_targets(rows) -> list:
    """F+AH 両空欄 + N 値あり + ItemID あり + D ≠ ○ の行を init 対象に.

    初回 cycle で baseline がない行を、N で F 初期化する。
    """
    targets = []
    for i, row in enumerate(rows):
        row_index = i + HEADER_ROWS + 1
        if len(row) <= COL_N_PRICE:
            continue
        item_id = (row[COL_ITEM_ID] or "").strip() if len(row) > COL_ITEM_ID else ""
        if not item_id:
            continue
        sold_flag = row[COL_SOLD_FLAG] if len(row) > COL_SOLD_FLAG else ""
        if _is_sold(sold_flag):
            continue
        f_jpy = _to_float(row[COL_F_PRICE]) if len(row) > COL_F_PRICE else None
        n_jpy = _to_float(row[COL_N_PRICE]) if len(row) > COL_N_PRICE else None
        ah_jpy = _to_float(row[COL_AH_PRICE]) if len(row) > COL_AH_PRICE else None
        # F 無効 + AH 無効 + N 有効 = init
        if (not _is_valid_jpy(f_jpy)) and (not _is_valid_jpy(ah_jpy)) and _is_valid_jpy(n_jpy):
            targets.append(InitTarget(
                row_index=row_index,
                item_id=item_id,
                new_jpy=n_jpy,
            ))
    return targets


# ============================================================================
# compute_new_usd (コストプラス簡易版)
# ============================================================================
# ============================================================================
# V8 pricing_engine 本元 import (= SSOT、worktree 越境だが read-only)
# ============================================================================
_IMAK_EBAY_API_PATH = r"C:/dev/iMak/iMakeBayAPI"


def _import_v8_pricing():
    """本元 iMakeBayAPI/pricing_engine.compute_listing_price_v6 を import.

    compute_listing_price (dispatcher) ではなく v6 を直接使う。
    理由: dispatcher は title 引数を取らないため title_overrides
    (バッグ→Porter / グッズ→サンリオぬいぐるみ等) が効かない。
    """
    if _IMAK_EBAY_API_PATH not in sys.path:
        sys.path.insert(0, _IMAK_EBAY_API_PATH)
    from pricing_engine import compute_listing_price_v6  # type: ignore  # noqa: PLC0415
    return compute_listing_price_v6


def _import_pricedown_override():
    """本元 pricing_engine.apply_pricedown_override を import (= NO_CONVERT 値下げ SSOT).

    cost+category+title から V8標準を絶対計算し 5pp 値下げ (gate で赤字防止・冪等)。
    title を渡すことで標準パス (compute_listing_price_v6) と同じ title_override が効く。
    """
    if _IMAK_EBAY_API_PATH not in sys.path:
        sys.path.insert(0, _IMAK_EBAY_API_PATH)
    from pricing_engine import apply_pricedown_override  # type: ignore  # noqa: PLC0415
    return apply_pricedown_override


# ============================================================================
# カテゴリ正規化 (= HIGHT/LOW R列 略称 → V8 yaml 正式名)
# 参照: iMakHQ/tools/v6_generate_revise_xlsx_v2.py CATEGORY_NORMALIZE
# (Revise 側に複製、修正連鎖回避のため import せずローカル定義)
# ============================================================================
CATEGORY_NORMALIZE = {
    "TCG":                "TCG(PSA10)",
    "G-shock":            "G-SHOCK",
    "G-SHOCK":            "G-SHOCK",
    "Tシャツ":             "Tシャツ(UT)",
    "Tシャツ(UT)":         "Tシャツ(UT)",
    "ユニクロ":            "ユニクロ(非UT)",
    "ユニクロ(非UT)":      "ユニクロ(非UT)",
    "Montbell":           "Montbell(軽)",
    "Montbell(軽)":        "Montbell(軽)",
    "Montbell(重)":        "Montbell(重)",
    "アウトドア・ジャケット": "Montbell(重)",
    "一番くじ":            "一番くじ",
    "フィギュア":           "フィギュア",
    "サンリオ文具":         "サンリオ文具",
    "ヴィンテージ玩具":      "ヴィンテージ玩具",
    "ヴィンテージ":         "ヴィンテージ玩具",
    "トミカ":              "トミカ",
    "tomica":             "トミカ",
    "POPMart":            "POPMart",
    "ガシャポン":           "ガシャポン",
    "カプセルトイ":         "ガシャポン",
    "ダイソー":            "ダイソー",
    "バッグ":              "バッグ(アネロ)",  # title PORTER → V8 title_overrides で Porter に
    "バッグ(アネロ)":       "バッグ(アネロ)",
    "アネロ":              "バッグ(アネロ)",
    "サンリオぬいぐるみ":    "サンリオぬいぐるみ",
    "Porter":             "Porter",
    "リール":              "リール",
    # 2026-05-23 追加 (= HQ 側 yaml 連動済、v8_calc_failed 87 件解消)
    "グッズ":              "サンリオぬいぐるみ",  # サンリオキーホルダー想定
    "文具":                "サンリオ文具",         # 三菱ジェット 等
    "スニーカー":           "スニーカー",          # yaml 新規 category 追加済
    "ゴルフ":               "ゴルフ",              # yaml 新規 category 追加済
}


def normalize_category(category_label: str) -> str:
    """R列 略称 → V8 yaml 正式名. 未マッピングは原値 (V8 側で default A group fallback)."""
    cat = (category_label or "").strip()
    if not cat:
        return ""
    if cat in CATEGORY_NORMALIZE:
        return CATEGORY_NORMALIZE[cat]
    # 部分一致 fallback
    for short, full in CATEGORY_NORMALIZE.items():
        if short in cat or cat in short:
            return full
    return cat


def compute_new_usd(candidate: ReviseCandidate, v8_fn, pricedown_fn=None) -> ReviseCandidate:
    """V8 pricing_engine 経由で価格計算.

    成功時: candidate.new_usd / shipping_usd / shipping_profile_name 等を埋める
    失敗時: candidate.skip_reason 設定

    pack 反映: effective_cost = N × pack_count を V8 に渡す (= 2026-05-22 pack 対応)。
    pack_count は candidate に事前 set されている前提 (= run_price_revise で設定)。

    NO_CONVERT 値下げ (2026-06-30): pricedown_fn 指定 + AL列flag="値下5pp" + D≠○ の行は、
    標準 V8 算出後に apply_pricedown_override(cost, category, title) の price+shipping_profile_name
    でセット差し替え (= 5pp 値下げ)。title を渡すので title_override は標準パスと整合。
    赤字行 (gate 未達含む) は override 側 applied=False で標準価格が返るため安全。
    """
    norm_category = normalize_category(candidate.category)
    # effective_cost = N × pack_count (= mapping 未登録なら pack_count=1 で同値)
    candidate.effective_cost = candidate.new_jpy * (candidate.pack_count or 1)
    try:
        result = v8_fn(
            cost_jpy=candidate.effective_cost,
            median_usd=0,  # NO_MEDIAN モード
            category=norm_category,
            country="US",
            title=candidate.title,
        )
    except ValueError as e:
        candidate.skip_reason = f"V8 計算失敗: {e}"
        return candidate
    except Exception as e:
        candidate.skip_reason = f"V8 例外 {type(e).__name__}: {e}"
        return candidate

    # V8 結果から必要項目を取り出し
    candidate.new_usd = result.get("price")
    candidate.shipping_usd = result.get("shipping_usd")
    candidate.shipping_profile_name = result.get("shipping_profile_name")
    candidate.buyer_total_usd = result.get("buyer_total_usd")
    candidate.profit_jpy = result.get("profit_jpy")

    # 赤字検出 (= 5/15 事故再発防止)
    if candidate.profit_jpy is not None and candidate.profit_jpy < 0:
        candidate.skip_reason = f"赤字 利益¥{candidate.profit_jpy:.0f}"
        candidate.new_usd = None  # skip 扱い
        return candidate

    # NO_CONVERT 値下げ override (HIGH/LOW のみ、AL列=正の数値pp の行)
    cut_pp = parse_pricedown_pp(candidate.pricedown_flag)
    if (pricedown_fn is not None
            and cut_pp is not None
            and not _normalize.is_sold(candidate.sold_flag)):
        try:
            od = pricedown_fn(
                cost_jpy=candidate.effective_cost,
                category=norm_category,
                title=candidate.title,
                cut_pct=cut_pp,  # AL列の数値pp (5→5% / 8→8%)
            )
            # price と shipping_profile_name は必ずセットで採用 (バンド跨ぎ不整合防止)
            candidate.new_usd = od["price"]
            candidate.shipping_profile_name = od["shipping_profile_name"]
            candidate.pricedown_applied = bool(od.get("applied"))
        except Exception as e:
            # override 失敗時は標準価格を据置 (fail-safe: 値下げしないだけ、誤価格は出さない)
            # 例: 手動 AL≥gate(10) → 関数が ValueError (赤字防止の不変条件) → 標準据置。
            print(f"  [WARN pricedown override 失敗→標準据置] item={candidate.item_id} AL={candidate.pricedown_flag!r}: {e}")

    return candidate


# ============================================================================
# CSV 生成
# ============================================================================
def write_revise_csv(revisable: list, output_dir: Path = CSV_OUTPUT_DIR,
                       filename_prefix: str = "revise_combined") -> Path:
    """eBay FileExchange Revise CSV を生成 (= single listing 用, 6 列).

    列順: Action / ItemID / ShippingProfileName / StartPrice /
          BestOfferAutoAcceptPrice (空) / MinimumBestOfferPrice (空)
    variation candidate は除外 (= write_revise_variation_csv で別出力)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{filename_prefix}_{ts}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(REVISE_CSV_HEADER)
        for c in revisable:
            if getattr(c, "is_variation", False):
                continue  # variation は別 CSV
            writer.writerow([
                "Revise",
                c.item_id,
                c.shipping_profile_name or "",
                f"{c.new_usd:.2f}",
                "",  # BestOfferAutoAcceptPrice = 空 (= 自動承認閾値リセット)
                "",  # MinimumBestOfferPrice = 空 (= 自動却下閾値リセット)
            ])
    return path


# variation revise CSV ヘッダ群 (= 2026-05-24 第 4 版、eBay 公式 FileExchange 形式)
#
# 教訓:
#   v1 (5 列、ShippingProfileName 混在) → 全行 21916618 警告で price ignore
#   v2 (4 列、SKU + *StartPrice)        → 全行 21916618 警告で price ignore
#       理由: 監視くん *Quantity + SKU shortcut は Quantity 限定、 StartPrice は SKU 認識せず
#   v3 (5 列、Variation row のみ)        → Item row 欠落で公式仕様違反
#   v4 (= 現在、公式 doc 準拠):
#     - Item row 1 行目: ItemID + RelationshipDetails (= 全 trait + 全 value 列挙)
#     - Variation row N 行: Relationship=Variation + RelationshipDetails (= 単一 value) + *StartPrice
#
# format example (eBay 公式 PDF "File Exchange Advanced Template Instructions" pp.27):
#   Action, ItemID, Relationship, RelationshipDetails, *StartPrice
#   Revise, 358589341204, , Sizes=US XS(JP S);US S(JP M)|Colors=Pink;Blue,
#   ,      ,             Variation, Sizes=US XS(JP S)|Colors=Pink,                                49.98
#   ,      ,             Variation, Sizes=US S(JP M)|Colors=Blue,                                 49.98

REVISE_VARIATION_PRICE_CSV_HEADER = [
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "ItemID",
    "Relationship",
    "RelationshipDetails",
    "*StartPrice",
]

# Item レベル ShippingProfile update 用 (= 3 列、SKU なしで Item 全体、 動作実績あり)
REVISE_VARIATION_SHIPPING_CSV_HEADER = [
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "ItemID",
    "ShippingProfileName",
]


def _build_item_row_details(all_variations: list) -> str:
    """Item row 用 RelationshipDetails: 全 trait + 全 value を列挙.

    例: variation 2 個で Sizes=[XS, S], Colors=[Pink, Blue]
        → "Sizes=XS;S|Colors=Pink;Blue"

    Args:
        all_variations: [{"specifics": {trait: value}}, ...] (= snapshot variations.json[item_id])
    """
    trait_values: dict = {}  # {trait: [value1, value2]} (insertion order 保持で dict)
    for v in all_variations:
        for trait, value in (v.get("specifics") or {}).items():
            if trait not in trait_values:
                trait_values[trait] = []
            if value not in trait_values[trait]:
                trait_values[trait].append(value)
    if not trait_values:
        return ""
    return "|".join(f"{trait}={';'.join(values)}" for trait, values in trait_values.items())


def _build_variation_row_details(specifics: dict) -> str:
    """Variation row 用 RelationshipDetails: 単一 variation の trait=value 列挙.

    例: {"Sizes": "US XS(JP S)", "Colors": "Pink"} → "Sizes=US XS(JP S)|Colors=Pink"
    """
    if not specifics:
        return ""
    return "|".join(f"{trait}={value}" for trait, value in specifics.items())


def write_revise_variation_csv(revisable: list, output_dir: Path = CSV_OUTPUT_DIR,
                                 filename_prefix: str = "revise_variation",
                                 variations_map: Optional[dict] = None) -> dict:
    """variation listing 用 Revise CSV を 2 ファイル生成 (= 5/24 第 4 版、eBay 公式 doc 準拠).

    1. `{prefix}_price_{ts}.csv`    (5 列: Action / ItemID / Relationship / RelationshipDetails / *StartPrice)
       - ItemID 単位で grouping: Item row 1 行 (全 trait+value 列挙) + Variation rows N 行 (単一 value + StartPrice)
    2. `{prefix}_shipping_{ts}.csv` (3 列: Item レベル ShippingProfileName、 ItemID あたり 1 行)

    Format reference: eBay 公式 PDF "File Exchange Advanced Template Instructions" pp.27
                      "Modifying the Quantity and StartPrice of a variation"

    Args:
        variations_map: {item_id: [{sku, specifics, ...}, ...]} (snapshot.variations.json)
                        Item row 構築に必要 (= 全 variation の trait/value 集合)。

    Returns: {"price_path": Path or None, "shipping_path": Path or None}
    """
    var_candidates = [c for c in revisable if getattr(c, "is_variation", False)]
    if not var_candidates:
        return {"price_path": None, "shipping_path": None}
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    variations_map = variations_map or {}

    # candidate を ItemID で grouping (insertion order 保持)
    grouped: dict = {}
    for c in var_candidates:
        grouped.setdefault(c.item_id, []).append(c)

    # --- 1. variation 別 価格 CSV (公式形式: Item row + Variation rows) ---
    price_path = output_dir / f"{filename_prefix}_price_{ts}.csv"
    with price_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(REVISE_VARIATION_PRICE_CSV_HEADER)
        for item_id, cands in grouped.items():
            all_vars = variations_map.get(item_id, [])
            # Item row: ItemID + 全 variation 列挙
            item_details = _build_item_row_details(all_vars)
            writer.writerow(["Revise", item_id, "", item_details, ""])
            # Variation rows: ItemID/Action 空、 Relationship=Variation
            # 公式 GU/UNIQLO の特性: 全 variation で cost 共通 → new_usd も共通
            # スプシ SKU 列が空欄でも Size/Color あれば is_variation=True、
            # かつ全 candidate の new_usd が一致するなら snapshot 全 variation に展開可
            skus_empty = all(not c.sku for c in cands)
            same_price = len({round(c.new_usd or 0, 2) for c in cands}) == 1
            if skus_empty and same_price and all_vars and cands[0].new_usd is not None:
                # snapshot 全 variation を同 new_usd で emit (= 公式 全 size 同価格 case)
                new_usd = cands[0].new_usd
                for v in all_vars:
                    var_details = _build_variation_row_details(v.get("specifics") or {})
                    writer.writerow(["", "", "Variation", var_details, f"{new_usd:.2f}"])
            else:
                # 通常: SKU lookup → fallback Size/Color
                # 混在 case (= SKU populated + SKU empty 共存) では SKU 空欄行は orphan
                # 扱いで skip。 emit すると Item row と trait/value 不一致で eBay 全体 Failure
                # (= 21916664 "Variation Specifics provided does not match")
                has_any_sku = any(c.sku for c in cands)
                for c in cands:
                    match = next((v for v in all_vars if v.get("sku") == c.sku), None)
                    if match and match.get("specifics"):
                        var_details = _build_variation_row_details(match["specifics"])
                    elif not c.sku and has_any_sku:
                        # orphan: 混在 case の SKU 空欄行を skip (= 監視くん中途半端な巡回の残骸)
                        continue
                    else:
                        # fallback: candidate の variation_size/color (= スプシ G/H)
                        fb = {}
                        if c.variation_size:
                            fb["Sizes"] = c.variation_size
                        if c.variation_color:
                            fb["Colors"] = c.variation_color
                        var_details = _build_variation_row_details(fb)
                    writer.writerow(["", "", "Variation", var_details, f"{c.new_usd:.2f}"])

    # --- 2. Item レベル Shipping CSV (3 列、ItemID あたり 1 行) ---
    shipping_path = output_dir / f"{filename_prefix}_shipping_{ts}.csv"
    seen_item_policy: dict = {}
    for c in var_candidates:
        if c.item_id not in seen_item_policy and c.shipping_profile_name:
            seen_item_policy[c.item_id] = c.shipping_profile_name
    with shipping_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(REVISE_VARIATION_SHIPPING_CSV_HEADER)
        for item_id, policy in seen_item_policy.items():
            writer.writerow(["Revise", item_id, policy])

    return {"price_path": price_path, "shipping_path": shipping_path}


def write_diff_csv(revisable: list, mode: str, output_dir: Path = CSV_OUTPUT_DIR,
                    filename_prefix: str = "revise_combined_diff",
                    abnormal: Optional[list] = None) -> Path:
    """ビフォーアフター 比較 CSV (multi-sheet 統合、V8 対応 + 異常検出列).

    列: sheet / ItemID / タイトル / カテゴリ / 旧仕入¥ (F) / 前期 (AH) / 現仕入¥ (N) /
        差分% / basis / 新USD / 送料USD / Policy名 / Buyer total USD / 利益¥ / mode / 異常検出
    abnormal: ABNORMAL_DELTA で skip した candidate も含める (= user 目視チェック用)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{filename_prefix}_{ts}.csv"
    abnormal = abnormal or []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow([
            "sheet", "ItemID", "タイトル", "カテゴリ",
            "旧仕入¥(F)", "前期¥(AH)", "現仕入¥(N)",
            "仕入差分%", "判定軸",
            "新USD", "送料USD", "Policy名", "Buyer total USD", "利益¥",
            "mode", "異常検出",
        ])
        all_rows = list(revisable) + list(abnormal)
        for c in all_rows:
            anomaly_flag = ""
            if c.is_abnormal:
                anomaly_flag = f"⚠️ ABNORMAL_DELTA (+{c.delta_pct:.0f}%)"
            writer.writerow([
                c.source_sheet,
                c.item_id,
                (c.title or "")[:80],
                c.category,
                f"{c.f_jpy:.0f}" if c.f_jpy else "",
                f"{c.ah_jpy:.0f}" if c.ah_jpy else "",
                f"{c.new_jpy:.0f}",
                f"{c.delta_pct:+.2f}",
                c.basis,
                f"{c.new_usd:.2f}" if c.new_usd else "(skip)",
                f"{c.shipping_usd:.2f}" if c.shipping_usd is not None else "",
                c.shipping_profile_name or "",
                f"{c.buyer_total_usd:.2f}" if c.buyer_total_usd is not None else "",
                f"{c.profit_jpy:.0f}" if c.profit_jpy is not None else "",
                mode,
                anomaly_flag,
            ])
    return path


def write_abnormal_alert_log(abnormal: list, output_dir: Path = CSV_OUTPUT_DIR) -> Optional[Path]:
    """異常 delta 検出 alert log 出力.

    Returns: log path (= 異常 0 件なら None)
    """
    if not abnormal:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"alert_abnormal_delta_{ts}.log"
    with path.open("w", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 異常 delta 検出 ({len(abnormal)} 件)\n")
        f.write("=" * 60 + "\n")
        for c in abnormal:
            f.write(f"\nItemID: {c.item_id} | sheet: {c.source_sheet} | category: {c.category}\n")
            f.write(f"  AH: ¥{(c.ah_jpy or 0):,.0f} → N: ¥{c.new_jpy:,.0f} (+{c.delta_pct:.0f}%)\n")
            f.write(f"  判定: ABNORMAL_DELTA で skip (eBay 実価格 ≠ N 計算値 = scrape 誤り疑い)\n")
            f.write(f"  推奨: スプシ N 列 (row{c.row_index}) を手動確認、監視くん scrape ロジック検証\n")
    return path


# ============================================================================
# スプシ書込は監視くん責務、リバイスくんは読むだけ (2026-05-12 設計修正)
# ============================================================================
# ============================================================================
# 統合 entry point
# ============================================================================
SHARED_SNAPSHOT_DIR = Path(r"C:/dev/iMak_data/snapshots")
SNAPSHOT_KEEP_COUNT = 5
SNAPSHOT_DL_RETRIES = 3                       # 2026-06-12 R1: DL 失敗時 retry 回数
SNAPSHOT_DL_RETRY_INTERVAL_SEC = 2.0           # retry 間隔
SNAPSHOT_FRESHNESS_MAX_AGE_SEC = 6 * 3600      # mtime ガード = 6h (R1 二重防御)


class SnapshotFetchError(RuntimeError):
    """snapshot DL 失敗 / 鮮度切れで run 中止すべきことを示す例外 (R1 fresh-or-fail)."""


def _flush_dns_cache(verbose: bool = True) -> None:
    """Windows DNS cache を flush (= DNS hiccup の自動復旧試行)."""
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True, text=True, timeout=10,
            encoding="cp932", errors="replace",
        )
        if verbose:
            print(f"[snapshot]   DNS cache flush 完了 (= 自動復旧試行)")
    except Exception as e:
        if verbose:
            print(f"[snapshot]   [WARN] DNS cache flush 失敗: {e} (= 続行)")


def fetch_and_save_snapshot(output_dir: Path = SHARED_SNAPSHOT_DIR,
                              keep_count: int = SNAPSHOT_KEEP_COUNT,
                              verbose: bool = True,
                              max_retries: int = SNAPSHOT_DL_RETRIES,
                              fetch_fn=None) -> Path:
    """Trading API で snapshot 自動取得 → 共有フォルダ保存 → rotation (R1 fresh-or-fail).

    DL 失敗時の動作:
      1. 1 回目失敗 → flushdns + retry (= DNS hiccup 自動復旧)
      2. retry 尽きても失敗 → SnapshotFetchError 投げて run 中止 (= 古い snapshot で続行しない)

    Returns: 保存した snapshot path (= 必ず fresh)
    Raises : SnapshotFetchError (= DL 不可、 run 中止すべき)

    Args:
        fetch_fn: test 用 injection (= 通常は ebay_trading_api.fetch_all_active_listings)
    """
    from . import ebay_trading_api
    if fetch_fn is None:
        fetch_fn = ebay_trading_api.fetch_all_active_listings

    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            if verbose:
                if attempt == 1:
                    print(f"[snapshot] eBay GetSellerList で active listing 取得 中...")
                else:
                    print(f"[snapshot]   retry {attempt}/{max_retries} ...")
            items = fetch_fn(verbose=verbose)
            if verbose:
                print(f"[snapshot]   取得完了: {len(items)} listings")
            path = ebay_trading_api.save_snapshot_csv(items, output_dir)
            if verbose:
                print(f"[snapshot]   保存: {path}")
            deleted = ebay_trading_api.rotate_snapshots(output_dir, keep_count=keep_count)
            if verbose and deleted:
                print(f"[snapshot]   rotation: 削除 {len(deleted)} 件 (keep={keep_count})")
            return path
        except Exception as e:
            last_err = e
            if verbose:
                print(f"[snapshot]   [WARN] 取得失敗 (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                _flush_dns_cache(verbose=verbose)
                time.sleep(SNAPSHOT_DL_RETRY_INTERVAL_SEC)

    # 全 retry 尽きた → fail-CLOSED で run 中止 (= 古い snapshot で続行しない)
    raise SnapshotFetchError(
        f"snapshot DL 失敗 ({max_retries} 回 retry 尽き、 最後 err: {last_err}). "
        f"DNS/ネットワーク確認のうえ再実行してください。"
    )


def _check_snapshot_freshness(path: Path, max_age_sec: int = SNAPSHOT_FRESHNESS_MAX_AGE_SEC,
                                verbose: bool = True) -> None:
    """snapshot mtime が max_age_sec 超なら SnapshotFetchError (= 二重防御).

    fetch_and_save_snapshot 経由は時刻保証されるが、 既存 snapshot 採用経路でも
    stale を使わないようにする最終チェック。
    """
    if not path.exists():
        raise SnapshotFetchError(f"snapshot not found: {path}")
    age_sec = time.time() - path.stat().st_mtime
    if age_sec > max_age_sec:
        age_h = age_sec / 3600
        raise SnapshotFetchError(
            f"snapshot stale: {path.name} は {age_h:.1f}h 前 "
            f"(許容 {max_age_sec/3600:.0f}h 以内). DNS/ネットワーク確認のうえ再実行してください。"
        )
    if verbose:
        age_min = age_sec / 60
        print(f"[snapshot]   鮮度 OK ({age_min:.0f} 分前 < 許容 {max_age_sec/3600:.0f}h)")


def run_price_revise(
    threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    max_revises: Optional[int] = None,
    max_init: Optional[int] = None,
    dry_run: bool = False,
    skip_sheet_update: bool = False,
    mode: str = "normal",
    sheet_keys: Optional[list] = None,
    review_xlsx: bool = False,
    skip_snapshot: bool = False,
    snapshot_from: Optional[str] = None,
) -> ReviseRunResult:
    """Phase 1 価格 revise の本体フロー (multi-sheet 対応).

    mode:
      "normal" (default): 仕入変動 cycle (rate >= 3% 起動)
      "all": 全件見直し (D=○ 除く全行を re-price)
    sheet_keys: ["HIGH", "LOW", "公式"] のサブセット。None なら全 sheet。
                重複 ItemID は最初に処理した sheet を優先 (HIGH > LOW > 公式 の listing order)。
    """
    if sheet_keys is None:
        sheet_keys = list(ALL_SHEET_KEYS)
    # 不正キー除外
    sheet_keys = [k for k in sheet_keys if k in SHEETS]
    if not sheet_keys:
        raise ValueError("sheet_keys が空 (= 1 つも check されてない)")

    result = ReviseRunResult()
    all_candidates: list = []
    seen_item_ids: set = set()

    # === Step 0: snapshot 自動取得 (= 2026-05-22 追加、stale 事故防止) ===
    if not skip_snapshot and snapshot_from is None:
        fetch_and_save_snapshot()

    # === Step 1: 全 sheet 読込 + filter pass (= eligible 抽出) ===
    for sheet_key in sheet_keys:
        cfg = SHEETS[sheet_key]
        print(f"[revise] === sheet={sheet_key} ({cfg['label']}) ===")
        print(f"[revise] mode={mode} 読込: id={cfg['id']} tab={cfg['tab']}")
        _, rows, _ws, schema = load_sheet_rows(sheet_key)
        print(f"[revise] 全行数: {len(rows)} (header 除く, schema={schema})")

        sheet_candidates = detect_candidates(
            rows, threshold_pct=threshold_pct, mode=mode, source_sheet=sheet_key,
            schema=schema,
        )
        before = len(sheet_candidates)
        sheet_candidates = [c for c in sheet_candidates if c.item_id not in seen_item_ids]
        dup_skipped = before - len(sheet_candidates)
        if dup_skipped:
            print(f"[revise]   重複 ItemID 除去: {dup_skipped} 件 (先発 sheet 優先)")
        for c in sheet_candidates:
            seen_item_ids.add(c.item_id)

        print(f"[revise]   {sheet_key} eligible: {len(sheet_candidates)} 件 (filter pass)")
        all_candidates.extend(sheet_candidates)

    result.candidates = all_candidates
    print(f"[revise] === 全 sheet 統合 eligible: {len(all_candidates)} 件 ===")

    # === Step 2: 異常 delta も V8/snapshot まで流す (pre-filter 廃止 2026-06-25) ===
    # 旧: is_abnormal を計算前に一律 skip+alert していた → RESTOCK で正規値上げ済の行も
    #     毎 cycle 誤 alert。新: should_revise で eBay 実価格 vs N 計算値を照合し、
    #     整合 (RESTOCK 反映済) なら aligned、不一致なら abnormal_delta に振り分ける。
    normal_candidates = all_candidates

    # === Step 3: pack mapping 読込 + 全 eligible で V8 計算 ===
    from . import pack_items as _pack_mod
    pack_map = _pack_mod.load_pack_items()
    pack_registered_count = 0
    pack_suspect_count = 0
    if normal_candidates:
        print(f"[revise] V8 計算 {len(normal_candidates)} 件 (pack mapping {len(pack_map)} 件 読込)...")
        v8_fn = _import_v8_pricing()
        pricedown_fn = _import_pricedown_override()
        v8_failed = 0
        pricedown_applied_count = 0
        for c in normal_candidates:
            # pack 反映
            c.pack_count = _pack_mod.get_pack_count(c.item_id, pack_map)
            if c.pack_count > 1:
                pack_registered_count += 1
            else:
                # 未登録だが title から pack 疑い
                if _pack_mod.detect_pack_suspicion(c.title):
                    c.pack_suspect = True
                    pack_suspect_count += 1
                    print(f"  [WARN pack 疑い 未登録] item={c.item_id} title={(c.title or '')[:60]}")
            compute_new_usd(c, v8_fn, pricedown_fn=pricedown_fn)
            if c.skip_reason and "V8" in c.skip_reason:
                v8_failed += 1
            if c.pricedown_applied:
                pricedown_applied_count += 1
        if v8_failed:
            print(f"[revise]   V8 計算失敗: {v8_failed} 件 (= Unknown category 等)")
        pricedown_flagged = sum(
            1 for c in normal_candidates if parse_pricedown_pp(c.pricedown_flag) is not None
        )
        if pricedown_flagged:
            print(f"[revise]   NO_CONVERT 値下げ: flag {pricedown_flagged} 件 中 "
                  f"{pricedown_applied_count} 件に値下げ適用 (残は gate 据置)")
        if pack_registered_count:
            print(f"[revise]   pack mapping 適用: {pack_registered_count} 件")
        if pack_suspect_count:
            print(f"[revise]   [WARN] pack 疑い (未登録): {pack_suspect_count} 件 (= user 確認推奨)")

    # === Step 4: 現状取得 (= snapshot CSV + variation JSON + Trading API cache) ===
    snapshot_map: dict = {}
    policy_map: dict = {}
    variations_map: dict = {}  # 2026-05-24 variation listing 対応
    item_ids = [c.item_id for c in normal_candidates if not c.skip_reason]
    if item_ids:
        from . import snapshot_reader, ebay_trading_api
        if snapshot_from:
            snapshot_path = Path(snapshot_from)
            print(f"[revise] snapshot 強制指定: {snapshot_path}")
        else:
            snapshot_path = snapshot_reader.find_latest_snapshot()
        if snapshot_path and snapshot_path.exists():
            # R1 二重防御: mtime > 6h なら stale で中止 (skip_snapshot/snapshot_from 経由も同じ)
            _check_snapshot_freshness(snapshot_path)
            print(f"[revise] snapshot 読込: {snapshot_path.name}")
            snapshot_map = snapshot_reader.load_snapshot(snapshot_path)
            variations_map = snapshot_reader.load_variations(snapshot_path)
            print(f"[revise]   snapshot {len(snapshot_map)} listings 取得 "
                  f"(うち variation listing {len(variations_map)} 件)")
        else:
            raise SnapshotFetchError(
                f"snapshot CSV 未検出: {snapshot_path}. "
                f"DL 取得失敗 or skip_snapshot 指定で stale 想定。 run 中止。"
            )
        try:
            policy_map = ebay_trading_api.get_items_cached(item_ids)
        except Exception as e:
            print(f"[revise] [WARN] Trading API cache 取得失敗 → 全件 no_snapshot: {e}")

    # === Step 5: 各 candidate を新 logic で判定 ===
    reason_counts: dict = {}
    for c in normal_candidates:
        if c.skip_reason:  # V8 計算失敗 or 赤字
            reason_label = "v8_calc_failed" if "V8" in c.skip_reason else "loss"
            c.decision_reason = reason_label
            c.decision_details = c.skip_reason
            reason_counts[reason_label] = reason_counts.get(reason_label, 0) + 1
            result.skipped.append(c)
            continue

        # fail-closed: snapshot で variation listing と判明 + スプシ SKU 空欄 → skip
        # 旧 bug: スプシ SKU 空欄で is_variation=False → single CSV に Item-level *StartPrice
        #        を書き → eBay 側で 21916618 silent ignore (= 価格未反映)
        # 対策: snapshot variations_map に存在する listing は SKU 必須、空欄なら skip
        if not c.is_variation and c.item_id in variations_map:
            c.decision_reason = "variation_no_sku_in_spreadsheet"
            c.decision_details = (
                f"snapshot で variation listing と判明 ({len(variations_map[c.item_id])} variation) "
                f"だがスプシ SKU 空欄 (= 監視くん巡回不足)"
            )
            reason_counts["variation_no_sku_in_spreadsheet"] = (
                reason_counts.get("variation_no_sku_in_spreadsheet", 0) + 1
            )
            result.skipped.append(c)
            continue

        # snapshot + policy 取得
        snap = snapshot_map.get(c.item_id)
        pol_entry = policy_map.get(c.item_id) or {}
        c.current_policy = pol_entry.get("shipping_profile_name")  # ItemID レベル

        # variation candidate (2026-05-24): SKU 別 current_usd / qty
        if c.is_variation:
            vars_list = variations_map.get(c.item_id, [])
            match = next((v for v in vars_list if v.get("sku") == c.sku), None)
            if match:
                c.current_usd = match.get("start_price")
                c.available_qty = match.get("quantity")
            elif vars_list and not c.sku:
                # 公式 case: SKU UUID 空欄だが snapshot に variation あり
                # 全 variation 同価格前提なので 1 つ目を current_usd として採用
                # qty は全 variation の合計
                c.current_usd = vars_list[0].get("start_price")
                c.available_qty = sum(v.get("quantity") or 0 for v in vars_list)
            else:
                # variation 情報が snapshot にない → not_in_snapshot 扱い
                c.current_usd = None
                c.available_qty = None
        else:
            c.current_usd = snap["price_usd"] if snap else pol_entry.get("current_price_usd")
            c.available_qty = snap["available_qty"] if snap else None

        revise_yes, reason, extras = should_revise(
            item_id=c.item_id,
            sold_flag=c.sold_flag,
            n_jpy=c.new_jpy,
            ah_jpy=c.ah_jpy,
            current_usd=c.current_usd,
            current_policy=c.current_policy,
            v7_usd=c.new_usd,
            v7_policy=c.shipping_profile_name,
            in_snapshot=(snap is not None),
            available_qty=c.available_qty,
            abnormal_delta_threshold=ABNORMAL_DELTA_PCT_THRESHOLD,
        )
        c.decision_reason = reason
        c.decision_details = extras.get("details", "")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if revise_yes:
            c.basis = "decision"
            # revise内容 判定 (= xlsx 表示用)
            n_cur_usd = _normalize.normalize_usd(c.current_usd)
            n_v7_usd = _normalize.normalize_usd(c.new_usd)
            n_cur_pol = _normalize.normalize_policy_name(c.current_policy)
            n_v7_pol = _normalize.normalize_policy_name(c.shipping_profile_name)
            usd_diff = (n_cur_usd != n_v7_usd)
            pol_diff = (n_cur_pol != n_v7_pol)
            if usd_diff and pol_diff:
                c.revise_content = "USD+Policy"
            elif pol_diff:
                c.revise_content = "Policy のみ"
            elif usd_diff:
                c.revise_content = "USD のみ"
            result.revisable.append(c)
        else:
            c.basis = "skip"
            # RESTOCK 整合照合の結果を反映 (2026-06-25)
            c.is_abnormal = extras.get("is_abnormal", False)
            if reason == "abnormal_delta":
                c.skip_reason = "ABNORMAL_DELTA"
                result.abnormal.append(c)
            result.skipped.append(c)

    # === Step 6: 大量検出 警告 (= 上限 cap なし、新 logic 設計) ===
    # 残し = 乖離放置 = 赤字リスク のため全件処理が原則
    # max_revises は緊急時 emergency override のみ (= 通常 None=unlimited)
    if max_revises is not None and len(result.revisable) > max_revises:
        result.cap_exceeded = True
        print(f"[revise] [emergency cap] {max_revises} 件で打切 (= 通常運用では cap なし)")
        def _diff(c):
            if c.current_usd and c.new_usd:
                return abs(c.new_usd - c.current_usd)
            return 0
        result.revisable = sorted(result.revisable, key=_diff, reverse=True)[:max_revises]
    elif len(result.revisable) >= 200:
        # 通知のみ (= cap せず) : 大量検出時は user 目視確認推奨
        print(f"[revise] [NOTICE] {len(result.revisable)} 件 大量 revise 検出 — xlsx で目視確認推奨")

    print(f"[revise] === 結果 ===")
    print(f"[revise] revisable: {len(result.revisable)} / skip: {len(result.skipped)}")
    if result.abnormal:
        reason_counts["abnormal_delta"] = len(result.abnormal)
    for reason in ["aligned", "policy_change", "price_diff",
                   "not_in_snapshot", "out_of_stock", "no_snapshot",
                   "abnormal_delta", "variation_no_sku_in_spreadsheet",
                   "v8_calc_failed", "loss"]:
        n = reason_counts.get(reason, 0)
        if n:
            print(f"[revise]   - {reason}: {n}")

    # サンプル log 出力 (revise + abnormal 上位 数件)
    for c in result.revisable[:5]:
        print(
            f"  [revise] [{c.source_sheet}] item={c.item_id} cat={c.category} "
            f"{c.decision_reason}: {c.decision_details} "
            f"new=${c.new_usd:.2f} policy={c.shipping_profile_name}"
        )
    for c in result.abnormal[:3]:
        print(
            f"  [⚠️ abnormal] [{c.source_sheet}] item={c.item_id} cat={c.category} "
            f"{c.decision_details}"
        )

    if result.revisable:
        # single listing 用 CSV (= 6 列、Best Offer 関連あり)
        csv_path = write_revise_csv(result.revisable)
        result.csv_path = str(csv_path)
        single_n = sum(1 for c in result.revisable if not c.is_variation)
        print(f"[revise] eBay UP CSV (single, {single_n} 件): {csv_path}")
        # variation 用 CSV (= 2 分離、5/24 改修で silent ignore 回避)
        var_paths = write_revise_variation_csv(result.revisable, variations_map=variations_map)
        if var_paths.get("price_path"):
            var_n = sum(1 for c in result.revisable if c.is_variation)
            result.var_price_path = str(var_paths["price_path"])
            result.var_shipping_path = str(var_paths["shipping_path"])
            print(f"[revise] eBay UP CSV (variation price, {var_n} 行): {var_paths['price_path']}")
            print(f"[revise] eBay UP CSV (variation shipping, ItemID 単位): {var_paths['shipping_path']}")

    # diff CSV は revisable + 異常 を統合 (= user 目視で異常 review 可)
    if result.revisable or result.abnormal:
        diff_path = write_diff_csv(result.revisable, mode=mode, abnormal=result.abnormal)
        print(f"[revise] ビフォーアフター CSV (統合): {diff_path}")

    # 異常 delta alert log
    if result.abnormal:
        alert_path = write_abnormal_alert_log(result.abnormal)
        result.alert_log_path = str(alert_path) if alert_path else None
        if alert_path:
            print(f"[revise] ⚠️ 異常 delta alert log: {alert_path}")

    # レビュー用 xlsx (= 旧/新 比較、user 目視承認用、summary sheet 付き)
    if review_xlsx and (result.revisable or result.abnormal or result.skipped):
        try:
            from . import review_xlsx as review_mod
            xlsx_path = review_mod.write_review_xlsx(
                revisable=result.revisable,
                output_dir=CSV_OUTPUT_DIR,
                snapshot_map=snapshot_map,
                old_policy_map=policy_map,
                abnormal=result.abnormal,
                all_skipped=result.skipped,
            )
            result.review_xlsx_path = str(xlsx_path)
            print(f"[review] レビュー xlsx: {xlsx_path}")
        except Exception as e:
            print(f"[review] [WARN] xlsx 生成失敗 (CSV のみ生成済): {e}")

    return result


# ============================================================================
# CLI
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="価格 revise (新 logic 2026-05-22)")
    parser.add_argument("--max", type=int, default=None,
                        help="emergency cap (default なし=全件 revise)。"
                             "新 logic では「現状≠V8理想」全件処理が原則 (= 残し=赤字リスク)。")
    parser.add_argument("--dry-run", action="store_true",
                        help="CSV 生成のみ、スプシ更新スキップ")
    parser.add_argument("--sheets", type=str, default=None,
                        help="処理対象 sheet (カンマ区切り、未指定なら全 sheet)。"
                             f"選択肢: {','.join(ALL_SHEET_KEYS)}")
    parser.add_argument("--review-xlsx", action="store_true",
                        help="レビュー用 xlsx (= 旧/新 比較) を生成")
    parser.add_argument("--skip-snapshot", action="store_true",
                        help="snapshot 自動取得を skip (= 既存 snapshot 利用、test/debug 用)")
    parser.add_argument("--snapshot-from", type=str, default=None,
                        help="特定 snapshot file 強制使用 (debug 用)")
    args = parser.parse_args()

    sheet_keys = None
    if args.sheets:
        sheet_keys = [s.strip() for s in args.sheets.split(",") if s.strip()]

    result = run_price_revise(
        max_revises=args.max,
        dry_run=args.dry_run,
        sheet_keys=sheet_keys,
        review_xlsx=args.review_xlsx,
        skip_snapshot=args.skip_snapshot,
        snapshot_from=args.snapshot_from,
    )
    if result.cap_exceeded:
        print(f"[emergency cap] 候補 {len(result.candidates)} 件 / 処理 {len(result.revisable)} 件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
