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

# project → check_csv.py / listing_commonカテゴリ / *Category値 / 固有列 / 送料自動修正可否
CATEGORY_MAP = {
    "tcg": {
        "check_csv": os.path.join(WORKSPACE, "iMakTCG", "check_csv.py"),
        "lc_category": "TCG(PSA10)", "ebay_categories": ["183454"],
        "sig_cols": ["C:Game", "C:Card Name", "C:Rarity"], "fix_shipping": True,
        "cost_key": "CDA:Certification Number - (ID: 27503)",
        "aspect_json": r"C:/dev/iMak_data/catalog/_input/ebay_tcg_filter_lists_api.json",
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
    out = []
    for col, mode in cols:
        if col == "C:Color" and _is_reel:
            continue
        i = hm.get(col)
        if i is None or i >= len(row):
            continue
        val = str(row[i]).strip()
        if not val:
            continue
        if mode == "first_token":
            tok = val.split()[0] if val.split() else val
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

    _report(project, csv_path, dry_run, len(rows), exclude_idx, ship_fixes,
            catalog_items, program_items, seo_notes, cat_req, prog_req,
            log_signals, excl_result, dc["gate_summary"], dc["claude"])
    # --- PDCA: 台帳に蓄積 + 前回比トレンド + 再発検知 (dry-run は追記しない) ---
    _ledger_report(project, headers, rows, exclude_idx, program_items, seo_notes, dry_run)
    return 1 if (exclude_idx or program_items or catalog_items) else 0


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


def ebay_aspect_findings(headers, rows, project):
    """取得済 eBay公式フィルタ(Aspects)と Item Specifics を照合 = 武器の活用。API不要(offline)。
      ① SELECTION_ONLY の値が許容リスト外 → eBayフィルタ不ヒット (findability欠損)
      ② eBayが required/RECOMMENDED の aspect が「列無し or 全行空」 → SEO機会 (eBay自身が推奨)
    返り: [(sku, msg)] (SEO_NOTE 扱い・報告のみ。CSVは触らない)。"""
    asp = load_aspects(project)
    if not asp:
        return []
    hm = {h: i for i, h in enumerate(headers)}
    notes = []
    # ① RECOMMENDED/required aspect の未充足 (CSV全体で集約=1回)
    for name, a in asp.items():
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
      ② TOPセラー Item Specifics 比較 (fetch_top_seller_specs→compare_item_specifics) = SEO。
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
                if comps:
                    top = mod.fetch_top_seller_specs(token, comps)
                    if top:
                        for sev, msg in mod.compare_item_specifics(row, top):
                            out["seo"].append((_row_sku(headers, row), msg))
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
            log_signals, excl_result, gate_summary=None, claude="" ):
    gate_summary = gate_summary or []
    gc = collections.Counter(st for _, st in gate_summary)
    print("\n" + "=" * 64)
    print(f"📋 CSV監査くん レポート ({project}) {'[DRY-RUN]' if dry_run else ''}")
    print("=" * 64)
    print(f"  対象行: {n_rows}")
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
