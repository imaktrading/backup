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
import os
import re
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
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
    },
    "gshock": {
        "check_csv": os.path.join(WORKSPACE, "iMakG-shock", "check_csv.py"),
        "lc_category": "G-SHOCK", "ebay_categories": ["31387"],
        "sig_cols": ["C:Model", "C:Movement"], "fix_shipping": True, "cost_key": "*Title",
    },
    "ichibankuji": {
        "check_csv": os.path.join(WORKSPACE, "iMak_ichibankuji", "check_csv.py"),
        "lc_category": "一番くじ", "ebay_categories": ["261055"],
        "sig_cols": ["C:Franchise", "C:Character"], "fix_shipping": True, "cost_key": "*Title",
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


def native_findings(headers, row):
    """check_csv に無い csv_auditor 独自検査 (日本語混入)。check_csv 経路で validate_row に上乗せ。"""
    out = []
    hm = {h: i for i, h in enumerate(headers)}
    ti = hm.get(COL_TITLE)
    title = str(row[ti]).strip() if ti is not None and ti < len(row) else ""
    if _JP_RE.search(title):
        out.append(("ERROR", f"タイトルに日本語文字が混入: {title!r}"))
    return out


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
    print(f"▶ カテゴリ: {project}{' (汎用=タイトル安全のみ)' if is_generic else ''} / "
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
    return 1 if (exclude_idx or program_items or catalog_items) else 0


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
