#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSV監査くん — 出来上がった出品CSVを後から監査し、4軸(タイトル/Item Specifics/
価格/送料ポリシー)の適正をチェックして処理する独立プログラム (2026-06-08 新設)。

設計原則 (ユーザー合意・厳守): 「修正」は3分岐。値の捏造禁止 (SSOT/参照のみ)。
  - 機械的・決定論的 (送料ポリシー)        → CSV自動修正 (価格から再計算=一意)
  - データ誤り (catalogと不一致/空)        → 行を除外(fail-closed) + カタログ修正依頼
  - 生成プログラムのバグ (title/カテゴリ等) → 行を除外 + プログラム修正依頼(報告のみ)
  - SEO改善余地                            → 報告のみ (CSVは触らない)

既存資産を再利用 (ゼロから作らない):
  - 各カテゴリ check_csv.validate_row(row,i)->[(severity,msg)] (SSOT検査ロジック)
  - csv_postprocess/excluder.exclude_rows_from_csv (行物理除外+backup)
  - listing_common.get_shipping_policy_name (送料正解値)
  - auto_catalog_add_request のパターン (依頼書 .md)

使い方:
  python csv_auditor.py                  # 最新CSVを自動検出して監査+修正
  python csv_auditor.py --csv path.csv   # CSV指定
  python csv_auditor.py --dry-run        # 検査のみ(CSV/依頼書を書かない)
  python csv_auditor.py --with-market    # 市場ゲート+TOPセラーSEO比較も(API)
  python csv_auditor.py --log run.log    # 生成ログも参照(補助証拠)
"""
import argparse
import collections
import csv as _csv
import datetime
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import audit_ledger  # PDCA 台帳 (蓄積/前回比/再発検知)  # noqa: E402
WORKSPACE = os.path.normpath(os.path.join(_HERE, "..", ".."))  # c:/dev/iMak
CSV_DIR = os.path.join(WORKSPACE, "iMakHQ", "csv_output")
REVIEW_DIR = os.path.join(WORKSPACE, "iMakHQ", "review_logs")
CATALOG_REQ_DIR = r"C:\dev\iMak_data\catalog\requests"
MISSING_MODELS_PATH = r"C:/dev/iMak_data/catalog/missing_models.csv"  # psa_to_csv 検出の catalog未登録
CATALOG_DB = r"C:/dev/iMak_data/catalog/products.sqlite"              # 解決済 prune の照合先
# identity 未解決で Catalog へ送らなかった分の残件リスト (毎監査 上書き = 常に全件再掲)
UNRESOLVED_IDENTITY_PATH = os.path.join(REVIEW_DIR, "pdca_identity_unresolved.md")

# project → check_csv.py / listing_commonカテゴリ / *Category値 / 固有列 / 送料自動修正可否
CATEGORY_MAP = {
    "tcg": {
        "check_csv": os.path.join(WORKSPACE, "iMakTCG", "check_csv.py"),
        "lc_category": "TCG(PSA10)", "ebay_categories": ["183454"],
        "sig_cols": ["C:Game", "C:Card Name", "C:Rarity"], "fix_shipping": True,
        "cost_key": "CDA:Certification Number - (ID: 27503)",
        "aspect_json": r"C:/dev/iMak_data/catalog/_input/ebay_tcg_filter_lists_api.json",
        # 必須spec空でも除外しない=報告のみ (2026-06-15)。実機確認 cat 183454: 必須aspectは
        # Game のみ (aspect_required=True)、Rarity/Card Name/Character は RECOMMENDED(False)。
        # 旧は Rarity 等空で fail-closed 除外→ catalog に rarity 無い正規カード(例 Gundam RP-022)が
        # 出品できず recall 損。G-shock/Mercari と同型の非必須欄での誤除外なので同じ扱いにする。
        # (Game 空は sig_cols 経由で別途検出。誤情報でなく欠落=空のまま出品が正・大前提に合致)
        "spec_empty_excludes": False,
    },
    "gshock": {
        "check_csv": os.path.join(WORKSPACE, "iMakG-shock", "check_csv.py"),
        "lc_category": "G-SHOCK", "ebay_categories": ["31387"],
        "sig_cols": ["C:Model", "C:Movement"], "fix_shipping": True, "cost_key": "*Title",
        "aspect_json": r"C:/dev/iMak_data/catalog/_input/ebay_gshock_filter_lists_api.json",
        # 必須spec空でも除外しない=報告のみ (2026-06-13)。check_csv が Movement/Color 空を
        # 必須扱いして全8行を誤除外→入稿0件になった。実機確認: cat 31387 で Movement は
        # aspect_required=false(RECOMMENDED)、"Color" は aspect 自体が無い(Case/Band Color が正)。
        # = eBay必須でない欄での fail-closed 全滅。apparel(mercari) と同型なので同じ扱いにする。
        "spec_empty_excludes": False,
    },
    "ichibankuji": {
        "check_csv": os.path.join(WORKSPACE, "iMak_ichibankuji", "check_csv.py"),
        "lc_category": "一番くじ", "ebay_categories": ["261055"],
        "sig_cols": ["C:Franchise", "C:Character"], "fix_shipping": True, "cost_key": "*Title",
        "aspect_json": r"C:/dev/iMak_data/catalog/_input/ebay_ichibankuji_filter_lists_api.json",
    },
    # Mercari系 apparel (uniqlo/montbell/porter)。check_csv は apparel共通(category受理=下記4つ)。
    # ⚠️ shipping は check_csv 内で "Tシャツ(UT)" ハードコード → porter/montbell に誤適用しうるので
    #    送料自動修正は無効(fix_shipping=False, 報告のみ)。title/spec/cert/除外は有効。
    "mercari": {
        "check_csv": os.path.join(WORKSPACE, "iMakMercari", "check_csv.py"),
        "lc_category": "Tシャツ(UT)",
        "ebay_categories": ["57988", "52357", "11450", "15687"],
        "sig_cols": ["C:Department"], "fix_shipping": False, "cost_key": "*Title",
        # apparel必須spec(Size/Department)がporter等に合わず全滅するので、spec空は除外せず報告のみ。
        "spec_empty_excludes": False,
    },
}
# importlib ロード時に sys.path へ足す共有 dir
_SHARED_PATHS = [os.path.join(WORKSPACE, "iMakeBayAPI")]

# project → 属する catalog category 集合 (recurring_missing の project-scoped filter 用・2026-07-25)。
# missing_models.csv / pdca improvement_queue はプロジェクト横断のグローバル台帳のため、gshock 監査に
# TCG由来(dragonball_scg 等)の recurring が混入していた(2026-07-25 ITAJAGA 誤検出)。監査対象プロジェクトの
# category に属さない recurring を digest から除外する。※未知(下表に無い)category は「残す」= 誤って隠さない。
# ★2026-08-01: **project名そのもの** も自分の category として持たせる。
#   pdca improvement_queue には subcategory (pokemon_tcg 等) だけでなく **project名のまま**
#   (`category='tcg'`) 積まれた行が実在する (実測: pending 16件)。owner_map に "tcg" key が
#   無いと `owner=None` → fail-safe で残る → **gshock/ichibankuji/mercari の digest に全部混入**。
#   seen_count>=2 に達した分から順に表面化するので、放置すると毎日 digest が汚れ続ける。
PROJECT_CATALOG_CATEGORIES = {
    "tcg": {"tcg", "one_piece_tcg", "pokemon_tcg", "dragonball_scg", "gundam_tcg"},
    "gshock": {"gshock"},
    "ichibankuji": {"ichibankuji"},
    "mercari": {"mercari", "uniqlo", "montbell", "porter", "gu"},
}


def _category_owner_map():
    """{catalog_category: 所有project} を PROJECT_CATALOG_CATEGORIES から構築(純関数)。"""
    out = {}
    for proj, cats in PROJECT_CATALOG_CATEGORIES.items():
        for c in cats:
            out[c] = proj
    return out


def filter_recurring_for_project(recurring, project, owner_map=None):
    """recurring から「別プロジェクト所属と分かる category」を除外(純関数・test可)。

    owner_map(={category:project})に category が有り かつ project 不一致 → 除外(他プロジェクト案件)。
    owner_map に無い(未知)category / project 一致 → **残す**(未知を silent に隠さない=fail-safe)。
    2026-07-25: gshock 監査に dragonball_scg(TCG) の recurring が混入する構造を根絶。
    """
    if owner_map is None:
        owner_map = _category_owner_map()
    out = []
    for r in recurring:
        cat = (r.get("category") or "").strip()
        owner = owner_map.get(cat)
        if owner is None or owner == project:
            out.append(r)
    return out


# ============================================================================
# disposition (純関数 = テスト対象の中核)
# ============================================================================
# 行への処置種別
MECH_FIX = "MECH_FIX"             # 機械的に CSV 修正 (送料ポリシー)
EXCLUDE_CATALOG = "EXCLUDE_CATALOG"   # 除外 + カタログ修正依頼 (set誤マップ等のデータ誤り)
EXCLUDE_FAILCLOSED = "EXCLUDE_FAILCLOSED"  # 除外のみ (cert不正/価格非数値)
SPEC_EMPTY = "SPEC_EMPTY"         # 必須spec空 → 除外 + (要切り分け)依頼
REPORT_PROGRAM = "REPORT_PROGRAM"  # 除外 + プログラム修正依頼 (誤出品直結の生成バグ)
SEO_NOTE = "SEO_NOTE"             # 報告のみ (行は残す)
INFO_ONLY = "INFO_ONLY"

# 行を除外すべき disposition (誤出品を出さない=最安全)
_EXCLUDING = {EXCLUDE_CATALOG, EXCLUDE_FAILCLOSED, SPEC_EMPTY, REPORT_PROGRAM}
# 行集約の優先度 (重い順)
_PRIORITY = {
    EXCLUDE_CATALOG: 5, SPEC_EMPTY: 4, REPORT_PROGRAM: 4,
    EXCLUDE_FAILCLOSED: 4, MECH_FIX: 2, SEO_NOTE: 1, INFO_ONLY: 0,
}


def classify_finding(severity, msg):
    """validate_row が出す (severity, msg) を disposition に分類する純関数。
    msg の決定論的な接頭辞/含有語で判定。check_csv の文言に依存するので
    test_csv_auditor が全パターンを固定 (文言変更の回帰検知)。
    """
    m = msg or ""
    # --- データ誤り (catalog) ---
    if "不整合" in m or "誤マップ" in m:
        return EXCLUDE_CATALOG
    if m.startswith("必須Item Specific") and "空" in m:
        return SPEC_EMPTY
    # --- fail-closed 除外のみ ---
    if m.startswith("PSA鑑定番号が不正") or m.startswith("価格が数値でない"):
        return EXCLUDE_FAILCLOSED
    # --- 機械的修正 ---
    if m.startswith("送料ポリシー") and "不一致" in m:
        return MECH_FIX
    # --- 生成プログラムのバグ (誤出品直結 → 除外+報告) ---
    if "禁止ワード" in m:
        return REPORT_PROGRAM
    if "上限" in m and "タイトル" in m:        # タイトルN字 > 上限80字
        return REPORT_PROGRAM
    if "'PSA 10' で始まって" in m:
        return REPORT_PROGRAM
    if m.startswith("カテゴリが") or m.startswith("ConditionID"):
        return REPORT_PROGRAM
    if "日本語" in m:                          # csv_auditor native check
        return REPORT_PROGRAM
    # --- SEO/情報 (行は残す) ---
    if "推奨" in m or "< 推奨" in m or "重複" in m or "TOPセラー" in m:
        return SEO_NOTE
    if severity == "INFO":
        return INFO_ONLY
    # 既定: 未知の WARN/ERROR は安全側 (報告+除外) に倒す
    return REPORT_PROGRAM if severity == "ERROR" else SEO_NOTE


def row_disposition(dispositions):
    """1行の複数 disposition を優先度で集約 → 代表処置を返す。"""
    if not dispositions:
        return INFO_ONLY
    return max(dispositions, key=lambda d: _PRIORITY.get(d, 0))


def should_exclude(dispositions):
    return any(d in _EXCLUDING for d in dispositions)


# ============================================================================
# カテゴリ判定 / check_csv 動的ロード
# ============================================================================
def detect_category(headers, rows):
    """CSVヘッダ + *Category 値から project を判定。
    check_csv を持つ既知カテゴリ → project名。持たない(reel/tomica等) → 'generic'
    (汎用の最低限監査=タイトル安全のみ)。空CSV等 → None。"""
    if not headers:
        return None
    hset = set(headers)
    cat_val = ""
    if rows and "*Category" in headers:
        idx = headers.index("*Category")
        cat_val = str(rows[0][idx]).strip() if idx < len(rows[0]) else ""
    # *Category 値が有ればそれを権威にする (一致=そのカテゴリ / 不一致=generic)。
    # C:Model 等は reel/watch で被るので sig_cols フォールバックは *Category 空の時のみ。
    if cat_val:
        for proj, meta in CATEGORY_MAP.items():
            if cat_val in meta["ebay_categories"]:
                return proj
        return "generic"   # 既知カテゴリ外 (reel 261030 等) → 汎用監査
    # *Category 無し → 固有列シグネチャで推定
    for proj, meta in CATEGORY_MAP.items():
        if any(c in hset for c in meta["sig_cols"]):
            return proj
    return "generic"


def load_check_csv_module(project):
    """project の check_csv.py を別名モジュールとして importlib ロード。
    同名 'check_csv' の衝突回避 + 相対 import 解決のため sys.path を整える。
    """
    path = CATEGORY_MAP[project]["check_csv"]
    proj_dir = os.path.dirname(path)
    for p in [proj_dir] + _SHARED_PATHS:
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(f"check_csv_{project}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_latest_csv():
    cands = glob.glob(os.path.join(CSV_DIR, "*.csv"))
    return max(cands, key=os.path.getmtime) if cands else None


# 出品で実際に使う列名
COL_TITLE = "*Title"
COL_PRICE = "*StartPrice"
COL_SHIP = "ShippingProfileName"
_JP_RE = re.compile(r"[ぁ-んァ-ヶ一-龠]")


_MAX_TITLE = 80
IDEAL_TITLE_LEN = 70   # これ未満は「80字を活かしきれてない」= 短タイトル (PDCA KPI)


def native_findings(headers, row):
    """check_csv に無い csv_auditor 独自検査 (日本語混入)。check_csv 経路で validate_row に上乗せ。"""
    out = []
    hm = {h: i for i, h in enumerate(headers)}
    ti = hm.get(COL_TITLE)
    title = str(row[ti]).strip() if ti is not None and ti < len(row) else ""
    if _JP_RE.search(title):
        out.append(("ERROR", f"タイトルに日本語文字が混入: {title!r}"))
    return out


# タイトル↔Item Specifics 整合 (生成ロジック準拠の検証):
# 生成ロジックは catalog の事実から「タイトル」と「Item Specifics」の両方を作る。
# = 両者は同じ事実を語るはず。食い違い = 生成のミス (これを見逃すと誤出品)。
# 各カテゴリで「この spec の値はタイトルに反映されてるべき」列を (列, 照合mode) で定義。
#   "whole"      : 値全体(区切りで分割した各part)がタイトルに含まれること
#                  例 gshock C:Model='G-SHOCK G-LIDE' は全体一致を要求 → シリーズ名混入を検出
#   "first_token": 値の先頭語がタイトルに含まれること
#                  例 tcg C:Character='Togekiss V Legendary Heartbeat'(セット名混入で汚染) でも
#                     先頭語 'Togekiss' がタイトルに在れば一致扱い → フィールド汚染で誤検出しない
CONSISTENCY_COLS = {
    "tcg": [("C:Character", "first_token")],
    # C:Model は意図的に eBay の「シリーズ」フィルタ正規値 (例 'G-SHOCK 5600' / 'G-SHOCK G-LIDE')。
    # タイトルの実型番 (GW-M5610 等) と異なって当然 → 整合チェック対象から除外 (誤検出防止、2026-06-08)。
    "gshock": [("C:Display", "whole"), ("C:Band Color", "whole")],
    "ichibankuji": [("C:Character", "first_token")],
    "mercari": [("C:Color", "whole")],
}


def title_spec_consistency(headers, row, project):
    """タイトルが Item Specifics の重要ファクトを反映してるか検証。
    spec に値が在るのにタイトルに反映されてない → 生成ロジック逸脱の疑い (報告)。"""
    cols = CONSISTENCY_COLS.get(project)
    if not cols:
        return []
    hm = {h: i for i, h in enumerate(headers)}
    ti = hm.get(COL_TITLE)
    title = (str(row[ti]).strip() if ti is not None and ti < len(row) else "").lower()
    if not title:
        return []
    # リールはタイトルが型番中心で色を入れない慣習 → C:Color 整合は対象外 (誤検出防止)。
    _bi = hm.get("C:Brand")
    _brand = (str(row[_bi]).strip().lower() if _bi is not None and _bi < len(row) else "")
    _is_reel = any(b in _brand for b in _REEL_BRANDS)
    # DON!! カード(One Piece)は「キャラ」を持たない特殊カード。C:Character にフォールバックで
    # 'DON!! Card' が入り、タイトルは番号(#DON-PRB01-027)で表現するため first_token 'DON!!' が
    # タイトルに無く誤検出する → C:Character 整合は対象外 (2026-07-01、C:Type-on-bags と同型)。
    _cn_i = hm.get("C:Card Number")
    _cardnum = (str(row[_cn_i]).strip().lower() if _cn_i is not None and _cn_i < len(row) else "")
    _is_don = _cardnum.startswith("don-")
    out = []
    for col, mode in cols:
        if col == "C:Color" and _is_reel:
            continue
        if col == "C:Character" and _is_don:
            continue
        i = hm.get(col)
        if i is None or i >= len(row):
            continue
        val = str(row[i]).strip()
        if not val:
            continue
        if mode == "first_token":
            # 区切りは空白 + ピリオド。ドット略記名 (例 'Portgas.D.Ace') を
            # 1トークン扱いすると title の 'Portgas D Ace'(空白) に不一致→誤検出するため、
            # '.' でも分割して先頭の実トークンを取る (2026-07-07、Portgas.D.Ace 誤検出恒久対策)。
            _parts = [t for t in re.split(r"[\s.]+", val) if t]
            tok = _parts[0] if _parts else val
            hit = tok.lower() in title
        else:  # whole: 複数値 "A, B / C" は各 part で判定。1つでも在れば一致。
            parts = [p.strip() for p in re.split(r"[,/&]", val) if p.strip()]
            hit = any(p.lower() in title for p in parts)
        if not hit:
            out.append(f"タイトル↔spec不一致: {col}='{val}' がタイトルに反映されてない(生成ロジック逸脱疑い)")
    return out


# タイトル形式準拠 (生成ロジックから抽出した各カテゴリ/商品のタイトルの「形」):
# 生成ロジックは決まった型でタイトルを作る。型から外れる = 生成のミス (報告)。
#   prefix: 先頭一致必須 / contains: 全て含む必須 / contains_any: いずれか1つ必須 /
#   brand_exact: C:Brand が eBay公式ブランド名と一致必須 (フィルタ不ヒット防止)。
TITLE_FORMAT = {
    # TCG の PSA 10 先頭は validate_row が既に検査 → ここは番号 # のみ
    "tcg": {"contains": ["#"]},
    "gshock": {"prefix": "CASIO G-Shock", "contains": ["Watch"]},
    "ichibankuji": {"prefix": "Ichiban Kuji"},
}
# eBay 公式ブランド名 (フィルタ主戦場)。リールは brand 多数 → ブランド種別判定にも使う
_REEL_BRANDS = {"shimano", "daiwa", "abu garcia", "megabass", "lews", "abel", "penn", "okuma"}
# mercari は商品混在 (porter/tomica/uniqlo/montbell/workman/reel) → C:Brand で sub-detect
MERCARI_TITLE_FORMAT = [
    # (C:Brand に含まれる語, ルール)
    (("porter",), {"contains": ["PORTER"], "contains_any": ["Used", "Pre-owned", "Preowned"],
                   "brand_exact": {"Porter", "HEAD PORTER"}}),
    (("tomica",), {"contains_any": ["Tomica", "TOMICA"], "brand_exact": {"Tomica"}}),
    (("uniqlo",), {"contains_any": ["T-Shirt", "T Shirt", "Tee"], "brand_exact": {"Uniqlo"}}),
    (("montbell", "mont-bell"), {"prefix": "montbell"}),
    (("workman",), {"contains_any": ["Workman"]}),
    (tuple(_REEL_BRANDS), {"contains_any": ["Reel"]}),
]


def _check_title_format(title, brand_raw, rule):
    """1 タイトルを1ルールで検査 → 逸脱メッセージ list。"""
    out = []
    tl = title.lower()
    p = rule.get("prefix")
    if p and not title.startswith(p):
        out.append(f"タイトル形式逸脱: '{p}' で始まっていない(生成ロジック規定の形)")
    for c in rule.get("contains", []):
        if c.lower() not in tl:
            out.append(f"タイトル形式逸脱: 必須語 '{c}' がタイトルに無い")
    ca = rule.get("contains_any")
    if ca and not any(c.lower() in tl for c in ca):
        out.append(f"タイトル形式逸脱: {ca} のいずれもタイトルに無い")
    exp = rule.get("brand_exact")
    if exp and brand_raw and brand_raw not in exp:
        out.append(f"Brand='{brand_raw}' は eBay公式ブランド名でない(期待:{sorted(exp)} / フィルタ不ヒット)")
    return out


def title_format_checks(headers, row, project):
    """カテゴリ別タイトル生成フォーマットへの準拠を検証。"""
    hm = {h: i for i, h in enumerate(headers)}
    ti = hm.get(COL_TITLE)
    title = (str(row[ti]).strip() if ti is not None and ti < len(row) else "")
    if not title:
        return []
    if project in TITLE_FORMAT:
        return _check_title_format(title, "", TITLE_FORMAT[project])
    if project == "mercari":
        bi = hm.get("C:Brand")
        brand_raw = (str(row[bi]).strip() if bi is not None and bi < len(row) else "")
        brand = brand_raw.lower()
        if not brand:
            return []
        for brands, rule in MERCARI_TITLE_FORMAT:
            if any(b in brand for b in brands):
                return _check_title_format(title, brand_raw, rule)
    return []


# タイトル SEO 監査 (iMakKeywords PDF 参照):
# 生成は PDF 上位検索語でタイトルを最適化する建前 → 監査でも「PDF上位語を活かせてるか」を見る。
# PDF は pdftotext で .txt 化済 (C:/dev/iMak_data/keywords/)。csv_auditor は別 python 実行のため
# 実行時 pdftotext は呼ばず静的 txt を読む。PDF 更新時は再変換が必要。
# 安全設計: PDF上位語には他ブランド名 (rolex 等) が混ざる → 個別語の「足せ」提案はしない (誤キーワード=捏造)。
# 代わりに PDF プールでタイトルを採点し「同じ CSV 内で SEO が相対的に弱い行」を報告 (report-only)。
KEYWORD_DIR = r"C:/dev/iMak_data/keywords"
_TXT_TOYS = "toys_hobbies_2026q1.txt"
_TXT_JEWEL = "jewelry_watches_2026q1.txt"
_TXT_COLLECT = "collectibles_2026q1.txt"
_TXT_CLOTHING = "clothing_shoes_accessories_2026q1.txt"
_TXT_SPORTING = "sporting_goods_2026q1.txt"
KEYWORD_TXT = {
    "tcg": _TXT_TOYS,
    "gshock": _TXT_JEWEL,
    "ichibankuji": _TXT_COLLECT,
}
# Mercari は商品混在 → C:Brand で商品判定して PDF を出し分け (反射的に1PDFにしない)
MERCARI_BRAND_TXT = [
    (("porter", "uniqlo", "montbell", "mont-bell", "workman"), _TXT_CLOTHING),
    (("tomica",), _TXT_TOYS),
    (tuple(_REEL_BRANDS), _TXT_SPORTING),
]
_KW_LINE_RE = re.compile(r"^\s*(\d+)\s+(?:\d+|NEW)\s+(?:\d+|-|NEW)\s+(.+?)\s*$")
_KW_POOL_CACHE = {}


def _load_pool_file(fn):
    """PDF txt(ファイル名) → {keyword_lower: score}. score = max(0, 1 - rank/200). ファイル名でキャッシュ。"""
    if fn in _KW_POOL_CACHE:
        return _KW_POOL_CACHE[fn]
    pool = {}
    path = os.path.join(KEYWORD_DIR, fn) if fn else None
    if path and os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _KW_LINE_RE.match(line)
                if not m:
                    continue
                rank = int(m.group(1))
                kw = m.group(2).strip().lower()
                if not kw or kw.isdigit() or len(kw) < 3 or kw in ("rank", "prev rank", "keyword"):
                    continue
                sc = max(0.0, 1.0 - rank / 200.0)
                if kw not in pool or pool[kw] < sc:
                    pool[kw] = sc
    _KW_POOL_CACHE[fn] = pool
    return pool


def _load_keyword_pool(project):
    """project → pool (単一PDFカテゴリ用)。"""
    fn = KEYWORD_TXT.get(project)
    return _load_pool_file(fn) if fn else {}


def _mercari_pdf_for_brand(brand_lower):
    """Mercari の C:Brand から対応 PDF txt を判定 (porter/uniqlo→衣料, tomica→toys, リール→sporting)。"""
    if not brand_lower:
        return None
    for brands, fn in MERCARI_BRAND_TXT:
        if any(b in brand_lower for b in brands):
            return fn
    return None


def _title_seo_score(title, pool):
    """タイトルに含まれる PDF上位語の score 合計 (= SEO の効き具合)。"""
    tl = " " + title.lower() + " "
    return round(sum(sc for kw, sc in pool.items() if kw in tl), 3)


def _flag_weak_seo(scored, headers):
    """[(title,row,score)] → 中央値の0.6未満を SEO弱として報告。3行未満は相対比較せず空。"""
    if len(scored) < 3:
        return []
    vals = sorted(s for _, _, s in scored)
    thr = vals[len(vals) // 2] * 0.6
    return [(_row_sku(headers, row),
             f"SEO弱: PDF上位語の活用が他行比で低い (score={s} < 閾値{round(thr, 2)}) 「{t[:45]}」")
            for t, row, s in scored if s < thr]


def _title_check_project(project, is_generic):
    """タイトル検査(整合/形式/SEO)で使う実効 project。
    generic(reel/tomica/workman 等=check_csv 無し)は C:Brand 判定で mercari ルールを適用 → 取りこぼし防止。"""
    return "mercari" if is_generic else project


def title_seo_findings(headers, rows, project):
    """PDF 上位語でタイトルを採点 → 同 CSV 内で SEO が相対的に弱い行を報告 (SEO_NOTE)。
    Mercari は商品混在のため C:Brand で PDF を出し分け、商品グループごとに相対比較する。"""
    hm = {h: i for i, h in enumerate(headers)}
    ti = hm.get(COL_TITLE)
    if ti is None:
        return []

    def _score(row, pool):
        t = str(row[ti]).strip() if ti < len(row) else ""
        return (t, row, _title_seo_score(t, pool)) if t else None

    if project == "mercari":
        bi = hm.get("C:Brand")
        groups = {}  # txt → [(t,row,score)]
        for row in rows:
            brand = (str(row[bi]).strip().lower() if bi is not None and bi < len(row) else "")
            fn = _mercari_pdf_for_brand(brand)
            if not fn:
                continue
            pool = _load_pool_file(fn)
            if not pool:
                continue
            sc = _score(row, pool)
            if sc:
                groups.setdefault(fn, []).append(sc)
        out = []
        for grp in groups.values():
            out.extend(_flag_weak_seo(grp, headers))
        return out

    pool = _load_keyword_pool(project)
    if not pool:
        return []  # PDF 未整備カテゴリ → skip
    scored = [s for s in (_score(row, pool) for row in rows) if s]
    return _flag_weak_seo(scored, headers)


def generic_findings(headers, row):
    """check_csv を持たないカテゴリ(reel/tomica/workman等)向けの最低限監査。
    誤出品に直結する普遍的なタイトル安全のみ: 日本語混入 + 80字超。
    spec/価格/送料はカテゴリ別ルールが要るので generic では見ない(報告に明記)。"""
    out = list(native_findings(headers, row))
    hm = {h: i for i, h in enumerate(headers)}
    ti = hm.get(COL_TITLE)
    title = str(row[ti]).strip() if ti is not None and ti < len(row) else ""
    if len(title) > _MAX_TITLE:
        out.append(("ERROR", f"タイトル{len(title)}字 > 上限{_MAX_TITLE}字"))
    return out


# ============================================================================
# 機械的修正: 送料ポリシー
# ============================================================================
def fix_shipping_policies(headers, rows, lc_category):
    """価格→get_shipping_policy_name で送料ポリシーを再計算し不一致を修正。
    返り値: 修正リスト [(row_idx_1based, old, new, price)]。rows を in-place 更新。
    """
    try:
        from listing_common import get_shipping_policy_name
    except Exception as e:
        print(f"  ⚠️ get_shipping_policy_name import 失敗 (送料修正skip): {e}")
        return []
    hm = {h: i for i, h in enumerate(headers)}
    pi, si = hm.get(COL_PRICE), hm.get(COL_SHIP)
    if pi is None or si is None:
        return []
    fixes = []
    for i, row in enumerate(rows, 1):
        if si >= len(row):
            continue
        try:
            price = float(str(row[pi]).replace(",", "").replace("$", "").strip())
        except (ValueError, TypeError):
            continue
        try:
            expected = get_shipping_policy_name(price, lc_category)
        except Exception:
            continue
        cur = str(row[si]).strip()
        if expected and cur != expected:
            fixes.append((i, cur, expected, price))
            row[si] = expected
    return fixes


# ============================================================================
# 依頼書生成 (auto_catalog_add_request パターン)
# ============================================================================
def _today():
    # 日付は呼び出し側が固定できるよう env で上書き可 (テスト/再現性)
    return os.environ.get("CSV_AUDITOR_DATE") or datetime.date.today().isoformat()


def write_catalog_request(project, items, dry_run):
    """データ誤り/spec空 → カタログ修正依頼 .md。items=[(sku, reason)]。"""
    if not items:
        return None
    path = os.path.join(CATALOG_REQ_DIR, f"{_today()}_audit_catalog_fix_{project}.md")
    body = [
        f"# 自動依頼 (CSV監査くん → Catalog): {project} カタログ修正",
        f"- 依頼日: {_today()} / 依頼者: HQ `csv_auditor.py` / 緊急度: 中",
        "- 検出: 出品CSV監査でデータ誤り/必須spec空を検出 (fail-closed=該当行は出品から除外済)",
        "- 原則: 公式情報元のみ・ID完全一致lookup・推測禁止(fail-closed)。完了後 `_processed.md` rename",
        "",
        f"## 対象 ({len(items)}件)",
        "| SKU/識別 | 検出内容 |",
        "|---|---|",
    ]
    for sku, reason in items:
        body.append(f"| {sku} | {reason} |")
    body.append("\n※catalogに値が在るのにCSVが空なら generator 脱落の可能性 (要切り分け)。")
    text = "\n".join(body)
    if not dry_run:
        os.makedirs(CATALOG_REQ_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return path


def write_program_request(project, items, dry_run):
    """生成プログラムのバグ → プログラム修正依頼 .md (報告のみ)。items=[(sku, reason)]。"""
    if not items:
        return None
    path = os.path.join(REVIEW_DIR, f"{_today()}_audit_program_fix_{project}.md")
    gen = {"tcg": "iMakTCG/psa_to_csv.py", "gshock": "iMakG-shock/gshock_to_csv.py",
           "ichibankuji": "iMak_ichibankuji/ichibankuji_to_csv.py"}.get(project, "?")
    body = [
        f"# 自動報告 (CSV監査くん): {project} 生成プログラムの出力不正",
        f"- 報告日: {_today()} / 生成元(推定): {gen} / 該当行は出品から除外済",
        "- 自動修正はしない (値の捏造禁止)。generator 側で根治する。",
        "",
        f"## 症状 ({len(items)}件)",
        "| SKU/識別 | 症状 |",
        "|---|---|",
    ]
    for sku, reason in items:
        body.append(f"| {sku} | {reason} |")
    text = "\n".join(body)
    if not dry_run:
        os.makedirs(REVIEW_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return path


def _row_sku(headers, row):
    hm = {h: i for i, h in enumerate(headers)}
    for key in ("CustomLabel", "*Title"):
        i = hm.get(key)
        if i is not None and i < len(row) and str(row[i]).strip():
            return str(row[i]).strip()[:48]
    return "(no-sku)"


# identity = 「その item_id が何の商品か」を Catalog が引ける最小情報。カテゴリ別 if を作らず
# 列の有無で拾う (無い列は素通り) → TCG/G-shock/Mercari どれでも同じ経路で効く。
# 並び順 = 識別力の高い順。max_len で切れても手掛かりが残るようにする
# (C:Franchise は C:Game と冗長なので入れない)。
_IDENTITY_KEYS = (
    "C:Card Number", "C:Card Name", "C:Character", "C:Set", "C:Language", "C:Game",
    "C:Brand", "C:Model", "C:MPN",
)


def card_identity(headers, row, max_len=90):
    """CSV 行から商品 identity 文字列を組む (純関数)。

    item_id (CustomLabel=m*/PSA10-*) は出品IDでありカードIDではないため、Catalog は
    それ単体では対象を特定できない (= 依頼が backfill 不能で永久再掲。2026-07-15 発覚)。
    生成物である CSV 行には catalog 由来の事実 (カード番号/名/セット) が既に載っているので、
    それを identity として同送する。値は **CSV にある事実のみ** (推測・補完はしない)。
    Returns: "OP04-119 | Donquixote Rosinante | Kingdoms of Intrigue" / 手掛かり無しは ""。
    """
    hm = {h: i for i, h in enumerate(headers)}
    parts = []
    for key in _IDENTITY_KEYS:
        i = hm.get(key)
        if i is None or i >= len(row):
            continue
        v = str(row[i]).strip()
        if v and v not in parts:
            parts.append(v)
    if not parts:                       # spec が全滅の行 → タイトルを手掛かりに (空欄よりマシ)
        i = hm.get("*Title")
        if i is not None and i < len(row):
            parts = [str(row[i]).strip()] if str(row[i]).strip() else []
    out = " | ".join(parts)
    return out[:max_len].strip(" |")


# ============================================================================
# メイン監査
# ============================================================================
def audit(csv_path, dry_run=False, with_market=False, log_path=None):
    project = None
    mod = load_csv = None
    # ロードは check_csv 経由 (HEADER_MAP 自動設定 + validate_row 再利用)
    headers0, rows0 = _peek_csv(csv_path)
    project = detect_category(headers0, rows0)
    if project is None:
        print(f"❌ CSVが空/読込不能: {csv_path}")
        return 2
    is_generic = project == "generic"
    print(f"▶ カテゴリ: {project}{' (汎用+C:Brand判定でタイトル形式/SEO検査)' if is_generic else ''} / "
          f"対象: {os.path.basename(csv_path)}{'  [DRY-RUN]' if dry_run else ''}")

    if is_generic:
        headers, rows = _peek_csv(csv_path)
        mod = None
        lc_category = None
    else:
        mod = load_check_csv_module(project)
        headers, rows = mod.load_csv(csv_path)   # mod.HEADER_MAP も設定される
        lc_category = CATEGORY_MAP[project]["lc_category"]

    # 必須spec空で除外するか (apparel系は specが商品に合わず全滅するので False=報告のみ)
    spec_excl = (not is_generic) and CATEGORY_MAP.get(project, {}).get("spec_empty_excludes", True)

    # --- 行ごとに findings → disposition 集約 ---
    exclude_idx = []          # 1-based 除外行
    catalog_items, program_items = [], []
    identity_by_sku = {}      # sku(出品ID) → 商品identity。Catalog が依頼から対象を引くため
    seo_notes = []
    all_vr = []               # 各行 validate_row 結果 (Claude総合レビュー文脈用)
    for i, row in enumerate(rows, 1):
        if is_generic:
            findings = generic_findings(headers, row)
            all_vr.append([])
        else:
            vr = list(mod.validate_row(row, i))
            all_vr.append(vr)
            findings = vr + native_findings(headers, row)
        disps = [classify_finding(sev, msg) for sev, msg in findings]
        sku = _row_sku(headers, row)
        _ident = card_identity(headers, row)
        if _ident and not identity_by_sku.get(sku):
            identity_by_sku[sku] = _ident
        eff = []   # 除外判定用 (spec_empty_excludes=False のカテゴリは spec空を除外に倒さない)
        for (sev, msg), d in zip(findings, disps):
            if d == SPEC_EMPTY and not spec_excl:
                catalog_items.append((sku, msg))
                seo_notes.append((sku, "(必須spec空・要確認) " + msg))
                eff.append(SEO_NOTE)
                continue
            if d in (EXCLUDE_CATALOG, SPEC_EMPTY):
                catalog_items.append((sku, msg))
            elif d == REPORT_PROGRAM:
                program_items.append((sku, msg))
            elif d == SEO_NOTE:
                seo_notes.append((sku, msg))
            eff.append(d)
        # タイトル↔Item Specifics 整合 (生成ロジック準拠の検証):
        # 生成ロジックが catalog の事実からタイトルと spec の両方を作る → 食い違い = 生成のミス。
        # 報告のみ (phrasing差で誤除外しないよう exclude には倒さない) → プログラム修正依頼へ。
        # generic(reel/tomica/workman 等)でも C:Brand で商品判定して mercari ルールを適用 → 取りこぼし無し
        _tproj = _title_check_project(project, is_generic)
        for cmsg in title_spec_consistency(headers, row, _tproj):
            program_items.append((sku, cmsg))
        for fmsg in title_format_checks(headers, row, _tproj):
            program_items.append((sku, fmsg))
        if should_exclude(eff):
            exclude_idx.append(i)

    # --- 深い検査 (出品時チェックと同等: 市場ゲート / TOPセラーSEO / Claude AI総合レビュー) ---
    deep = with_market and not is_generic
    dc = (deep_checks(mod, headers, rows, all_vr, project, csv_path) if deep
          else {"price_exclude": [], "seo": [], "gate_summary": [], "claude": ""})
    for idx in dc["price_exclude"]:          # 価格 NO-GO を除外に合流
        if idx not in exclude_idx:
            exclude_idx.append(idx)
    exclude_idx.sort()
    seo_notes = seo_notes + dc["seo"]
    # タイトル SEO 監査 (PDF上位語の活用度。generic でも C:Brand で商品判定して適用)
    seo_notes = seo_notes + title_seo_findings(headers, rows, _title_check_project(project, is_generic))

    # --- 機械的修正: 送料ポリシー (fix_shipping=True のカテゴリのみ。Mercari/genericは無効=報告のみ) ---
    if not is_generic and CATEGORY_MAP[project].get("fix_shipping", True):
        ship_fixes = fix_shipping_policies(headers, rows, lc_category)
    else:
        ship_fixes = []

    # --- CSV 書込 (送料修正を反映) → その後 除外 ---
    if ship_fixes and not dry_run:
        _backup(csv_path, "shipfix")
        _write_csv(csv_path, headers, rows)
    excl_result = None
    if exclude_idx and not dry_run:
        excl_result = _exclude(csv_path, exclude_idx)   # 物理除外+backup

    # --- 依頼書 / 生成ログ ---
    cat_req = write_catalog_request(project, catalog_items, dry_run)
    prog_req = write_program_request(project, program_items, dry_run)
    log_signals = _scan_log(log_path) if log_path else []

    # ★AI 段 (TitleAgent / Vision / AI総合レビュー) が落ちていないか。落ちていれば緑で終わらせない。
    degraded = ai_degraded(log_path, dc.get("claude", ""), csv_path)

    _report(project, csv_path, dry_run, len(rows), exclude_idx, ship_fixes,
            catalog_items, program_items, seo_notes, cat_req, prog_req,
            log_signals, excl_result, dc["gate_summary"], dc["claude"], degraded)
    # --- CSV UPシグナルを即発報(反応速度最優先)。入稿可否=監査の決定論結果(行数-除外)。
    #     headless の起動・解析(数分)を待たずに UP できるようにする(ユーザー要望 2026-06-27) ---
    _signal_csv_up(csv_path, len(rows) - len(exclude_idx), dry_run, degraded)
    # --- PDCA: 台帳に蓄積 + 前回比トレンド + 再発検知 (dry-run は追記しない) ---
    _ledger_report(project, headers, rows, exclude_idx, program_items, seo_notes, dry_run)
    # --- PDCA spiral-up: 改善キュー蓄積 → 集約発行 → 完了同期 (write-only・絶対に監査を壊さない) ---
    _pdca_accumulate(project, catalog_items, program_items, dry_run, identity_by_sku,
                     audited_rows=len(rows),
                     audited_skus=[_row_sku(headers, r) for r in rows])
    # --- 決定論NG digest: program不整合 + logシグナル + 再発finding(pdca seen_count) を束ねる(無言スキップ防止=PDCA担保) ---
    # ★2026-07-25: recurring は project-scoped(監査対象=project のカテゴリのみ)。missing_models/pdca は
    # グローバル台帳のため、他プロジェクト由来(例 gshock 監査に dragonball_scg=TCG)の混入を除外。
    recurring = filter_recurring_for_project(recurring_findings(_load_pdca_recurring()), project)
    digest = _build_ng_digest(project, program_items, log_signals, recurring)
    digest_path = _write_ng_digest(project, digest, dry_run)
    if recurring:
        top = recurring[0]
        print(f"  🔁 再発finding(catalog依頼/修正で消えない) {len(recurring)}件 → 構造/コード疑い(Actで提案化)"
              f" / 筆頭 seen×{top['seen_count']}: {str(top['item_id'])[:50]}")
    # --- program修正 backlog を明示 surface (catalog と違い実装者=HQ 待ち。報告のみ→スルーを防ぐ) ---
    prog_open = _load_open_program_fix()
    if prog_open:
        print(f"  🛠️ 未対応 program修正 backlog {len(prog_open)}件 "
              f"(実装=HQ / `python program_fix_backlog.py` で詳細 / done で閉じる):")
        for r in prog_open[:6]:
            print(f"     seen×{r['seen_count']} {r['item_id']} ← {(r['evidence'] or '')[:50]}")
    # --- Act合図: 監査完了 → headless Claude をBG起動して NG対応(コピペ不要・digest各項目を必ず処分) ---
    _signal_claude_act(project, csv_path, log_path, dry_run, digest_path, digest)
    return 1 if (exclude_idx or program_items or catalog_items) else 0


def recurring_findings(rows, min_seen=2):
    """再発(複数ラン消えない)findings を抽出 (純関数, test可)。

    rows = [{"category","item_id","target_field","finding_type","seen_count","status"}] (pdca由来)。
    pending かつ seen_count>=min_seen = catalog依頼/修正を重ねても消えていない
    = 構造/コードの疑い(誤カテゴリ/adapter抽出不能/スコープ外/generator脱落の常習)。
    ※missing_models.csv は (cat,model) dedup されるので再発検出に使えない → pdca.db improvement_queue
      の seen_count(再発で++)を真の再発ソースとする。
    戻り: seen_count 降順 list。
    """
    out = [r for r in rows
           if (r.get("status") == "pending" and int(r.get("seen_count") or 0) >= min_seen)]
    out.sort(key=lambda r: int(r.get("seen_count") or 0), reverse=True)
    return out


def _load_pdca_recurring(min_seen=2, limit=25):
    """pdca.db improvement_queue から再発(pending・seen_count>=min_seen)を取得 (I/O・失敗は [])。"""
    try:
        import pdca_store as _pdca
        con = _pdca.connect()
        cur = con.execute(
            "SELECT category,item_id,target_field,finding_type,seen_count,status "
            "FROM improvement_queue WHERE status='pending' AND seen_count>=? "
            "ORDER BY seen_count DESC LIMIT ?", (min_seen, limit))
        rows = [{"category": r["category"], "item_id": r["item_id"],
                 "target_field": r["target_field"], "finding_type": r["finding_type"],
                 "seen_count": r["seen_count"], "status": r["status"]} for r in cur.fetchall()]
        con.close()
        return rows
    except Exception as _e:
        print(f"  ⚠️ pdca 再発取得skip: {type(_e).__name__}")
        return []


def _load_open_program_fix(limit=50):
    """未対応(pending)の program_fix backlog を seen_count 降順で読む (surface用, read-only)。"""
    try:
        import pdca_store as _pdca
        con = _pdca.connect()
        cur = con.execute(
            "SELECT item_id, seen_count, evidence FROM improvement_queue "
            "WHERE finding_type='program_fix' AND status='pending' "
            "ORDER BY seen_count DESC, updated_ts DESC LIMIT ?", (limit,))
        rows = [{"item_id": r["item_id"], "seen_count": r["seen_count"],
                 "evidence": r["evidence"]} for r in cur.fetchall()]
        con.close()
        return rows
    except Exception:
        return []


def _build_ng_digest(project, program_items, log_signals, recurring):
    """決定論で検出した NG を1つに束ねる (純関数, test可)。headless が各項目を必ず処分する元。"""
    return {
        "project": project,
        "program_items": [{"sku": s, "msg": m} for s, m in program_items],
        "log_signals": list(log_signals or []),
        "recurring_missing": recurring,
        "counts": {"program": len(program_items), "log": len(log_signals or []),
                   "recurring_missing": len(recurring)},
    }


def _write_ng_digest(project, digest, dry_run):
    """NG digest を JSON 化 (PDCA の決定論記録)。戻り: path or ''。dry-run は書かない。"""
    if dry_run:
        return ""
    try:
        os.makedirs(REVIEW_DIR, exist_ok=True)
        p = os.path.join(REVIEW_DIR, f"ng_digest_{_today()}_{project}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(digest, f, ensure_ascii=False, indent=2)
        return p
    except Exception as _e:
        print(f"  ⚠️ NG digest 書込skip: {type(_e).__name__}")
        return ""


def _build_act_prompt(project, csv_path, log_path, digest_path="", digest=None):
    """headless Claude(claude -p)へ渡す NG対応(Act)指示文 (純関数, test可)。"""
    report = os.path.join(REVIEW_DIR, f"csv_auditor_{_today()}_{project}.md")
    act_out = os.path.join(REVIEW_DIR, f"ng_act_{_today()}_{project}.md")
    run_logs = os.path.join(WORKSPACE, "iMakHQ", "run_logs")
    notify = os.path.join(WORKSPACE, "iMakHQ", "tools", "notify_csv_ready.py")
    cnt = (digest or {}).get("counts", {})
    digest_line = (
        f"- 【決定論NG digest】{digest_path}\n"
        f"  (program不整合 {cnt.get('program',0)}件 / logシグナル {cnt.get('log',0)}件 / "
        f"再発missing {cnt.get('recurring_missing',0)}件)。"
        "**この digest の各項目に必ず処分(直した/依頼した/コード修正提案/誤検出打消し/対応不要+理由)を1件ずつ書け。"
        "無言で飛ばすな**(=これが無いと PDCA にならない)。\n"
    ) if digest_path else ""
    return (
        "あなたは iMak HQ Claude(出品専任)。出品くんの自動ランが完了した直後に、CSV監査くんから"
        "無人で呼ばれた。memory `ng_items_need_proactive_action` の手順で NG対応(Actフェーズ)を実行せよ。\n"
        f"- 対象CSV: {csv_path}\n"
        f"- 監査レポート: {report}\n"
        f"- 生成ログdir(最新.logを読む): {run_logs}\n"
        f"- NG台帳: {MISSING_MODELS_PATH}\n"
        + digest_line +
        "【優先順位 — CSV UP を最優先】\n"
        "①CSVを手直し: 監査の必須spec空/タイトル短/形式を点検。catalogに値が在るのに空=generator脱落のみ"
        "CSVを直接修正。日本語blank/catalog欠落由来の空欄は fail-closed で正(推測で埋めるな)。最終 入稿可否件数を確定。\n"
        f"②CSV UPシグナル: **csv_auditor が監査終了時に即発報済**(入稿可否件数=行数-除外の決定論値)。"
        f"あなた(headless)は通常やらなくてよい。**例外**: ①の手直しで入稿可否件数が変わった時だけ、"
        f"更新後の件数Nで `python \"{notify}\" <N> \"{csv_path}\"` をBG再発報。入稿(eBayアップ)自体はするな=人の操作。\n"
        "③カタログ依頼+誤検出整理(UPシグナルの後): 本物欠落は該当worktreeの requests/ に完全な依頼書"
        "(cert/brand/番号/subject+source)投入(catalog追加は2026-05-25合意で確認不要)。catalogに実在するのに"
        "『要調査』の誤検出は missing_models を打消し+真因(viewer/generator)を特定。誤カテゴリは訂正。\n"
        "【再発missing の扱い=重要】digest の recurring_missing(複数日 catalog未登録のまま)は、catalog依頼を"
        "再投入するだけでは消えない構造問題(誤カテゴリ/adapter抽出不能/スコープ外)の疑い。**catalog依頼で済ませず、"
        "真因仮説+コード修正提案を必ずレポートに書け**(=PDCA の Act)。\n"
        "【制約・厳守】プログラムのコード修正と git commit はするな(『修正が修正を生む』防止=人間レビュー必須)。"
        "必要なコード修正は提案として列挙するだけ。本番入稿・eBay revision・その他不可逆/外向き操作もするな。\n"
        # ★2026-07-31: 提案の行き先を作る。従来は ng_act_*.md に書くだけで **誰も読まず消えていた**
        #   (実測: 7/30 の提案「SDBH SCG が catalog 全体未登録」は妥当だったが放置され、
        #    翌日 Advisor が同じ問題を再発見して依頼書化していた = 二度手間)。
        #   requests に置けば worktree ボードに載り、窓口が拾える。
        "【★コード修正提案の行き先】提案が1件以上あるなら、レポートに書くだけでなく "
        "`C:/dev/iMak_data/hq/requests/<YYYY-MM-DD>_act_code_proposals_<project>.md` にも同じ内容を書け"
        "(既に同名があれば**上書きせず追記もせず skip**=重複投入回避)。1件も無いなら作るな。"
        "冒頭に『依頼日/依頼者=CSV監査くん Act/緊急度/フェーズ=提案』を明記し、提案ごとに"
        "**現象・実機で確認した根拠・影響件数・修正案・触るファイル**を書くこと。\n"
        f"【出力】完了後、Actレポートを {act_out} に書け"
        "(形式: ①CSV=入稿可否N件(理由) / ②UPシグナル発報済 / ③依頼N件・誤検出打消しM件・コード修正提案K件 / "
        "digest各項目の処分一覧)。"
    )


def _resolve_claude_exe(claude_bin):
    """claude.CMD shim → 実体 claude.exe を解決 (純関数, test可)。

    csv_auditor は control_panel の subprocess で、終了後 `taskkill /F /T` でツリー一括kill される。
    .CMD shim を起動すると cmd→claude.exe がツリーに残り tree-kill で巻き込まれる(2026-06-27 実測で
    DETACHED/CNW どの flag でも taskkill /T からは逃げられないと確認)。→ 実体 .exe を中継経由で
    起動し、中継を即終了させてツリーから外す(=tree-kill 生存)。
    """
    if claude_bin and claude_bin.lower().endswith(".exe"):
        return claude_bin
    candidates = []
    base = os.path.dirname(claude_bin or "")
    if base:
        candidates.append(os.path.join(
            base, "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe"))
    # ★2026-07-23: 出品くん subprocess は PATH に npm dir が無く which('claude')=None になる
    #   (7/20以降 Act合図が毎回 skip されていた真因)。既知の標準 install 位置へフォールバック。
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        candidates.append(os.path.join(
            appdata, "npm", "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe"))
    for exe in candidates:
        if os.path.exists(exe):
            return exe
    return claude_bin or ""


def _act_disabled(dry_run):
    """Act/UP の自動発報を抑止すべきか (dry-run/test/env)。"""
    return (dry_run or os.environ.get("CSV_AUDITOR_NO_SIGNAL") == "1"
            or "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST")))


def _detached_spawn(argv, stdout_path=None):
    """argv を tree-kill 耐性で BG 起動 (中継 python が DETACHED 起動して即終了)。

    control_panel は csv_auditor 終了後 taskkill /F /T でツリー一括kill する。直接 Popen だと
    子孫として巻き込まれて即死(2026-06-27 実測: DETACHED/CNW どの flag でも /T から逃げられない)。
    中継を1つ噛ませ即終了させると、起動対象は orphan 化してツリーから外れ生存する。
    """
    payload = list(argv)
    launcher = (
        "import subprocess,sys,json\n"
        "argv=json.loads(sys.argv[1]); logp=sys.argv[2] or None\n"
        "out=open(logp,'w',encoding='utf-8') if logp else subprocess.DEVNULL\n"
        "subprocess.Popen(argv,stdout=out,stderr=subprocess.STDOUT,"
        # ★2026-07-31: DETACHED_PROCESS(0x08) をやめ CREATE_NO_WINDOW(0x08000000) に。
        #   DETACHED はコンソールを継承しないだけで、コンソールアプリ(claude.exe)には
        #   Windows が **新しいコンソールを割り当てる** → 監査終了ごとに CMD がちらつく
        #   (ユーザー報告 2026-07-31)。NO_WINDOW ならウィンドウ自体が作られない。
        #   tree-kill 耐性は「中継が即終了して孤児化する」ことで担保しており DETACHED に
        #   依存していない。実験で両 flags とも中継終了後に子が生存することを確認済。
        "creationflags=0x00000200|0x08000000)\n"   # CREATE_NEW_PROCESS_GROUP|CREATE_NO_WINDOW
    )
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen([sys.executable, "-c", launcher, json.dumps(payload), stdout_path or ""],
                     creationflags=flags)


def _signal_csv_up(csv_path, n_listable, dry_run, degraded=()):
    """入稿可否が確定した瞬間(監査終了時)に UP 通知を**即**発報 (反応速度=最優先)。

    入稿可否は監査くんが自分で持つ決定論情報(エラー数/ゲート/除外)。headless の起動・ログ読込
    (数分)を待たずに csv_auditor が直接 UP を出す → ユーザーは即 UP できる。headless は遅くて
    良い③(依頼/コード提案)だけ裏で回す。戻り: "skipped"/"fired"/"error:<type>" (test可)。
    """
    if _act_disabled(dry_run):
        return "skipped"
    try:
        notify = os.path.join(WORKSPACE, "iMakHQ", "tools", "notify_csv_ready.py")
        note = " | ".join(degraded or ())
        _detached_spawn([sys.executable, notify, str(n_listable), csv_path] + ([note] if note else []))
        if note:
            # ★内容は正しいが AI 補強 (タイトル最適化・絵柄照合・総合レビュー) が効いていない。
            #   「入稿するな」ではなく「**このまま入れると SEO が弱い**」を必ず見せる。
            print(f"  ⚠️ CSV UPシグナル: {n_listable}件 — **AI補強が落ちた走行** ({note})")
            print("     内容は監査済みだが タイトル最適化/絵柄照合 が効いていない。"
                  "急がないなら復旧後に再走を推奨")
            return "fired_degraded"
        print(f"  🟢 CSV UPシグナル即発報: {n_listable}件 入稿OK → UPして(headless③は裏で継続)")
        return "fired"
    except Exception as _e:
        print(f"  ⚠️ UPシグナル skip(監査は完了): {type(_e).__name__}")
        return f"error:{type(_e).__name__}"


def _signal_claude_act(project, csv_path, log_path, dry_run, digest_path="", digest=None):
    """監査完了後に headless Claude を BG 起動して NG対応(Act)を回す (ユーザー要望 2026-06-26)。

    監査くんが終わったら HQ に合図 → コピペ不要で ①CSV→②修正+依頼。
    - 非dry-run のみ。`CSV_AUDITOR_NO_SIGNAL=1` で無効化(test/CI/手動確認時)。
    - **tree-kill 生存が肝**: control_panel は csv_auditor 終了後 `taskkill /F /T` でツリーを一括kill
      する(control_panel.py:_kill_process_tree)。claude を csv_auditor の子孫のまま起動すると即死
      (2026-06-27 実測: DETACHED/CNW どの flag でも /T からは逃げられない)。→ **中継 python を1つ
      噛ませ、中継が claude.exe を DETACHED 起動して即終了**する。中継が死ぬと claude は orphan 化し
      csv_auditor のツリーから外れる → tree-kill 生存(実測 SURVIVED 確認)。
    - try/except で監査本体は絶対に壊さない。headless にはコード修正/commit/入稿をさせない(提案止まり)。
    - digest_path/digest: 決定論NG digest を渡し、各項目を必ず処分させる(無言スキップ防止=PDCA担保)。
    戻り: "skipped"(dry/env) / "no-cli" / "spawned" / "error:<type>" (test 可)。
    """
    if _act_disabled(dry_run):
        return "skipped"
    try:
        claude_exe = _resolve_claude_exe(shutil.which("claude"))
        if not claude_exe or not os.path.exists(claude_exe):
            print("  ⚠️ claude.exe 不在 → Act合図 skip(『見て』で手動起動可)")
            return "no-cli"
        prompt = _build_act_prompt(project, csv_path, log_path, digest_path, digest)
        os.makedirs(REVIEW_DIR, exist_ok=True)
        log_file = os.path.join(REVIEW_DIR, f"ng_act_{_today()}_{project}.log")
        prompt_file = os.path.join(REVIEW_DIR, f"ng_act_{_today()}_{project}.prompt.txt")
        with open(prompt_file, "w", encoding="utf-8") as pf:
            pf.write(prompt)
        # claude.exe を中継経由 detach 起動(tree-kill 耐性)。prompt はファイル渡し。
        _detached_spawn(
            [claude_exe, "-p", prompt,
             "--dangerously-skip-permissions", "--add-dir", r"C:\dev\iMak_data", "--add-dir", WORKSPACE],
            stdout_path=log_file)
        print(f"  🤖 Act(③依頼/コード提案)を headless にBG委譲(tree-kill耐性) → "
              f"review_logs/ng_act_{_today()}_{project}.md")
        return "spawned"
    except Exception as _e:
        print(f"  ⚠️ Act合図 skip(監査は完了): {type(_e).__name__}: {_e}")
        return f"error:{type(_e).__name__}"


_PSA_CACHE_DIR = os.path.join(WORKSPACE, "iMakeBayAPI", "cache", "psa_certs")


def _identity_from_psa_cache(cert: str) -> str:
    """PSA cert 番号 → identity 文字列 (純関数寄り、失敗は "")。

    csv_auditor が pdca_store に渡す identity は、通常は CSV 行の spec 列
    (C:Card Number/C:Card Name/C:Set) から組む。ところが post_psa_review で
    NONE 判定 → CSV 除外された cert は CSV 行が無く identity 空欄となり、Catalog は
    「どのカードか」を解決できず依頼が永久再掲されていた (2026-07-27 Advisor 指摘)。
    素材は PSA cache に持っているので (Brand/Subject/CardNumber)、そこから identity を
    組んで backfill する = 経路 A の穴を塞ぐ。

    Returns: "CARDNUMBER | Subject | Brand" 形式 (欠けは省略)。cache 無しは ""。
    """
    if not cert:
        return ""
    path = os.path.join(_PSA_CACHE_DIR, f"{cert}.json")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        return ""
    parts = []
    for k in ("CardNumber", "Subject", "Brand"):
        v = (meta.get(k) or "").strip()
        if v and v not in parts:
            parts.append(v)
    return " | ".join(parts)[:120]


_CSV_HISTORY_IDENTITIES = None      # {sku: identity} 遅延構築 (プロセス内 1 回)


def _load_csv_history_identities(csv_dir=None):
    """過去に生成した出品CSV から {CustomLabel: identity} を作る (新しい順、初出優先)。

    identity の材料 (カード番号/名/セット) は **その行を作った時に catalog から引いた事実**
    なので、CSV が残っていれば後からでも復元できる。PSA cache に無いメルカリ出品
    (m*) はこれが唯一の手掛かり (2026-08-01: 保留 4 件がすべてここで解決できた)。
    推測は一切しない = CSV に載っている値だけを組む (card_identity と同じ規則)。
    """
    global _CSV_HISTORY_IDENTITIES
    if _CSV_HISTORY_IDENTITIES is not None:
        return _CSV_HISTORY_IDENTITIES
    out = {}
    d = csv_dir or os.path.join(WORKSPACE, "iMakHQ", "csv_output")
    try:
        files = sorted(glob.glob(os.path.join(d, "*.csv")), key=os.path.getmtime, reverse=True)
    except Exception:
        files = []
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace", newline="") as f:
                r = _csv.reader(f)
                headers = next(r)
                hm = {h: i for i, h in enumerate(headers)}
                ci = hm.get("CustomLabel", hm.get("*CustomLabel"))
                if ci is None:
                    continue
                for row in r:
                    if ci >= len(row):
                        continue
                    sku = str(row[ci]).strip()
                    if not sku or sku in out:
                        continue          # 新しい CSV の値を優先 (初出勝ち)
                    ident = card_identity(headers, row)
                    if ident:
                        out[sku] = ident
        except Exception:
            continue                      # 壊れた CSV 1 本で全体を落とさない
    _CSV_HISTORY_IDENTITIES = out
    return out


def _identity_from_csv_history(sku: str) -> str:
    return _load_csv_history_identities().get((sku or "").strip(), "")


_VERIFIED_CERTS_PATH = r"C:/dev/iMak_data/dedupe/verified_certs.json"
_VERIFIED_PID_CACHE = None


def canonical_pid_for_item(item_id: str) -> str:
    """`PSA10-<cert>` → 目視で確定した canonical product_id。無ければ ""。

    ★2026-08-08 実測の真因: 除外リストは canonical product_id (`MC-746` `S8b-101`) で
      判定するのに、渡していたのは identity 先頭 = CSV の `C:Card Number`
      (= 印刷された「番号/総数」`746/742` `101/184`)。
      One Piece / Gundam は `OP04-119` 形式なので偶然一致していたが、
      **Pokemon は最初から一度も当たらない**。7/29-7/30 に足した
      `mc-` `si-` `cp4-` `cp5-` `s8b-` `m2a-` `sm8b-` `sv4a-` `s6k-` `xy-` `hszm-` は
      **1件も発火していなかった**。
      結果、公式に rarity が無い Pokemon が毎日 defect に残り、catalog へ
      draft を毎日投げ続けていた (「同じ件が何度も来る」の現役の発生源)。

    canonical PID は `verified_certs.json` (目視確定台帳) が持っている。
    """
    global _VERIFIED_PID_CACHE
    s = str(item_id or "")
    if not s.startswith("PSA10-"):
        return ""
    if _VERIFIED_PID_CACHE is None:
        try:
            import json as _json
            with open(_VERIFIED_CERTS_PATH, encoding="utf-8") as f:
                _VERIFIED_PID_CACHE = _json.load(f) or {}
        except Exception:
            _VERIFIED_PID_CACHE = {}
    rec = _VERIFIED_PID_CACHE.get(s[len("PSA10-"):])
    if not isinstance(rec, dict):
        return ""
    if (rec.get("choice") or "").upper() not in ("CHOSEN", "OK"):
        return ""
    return (rec.get("product_id") or "").strip()


def _still_required_spec(card_number: str, card_name: str, field: str,
                         item_id: str = "") -> bool:
    """その spec が **今の監査ルール** でもまだ必須か (queue の退役判定用)。

    SSOT は check_csv.required_specifics_for_card (DON!!/RESOURCE/ENERGY MARKER/
    Pokemon hi-class 等の「公式に存在しない」除外を持つ側)。ここに判定を複製しない。
    identity の 2 番目 (カード名) を card_type として渡す: 非該当種別は name がそのまま
    種別名 ('Resource' / 'Energy Marker')。通常カードの名前は除外集合に無いので誤退役しない。
    import 不能・field が必須リスト管理外なら True (= 消さない、fail-closed)。

    ★2026-08-09: **判定キーを canonical product_id にする**。identity 先頭は
      印刷番号 (`746/742`) で、除外リストの prefix (`mc-`) と噛み合わない。
      cert から canonical PID を引けたらそちらを使い、引けなければ従来どおり
      identity 先頭で判定する (= 悪化させない)。
    """
    if not str(field or "").startswith("C:"):
        return True
    try:
        sys.path.insert(0, os.path.join(WORKSPACE, "iMakTCG"))
        from check_csv import REQUIRED_SPECIFICS, required_specifics_for_card
    except Exception:
        return True
    if field not in REQUIRED_SPECIFICS:
        return True                       # そもそも必須リスト外 = ここで判定しない
    pid = canonical_pid_for_item(item_id)
    key = pid or card_number
    if field not in required_specifics_for_card(key, card_name):
        return False                      # set 単位で「公式に存在しない」= 退役
    # ★set 単位のリストでは **1枚だけ公式に無い** ケースを表現できない (2026-08-09 実測)。
    #   S10b は 93件中 85件 (91%) が rarity を持つので prefix 除外にすると
    #   欠落85枚を永久に見逃す。一方 S10b-055 (かがやくイーブイ) は公式に rarity 表記が無い。
    #   → **catalog にも値が無いなら defect ではない**。カード単位で判定する。
    #   catalog に値が有るのに CSV が空 = generator 脱落 = 本物の defect なので残す。
    if pid and not _catalog_has_spec_value(pid, field):
        return False
    return True


_SPEC_TO_CATALOG_KEY = {"C:Rarity": "rarity"}          # 対応が確かなものだけ扱う


def _catalog_has_spec_value(product_id: str, field: str) -> bool:
    """catalog がその spec に値を持っているか。判定不能は True (= 消さない、fail-closed)。"""
    key = _SPEC_TO_CATALOG_KEY.get(field)
    if not key:
        return True                       # 対応表に無い field は触らない
    try:
        import json as _json
        import sqlite3 as _sq
        con = _sq.connect(r"C:/dev/iMak_data/catalog/products.sqlite")
        try:
            row = con.execute(
                "SELECT specs FROM products WHERE product_id=? LIMIT 1", (product_id,)).fetchone()
        finally:
            con.close()
    except Exception:
        return True
    if not row:
        return True                       # catalog に居ない → 判定不能
    try:
        v = (_json.loads(row[0] or "{}") or {}).get(key)
    except Exception:
        return True
    return bool(str(v or "").strip())


def _resolve_identity(sku: str, identity_by_sku: dict | None) -> str:
    """identity_by_sku の値を優先し、空なら PSA cache fallback (純関数寄り)。

    経路 A (csv_auditor) 側で catalog に依頼を出すときの identity 解決 SSOT。
    CSV に載っている行は identity_by_sku[sku] にヒットする。CSV 除外 (post_psa_review
    NONE) されたが sku=PSA10-<cert> 形式なら PSA cache から backfill を試みる。
    """
    ident = (identity_by_sku or {}).get(sku, "") or ""
    if ident:
        return ident
    s = (sku or "")
    if s.startswith("PSA10-"):
        ident = _identity_from_psa_cache(s[len("PSA10-"):])
        if ident:
            return ident
    # 最後の砦: 過去の出品CSV (m* のメルカリ出品はここでしか解決できない)
    return _identity_from_csv_history(s)


def _pdca_accumulate(project, catalog_items, program_items, dry_run, identity_by_sku=None,
                     audited_rows=0, audited_skus=None):
    """catalog/program 指摘を pdca.db 改善キューに蓄積し、dedup済 catalog 依頼を集約発行 +
    処理済を done 同期 (PDCA spiral-up Phase1b+2)。dry-run は記録しない。
    write-only・try/except で監査本体には一切影響させない。"""
    if dry_run:
        return
    try:
        import re as _re
        import pdca_store as _pdca
        con = _pdca.connect()
        ts = _today()
        _seen_dkeys = set()      # 今回の走行で検出した finding (= 再検出なし判定の母集団)
        for sku, msg in catalog_items:
            ft = "必須Item Specific" if "必須" in msg else "catalog_gap"
            m = _re.search(r"'(C:[^']+)'", msg)
            field = m.group(1) if m else "catalog_request"
            _seen_dkeys.add(_pdca.dedup_key(project, sku, field, ""))
            _pdca.upsert_improvement(con, project, sku, field, "",
                                     evidence=str(msg)[:80], source="auditor", layer="A",
                                     finding_type=ft,
                                     identity=_resolve_identity(sku, identity_by_sku), ts=ts)
        from program_fix_backlog import program_signature as _prog_sig
        for sku, msg in program_items:
            _pdca.record_finding(con, ts, project, sku, "program", str(msg)[:120], ts=ts)
            # program バグも catalog と対称に actionable queue へ(閉ループ化 2026-06-29)。
            # 症状クラスで dedup し別SKUでの再発を seen_count に集約 → 慢性度が surface される。
            # closure: HQが直す→回帰テスト追加→program_fix_backlog.py done。直ってなければ
            # 次監査で同症状が再upsertされ done→pending に自動復活(=スルー不能)。
            _pdca.upsert_improvement(con, project, _prog_sig(msg), "program_fix", "",
                                     evidence=f"{sku}: {str(msg)[:90]}", source="auditor",
                                     layer="code", finding_type="program_fix", ts=ts)
        # psa_to_csv 検出の catalog未登録 (missing_models.csv) も queue へ (= 入稿しない catalog-miss を還元)
        _mm = _pdca.import_missing_models(con, MISSING_MODELS_PATH, ts=ts)
        # 解決済 prune: catalog に後から収録/索引修正された gap を done 化 → 真の未解決のみ emit
        # (毎回 stale を再発行して Catalog に積むのを止める。Catalog 指摘B)。
        pruned = 0
        try:
            pr = _pdca.prune_resolved_gaps(con, _pdca.make_catalog_resolver(CATALOG_DB), ts=ts)
            pruned = pr["pruned"]
        except Exception as _pe:
            print(f"  ⚠️ PDCA prune skip: {type(_pe).__name__}: {_pe}")
        synced = _pdca.sync_processed(con, CATALOG_REQ_DIR, ts=ts)        # ループ閉じ
        # 長期未解決(created_ts > 21日)の pending を stale 退役 → digest の恒久ノイズを断つ(K1/K5)。
        staled = 0
        try:
            staled = _pdca.prune_stale_findings(con, ts, max_age_days=21)["pruned"]
        except Exception as _se:
            print(f"  ⚠️ PDCA stale prune skip: {type(_se).__name__}")
        # 今回の走行で **再検出されなかった** auditor 由来 pending を閉じる (証拠で閉じる。2026-08-03)。
        # 時間 (days_stale) で閉じる案より速く正確: m81161788422 のように CSV 側が既に整合している
        # 指摘が、次の監査で即座に閉じる。CSVが空/0行の走行では1件も閉じない (fail-closed)。
        nored = 0
        try:
            _nr = _pdca.close_not_redetected(con, project, _seen_dkeys, audited_skus,
                                             ts=ts, audited_rows=audited_rows)
            nored = _nr["closed"]
            if _nr.get("skipped_reason"):
                print(f"  ⏭ 再検出なしclose: {_nr['skipped_reason']}")
        except Exception as _ce:
            print(f"  ⚠️ 再検出なしclose skip: {type(_ce).__name__}: {_ce}")
        # 既存行の identity 後埋め (解決経路を後から実装した分の救済 2026-08-01)。
        # これを通さないと、7/31 以前に積まれた PSA cert 行は再検出まで (不明) のまま出続ける。
        filled = 0
        try:
            filled = _pdca.backfill_identities(
                con, lambda iid: _resolve_identity(iid, identity_by_sku), ts=ts)["filled"]
        except Exception as _be:
            print(f"  ⚠️ PDCA identity backfill skip: {type(_be).__name__}: {_be}")
        # 「今のルールではもう必須でない」spec 指摘の退役 (7/29-30 の除外確定より前の残骸)。
        nonapp = 0
        try:
            nonapp = _pdca.prune_non_applicable_specs(con, _still_required_spec, ts=ts)["pruned"]
        except Exception as _ne:
            print(f"  ⚠️ 非該当spec prune skip: {type(_ne).__name__}: {_ne}")
        held = []
        emitted = _pdca.emit_consolidated_request(con, project, CATALOG_REQ_DIR, ts, held_out=held)
        con.commit()
        con.close()
        # 送らなかった分は毎回全件を残件リストに再掲 (黙って落とさない)。
        try:
            _pdca.write_unresolved_note(held, UNRESOLVED_IDENTITY_PATH, ts, category=project)
        except Exception as _we:
            print(f"  ⚠️ 未解決リスト書込 skip: {type(_we).__name__}: {_we}")
        if emitted or synced or pruned or staled or filled or nonapp or nored:
            print(f"  📊 PDCA: 集約発行 {emitted} 件 / 完了同期 {synced} 件 / "
                  f"再検出なしclose {nored} 件 / "
                  f"解決済prune {pruned} 件 / 長期stale退役 {staled} 件 / identity後埋め {filled} 件 / "
                  f"非該当spec退役 {nonapp} 件 (dedup済)")
        if held:
            print(f"  ⚠️ identity 未解決につき Catalog へ送らず保留 {len(held)} 件 "
                  f"(要対応・全件: {UNRESOLVED_IDENTITY_PATH})")
            for r in held[:10]:
                print(f"     - {r['item_id']} / {r['target_field']}")
    except Exception as _e:
        print(f"  ⚠️ PDCA accumulate skip (監査は継続): {type(_e).__name__}: {_e}")


def _finding_tag(msg):
    """finding メッセージ → 短い種別タグ (再発キー/集計用)。"""
    for t in ("形式逸脱", "タイトル↔spec不一致", "SEO弱", "禁止ワード", "日本語",
              "上限", "推奨", "必須Item Specific", "不整合", "誤マップ"):
        if t in msg:
            return t
    return "other"


def _ledger_report(project, headers, rows, exclude_idx, program_items, seo_notes, dry_run):
    """KPI を算出 → audit_ledger に記録 → 前回比トレンド/再発/解消 を表示 (PDCA の蓄積・測定)。"""
    hm = {h: i for i, h in enumerate(headers)}
    ti = hm.get(COL_TITLE)
    lens = []
    if ti is not None:
        for r in rows:
            t = str(r[ti]).strip() if ti < len(r) else ""
            if t:
                lens.append(len(t))
    n = len(lens) or 1
    summary = {
        "rows": len(rows),
        "excluded": len(exclude_idx),
        "program": len(program_items),
        "seo_weak": sum(1 for _, m in seo_notes if "SEO弱" in m),
        "short_titles": sum(1 for L in lens if L < IDEAL_TITLE_LEN),
        "format_violations": sum(1 for _, m in program_items if "形式逸脱" in m),
        "consistency_mismatch": sum(1 for _, m in program_items if "不一致" in m),
        "avg_title_len": round(sum(lens) / n, 1),
    }
    # 再発キー = item(SKU) × 種別。次回同じものが残ってれば「まだ直ってない」。
    keys = [f"{sku}|{_finding_tag(m)}" for sku, m in (program_items + seo_notes)]
    res = audit_ledger.record_run(project, summary, keys, write=not dry_run)

    print("\n📈 PDCA 台帳 (前回比トレンド / 再発検知):")
    prev = res["previous"]
    if not prev:
        print("   (このカテゴリ初回 → 次回からトレンド比較)")
    else:
        print(f"   前回: {prev.get('date', '?')}")
        for k, v in summary.items():
            d = res["trend"].get(k)
            arrow = audit_ledger.trend_arrow(k, d) if d is not None else "—"
            dtxt = f"{d:+g}" if isinstance(d, (int, float)) else "—"
            print(f"     {k}: {v} ({dtxt} {arrow})")
        if res["recurring"]:
            print(f"   ⚠️ 未解消(再発) {len(res['recurring'])}件 (前回も同じ item×種別が残存)")
        if res["resolved"]:
            print(f"   ✅ 解消 {len(res['resolved'])}件 (前回の指摘が消えた)")
    if dry_run:
        print("   (DRY-RUN: 台帳には記録していません)")
    print(f"   台帳: {audit_ledger.LEDGER_PATH}")


def _peek_csv(path):
    with open(path, encoding="utf-8") as f:
        r = list(_csv.reader(f))
    return (r[0], r[1:]) if r else ([], [])


def _backup(path, tag):
    bak = f"{path}.bak_auditor_{tag}"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
    return bak


def _write_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f, quoting=_csv.QUOTE_NONNUMERIC)
        w.writerow(headers)
        w.writerows(rows)


def _exclude(csv_path, nogo_indices):
    try:
        sys.path.insert(0, os.path.join(WORKSPACE, "iMakeBayAPI", "csv_postprocess"))
        from excluder import exclude_rows_from_csv
        return exclude_rows_from_csv(csv_path, nogo_indices)
    except Exception as e:
        print(f"  ⚠️ excluder 委譲失敗 (除外は手動で): {e}")
        return None


# ★2026-08-02: AI 段が落ちた走行を「🟢 入稿OK」で終わらせない。
#   実害 (2026-08-02 19:10): Anthropic API が credit 不足になり TitleAgent / Vision /
#   AI総合レビューが**全カードで失敗**したのに、走行は続行して最後は緑の「入稿OK」で終わった。
#   落ちたことは行間のログにしか出ておらず、タイトルが短くなって初めて気づいた
#   (short_titles 3件 / avg_title_len -7.2)。= degraded なのに正常と報告する fail-OPEN。
#   → **呼べたのに失敗した**時だけ ⚠️ に倒す。key 未設定 (= その環境では AI 無しが正常) は倒さない。
#   ★2026-08-03: 逆向きの事故も起きた。`529` を **裸で** 見ていたため PSA cert 番号
#   (`#152976738` / `#152976751`) の中の "529" に当たり、過負荷ゼロの走行が毎回
#   「⚠️ API過負荷: 3件」になっていた。狼少年になると本物の劣化を見落とすので、
#   **数値のステータスコードは必ず文脈語とセットで**見る (裸の数字を単独パターンにしない)。
AI_FAIL_PATS = [
    ("APIクレジット不足", r"credit balance is too low"),
    ("APIレート制限", r"rate_limit_error|429 Too Many Requests"),
    ("API過負荷", r"overloaded_error"
                 r"|(?:error code|status(?:[ _]code)?|http)[=: ]*\s*529\b"
                 r"|\b529\s+(?:server\s+)?overloaded"),
    ("APIエラー", r"Claude API ?エラー|invalid_request_error|authentication_error"),
]
# 「キーが無い」は環境設定であって失敗ではない。ここで倒すと毎回 ⚠️ になり警告が意味を失う。
AI_NOKEY_PAT = r"APIキーなし|api_key.*not set"


def generation_logs_for(csv_path, run_logs_dir=""):
    """その CSV に触れた走行のログを **全部** 返す (無ければ [])。

    ★2026-08-02: 監査くんは自分の run log しか見ておらず、**劣化は生成側で起きる**ため
    今日の実ケース (生成ログに credit エラー18件) を取り逃がしていた。
    生成ログには最後に「出力: <CSVのフルパス>」が入るので、**CSV名を含む最新の .log** を辿る。
    """
    if not csv_path:
        return []
    d = run_logs_dir or os.path.join(WORKSPACE, "iMakHQ", "run_logs")
    name = os.path.basename(csv_path)
    try:
        cands = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".log")]
    except OSError:
        return []
    hits = []
    for p in cands:
        try:
            if name in open(p, encoding="utf-8", errors="replace").read():
                hits.append(p)
        except OSError:
            continue
    # ★1本に絞らない。監査くん自身のログが最新になるため、絞ると **生成側の劣化を取り逃がす**
    #   (2026-08-02 の実ケースがこれ)。触れたログは全部読む。
    return sorted(hits, key=os.path.getmtime)


def ai_degraded(log_path="", claude_text="", csv_path="", run_logs_dir=""):
    """AI 段が **呼べたのに失敗した** 証拠を返す (純関数寄り・test可)。

    自分の run log だけでなく、**その CSV を生成した走行のログ**も見る
    (TitleAgent / Vision は生成側で動くので、監査くんのログには何も出ない)。
    戻り: ["APIクレジット不足: 9件", ...]。空 = 劣化なし (= 緑で終わってよい)。
    """
    paths = [p for p in ([log_path] + generation_logs_for(csv_path, run_logs_dir)) if p]
    txt = ""
    for p in dict.fromkeys(paths):                 # 同じ file を二度数えない
        if not os.path.exists(p):
            continue
        try:
            txt += open(p, encoding="utf-8", errors="replace").read() + "\n"
        except OSError:
            continue
    txt += "\n" + (claude_text or "")
    out = []
    for label, pat in AI_FAIL_PATS:
        n = len(re.findall(pat, txt, re.I))
        if n:
            out.append(f"{label}: {n}件")
    if not out and re.search(r"Claude review skip:", claude_text or ""):
        out.append("AI総合レビューが例外で落ちた")
    return out


def _scan_log(log_path):
    if not log_path or not os.path.exists(log_path):
        return []
    sig = []
    pats = [("catalog miss", r"missing_models|未登録|見つかりません"),
            ("HOLD/gate", r"HOLD|gate_row_or_hold|csv_hold"),
            ("error", r"❌|Traceback|ERROR")]
    try:
        txt = open(log_path, encoding="utf-8", errors="replace").read()
        for label, p in pats:
            n = len(re.findall(p, txt))
            if n:
                sig.append(f"{label}: {n}件")
    except Exception:
        pass
    return sig


_ASPECT_CACHE = {}


def load_aspects(project):
    """取得済 eBay公式 Aspects JSON (fetch_ebay_category_aspects 出力) をロード。"""
    path = CATEGORY_MAP.get(project, {}).get("aspect_json")
    if not path or not os.path.exists(path):
        return None
    if path not in _ASPECT_CACHE:
        try:
            _ASPECT_CACHE[path] = json.load(open(path, encoding="utf-8")).get("aspects", {})
        except Exception:
            _ASPECT_CACHE[path] = None
    return _ASPECT_CACHE[path]


# 意図的に出力しない aspect (= SEO提案で「追加しろ」と出すとCPSC等の方針と矛盾する)。
# 2026-06-29: TCG の Age Level は CPSC eFiling 対応で**わざと削除**(PSA鑑定品=非児童製品)。
# 監査くんが「列が無い→追加で検索性UP」と再提案すると、毎回ノイズ+誤再追加リスク → 抑制。
_INTENTIONALLY_OMITTED_ASPECTS = {
    "tcg": {"Age Level"},
}


def ebay_aspect_findings(headers, rows, project):
    """取得済 eBay公式フィルタ(Aspects)と Item Specifics を照合 = 武器の活用。API不要(offline)。
      ① SELECTION_ONLY の値が許容リスト外 → eBayフィルタ不ヒット (findability欠損)
      ② eBayが required/RECOMMENDED の aspect が「列無し or 全行空」 → SEO機会 (eBay自身が推奨)
    返り: [(sku, msg)] (SEO_NOTE 扱い・報告のみ。CSVは触らない)。"""
    asp = load_aspects(project)
    if not asp:
        return []
    omit = _INTENTIONALLY_OMITTED_ASPECTS.get(project, set())
    hm = {h: i for i, h in enumerate(headers)}
    notes = []
    # ① RECOMMENDED/required aspect の未充足 (CSV全体で集約=1回)
    for name, a in asp.items():
        if name in omit:
            continue   # 意図的に外した aspect は「追加しろ」と提案しない (CPSC方針と矛盾するため)
        c = a.get("constraint", {})
        if not (c.get("aspect_required") or c.get("aspect_usage") == "RECOMMENDED"):
            continue
        idx = hm.get("C:" + name)
        req = "必須" if c.get("aspect_required") else "推奨"
        if idx is None:
            notes.append(("(CSV全体)", f"eBay{req}aspect '{name}' の列が無い → 追加で検索性UP"))
        elif rows and sum(1 for r in rows if idx < len(r) and str(r[idx]).strip()) == 0:
            notes.append(("(CSV全体)", f"eBay{req}aspect '{name}' が全行空 → 埋めると検索性UP"))
    # ② SELECTION_ONLY の値が許容外 (行ごと・上限30)
    # eBay 普遍の特殊値 (values配列に載らないが eBay が許容する opt-out) は許容扱い。
    _SPECIAL_OK = {"does not apply", "does not apply.", "n/a", "na", "unbranded", "no", "none"}
    sel = {n: set(a.get("values", [])) for n, a in asp.items()
           if a.get("constraint", {}).get("aspect_mode") == "SELECTION_ONLY"}
    capped = 0
    for row in rows:
        for name, allowed in sel.items():
            idx = hm.get("C:" + name)
            if idx is None or idx >= len(row):
                continue
            v = str(row[idx]).strip()
            if v and v.lower() not in _SPECIAL_OK and v not in allowed:
                notes.append((_row_sku(headers, row),
                              f"'{name}'='{v}' が公式フィルタ許容値外(SELECTION_ONLY)→フィルタ不ヒット"))
                capped += 1
        if capped >= 30:
            break
    return notes


def deep_checks(mod, headers, rows, all_vr, project, csv_path):
    """出品時チェックと同じ深い検査を check_csv の関数を再利用して実行:
      ① 市場ゲート (build_search_query→search_ebay_active→compare_with_competitors)
         = 価格 GO/RELAX/HOLD/NO-GO + 利益計算。NO-GO は価格除外候補。
      ② (廃止 2026-06-15) TOPセラー Item Specifics 比較 = catalog決定論生成のため不使用。
      ③ Claude AI 総合レビュー (claude_review) = バッチ全体の品質所見。
    API/key 無い環境では静かに degrade (deep skip)。all_vr=各行のvalidate_row結果(claude文脈用)。
    返り: {price_exclude:[1based], seo:[(sku,msg)], gate_summary:[(i,status)], claude:str}
    """
    out = {"price_exclude": [], "seo": [], "gate_summary": [], "claude": ""}
    if mod is None:
        return out
    # 武器の活用: 取得済 eBay公式フィルタ(Aspects)照合 (API不要・offline)
    out["seo"].extend(ebay_aspect_findings(headers, rows, project))
    try:
        keys = mod.load_ebay_keys()
        token = mod.get_oauth_token(keys["AppID"], keys["AppSecret"]) if keys.get("AppID") else None
    except Exception as e:
        print(f"  ⚠️ eBay API 認証失敗 → 市場ゲート/SEO skip: {e}")
        token = None
    # 仕入値 (サイドカーJSON) を読む = 市場ゲートの GO/HOLD/NO-GO 判定に必須
    cost_data, cost_key = {}, CATEGORY_MAP.get(project, {}).get("cost_key")
    try:
        cost_data = mod.load_cost_data(csv_path) or {}
    except Exception:
        cost_data = {}
    all_comp, all_gates = [], []
    if token:
        print("  ✓ eBay API 接続OK (市場ゲート/SEO 実行)")
        for i, row in enumerate(rows):
            comp, gate = [], None
            try:
                query = mod.build_search_query(row)
                comps, total = mod.search_ebay_active(token, query, limit=50)
                cost_jpy = cost_data.get(mod.get_col(row, cost_key)) if cost_key else None
                comp, gate = mod.compare_with_competitors(row, comps, total, cost_jpy)
                # 2026-06-15: TOPセラー Item Specifics 取得・比較は廃止 (catalog決定論生成 → 競合値不使用
                # =catalog-official-only/fail-closed)。市場は価格ゲート(compare_with_competitors)のみ。
            except Exception as e:
                comp, gate = [], None
                print(f"  ⚠️ 行{i+1} 市場検査 skip: {type(e).__name__}")
            all_comp.append(comp); all_gates.append(gate)
            if gate:
                st = gate.get("status")
                out["gate_summary"].append((i + 1, st))
                if st == "NO-GO":
                    out["price_exclude"].append(i + 1)
    # ③ Claude AI 総合レビュー (key 無ければ内部で skip)
    try:
        out["claude"] = mod.claude_review(rows, all_vr, all_comp, all_gates) or ""
    except Exception as e:
        out["claude"] = f"(Claude review skip: {type(e).__name__})"
    return out


def _report(project, csv_path, dry_run, n_rows, exclude_idx, ship_fixes,
            catalog_items, program_items, seo_notes, cat_req, prog_req,
            log_signals, excl_result, gate_summary=None, claude="", degraded=()):
    gate_summary = gate_summary or []
    gc = collections.Counter(st for _, st in gate_summary)
    print("\n" + "=" * 64)
    print(f"📋 CSV監査くん レポート ({project}) {'[DRY-RUN]' if dry_run else ''}")
    print("=" * 64)
    print(f"  対象行: {n_rows}")
    if degraded:
        # ★落ちた事実をレポート本体にも出す (行間のログに埋もれさせない)
        print(f"  ⚠️ AI補強が落ちた走行: {' / '.join(degraded)}")
        print("     → タイトル最適化・絵柄照合・AI総合レビューが効いていない (内容の監査は実施済)")
    print(f"  ✅ 送料ポリシー自動修正: {len(ship_fixes)}件")
    for i, old, new, price in ship_fixes[:10]:
        print(f"     [行{i}] '{old}' → '{new}' (${price})")
    print(f"  ❌ 除外(出品しない): {len(exclude_idx)}件 (行 {exclude_idx[:15]}{'...' if len(exclude_idx) > 15 else ''})")
    if gate_summary:
        print(f"  🏁 市場ゲート: GO {gc.get('GO',0)} / RELAX {gc.get('RELAX',0)} / 保留HOLD {gc.get('HOLD',0)} / ❌NO-GO {gc.get('NO-GO',0)}")
    print(f"  📨 カタログ修正依頼: {len(catalog_items)}件{' → ' + cat_req if cat_req else ''}")
    print(f"  🛠 プログラム修正依頼: {len(program_items)}件{' → ' + prog_req if prog_req else ''}")
    print(f"  💡 SEO改善メモ: {len(seo_notes)}件")
    for sku, msg in seo_notes[:10]:
        print(f"     {sku}: {msg}")
    if claude:
        print("\n  🤖 Claude AI 総合レビュー:")
        for ln in claude.strip().splitlines()[:40]:
            print(f"     {ln}")
    if log_signals:
        print(f"  📄 生成ログ signal: {', '.join(log_signals)}")
    if excl_result:
        print(f"  (excluder: removed={excl_result.get('removed')} backup={excl_result.get('backup_path')})")
    # レポート .md
    if not dry_run:
        os.makedirs(REVIEW_DIR, exist_ok=True)
        rp = os.path.join(REVIEW_DIR, f"csv_auditor_{_today()}_{project}.md")
        with open(rp, "w", encoding="utf-8") as f:
            f.write(f"# CSV監査くん {project} {_today()}\n\n")
            f.write(f"- 対象: {csv_path} / 行 {n_rows}\n")
            f.write(f"- 送料修正 {len(ship_fixes)} / 除外 {len(exclude_idx)} / "
                    f"カタログ依頼 {len(catalog_items)} / プログラム依頼 {len(program_items)} / SEO {len(seo_notes)}\n")
            if gate_summary:
                f.write(f"- 市場ゲート: GO {gc.get('GO',0)} / RELAX {gc.get('RELAX',0)} / HOLD {gc.get('HOLD',0)} / NO-GO {gc.get('NO-GO',0)}\n")
            if claude:
                f.write(f"\n## 🤖 Claude AI 総合レビュー\n\n{claude}\n")
        print(f"\n  レポート: {rp}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="")
    ap.add_argument("--dry-run", action="store_true")
    # 既定で出品時チェックと同等の深い検査(市場ゲート/SEO/Claude AIレビュー)を実行。
    # --quick で機械ルールのみ(API不要・高速)に。
    ap.add_argument("--quick", action="store_true", help="市場ゲート/SEO/Claude を省く(高速)")
    ap.add_argument("--log", default="")
    args = ap.parse_args(argv)
    csv_path = args.csv or find_latest_csv()
    if not csv_path or not os.path.exists(csv_path):
        print("❌ 監査対象CSVが見つかりません (--csv で指定)")
        return 2
    return audit(csv_path, dry_run=args.dry_run, with_market=(not args.quick),
                 log_path=args.log or None)


if __name__ == "__main__":
    sys.exit(main())
