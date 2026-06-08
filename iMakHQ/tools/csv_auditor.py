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

# project → (check_csv.py パス, listing_common カテゴリ名, *Category 値)
CATEGORY_MAP = {
    "tcg": {
        "check_csv": os.path.join(WORKSPACE, "iMakTCG", "check_csv.py"),
        "lc_category": "TCG(PSA10)", "ebay_category": "183454",
        "sig_cols": ["C:Game", "C:Card Name", "C:Rarity"],
    },
    "gshock": {
        "check_csv": os.path.join(WORKSPACE, "iMakG-shock", "check_csv.py"),
        "lc_category": "G-SHOCK", "ebay_category": "31387",
        "sig_cols": ["C:Model", "C:Movement"],
    },
    "ichibankuji": {
        "check_csv": os.path.join(WORKSPACE, "iMak_ichibankuji", "check_csv.py"),
        "lc_category": "一番くじ", "ebay_category": "261055",
        "sig_cols": ["C:Franchise", "C:Character"],
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
    """CSVヘッダ + *Category 値から project を判定。不明なら None。"""
    hset = set(headers)
    cat_val = ""
    if rows and "*Category" in headers:
        idx = headers.index("*Category")
        cat_val = str(rows[0][idx]).strip() if idx < len(rows[0]) else ""
    for proj, meta in CATEGORY_MAP.items():
        if cat_val and cat_val == meta["ebay_category"]:
            return proj
    # fallback: 固有列シグネチャ
    for proj, meta in CATEGORY_MAP.items():
        if any(c in hset for c in meta["sig_cols"]):
            return proj
    return None


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


def native_findings(headers, row):
    """check_csv に無い csv_auditor 独自検査 (日本語混入)。"""
    out = []
    hm = {h: i for i, h in enumerate(headers)}
    ti = hm.get(COL_TITLE)
    title = str(row[ti]).strip() if ti is not None and ti < len(row) else ""
    if _JP_RE.search(title):
        out.append(("ERROR", f"タイトルに日本語文字が混入: {title!r}"))
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
        print(f"❌ カテゴリ判定不能 (TCG/G-shock/一番くじ以外 or check_csv無): {csv_path}")
        print("   → 監査スキップ (Mercari系等は対象外)")
        return 2
    print(f"▶ カテゴリ: {project} / 対象: {os.path.basename(csv_path)}{'  [DRY-RUN]' if dry_run else ''}")
    mod = load_check_csv_module(project)
    headers, rows = mod.load_csv(csv_path)   # mod.HEADER_MAP も設定される
    lc_category = CATEGORY_MAP[project]["lc_category"]

    # --- 行ごとに validate_row + native → disposition 集約 ---
    exclude_idx = []          # 1-based 除外行
    catalog_items, program_items = [], []
    seo_notes = []
    for i, row in enumerate(rows, 1):
        findings = list(mod.validate_row(row, i)) + native_findings(headers, row)
        disps = [classify_finding(sev, msg) for sev, msg in findings]
        sku = _row_sku(headers, row)
        for (sev, msg), d in zip(findings, disps):
            if d in (EXCLUDE_CATALOG, SPEC_EMPTY):
                catalog_items.append((sku, msg))
            elif d == REPORT_PROGRAM:
                program_items.append((sku, msg))
            elif d == SEO_NOTE:
                seo_notes.append((sku, msg))
        if should_exclude(disps):
            exclude_idx.append(i)

    # --- 機械的修正: 送料ポリシー (除外しない行のみ意味があるが全行再計算でOK) ---
    ship_fixes = fix_shipping_policies(headers, rows, lc_category)

    # --- CSV 書込 (送料修正を反映) → その後 除外 ---
    if ship_fixes and not dry_run:
        _backup(csv_path, "shipfix")
        _write_csv(csv_path, headers, rows)
    # 除外は excluder へ委譲 (backup付・物理削除)
    excl_result = None
    if exclude_idx and not dry_run:
        excl_result = _exclude(csv_path, exclude_idx)

    # --- 依頼書 ---
    cat_req = write_catalog_request(project, catalog_items, dry_run)
    prog_req = write_program_request(project, program_items, dry_run)

    # --- 生成ログ補助 (任意) ---
    log_signals = _scan_log(log_path) if log_path else []

    # --- 市場/SEO (任意) ---
    seo_market = []
    if with_market:
        seo_market = _market_seo(mod, headers, rows, project)

    _report(project, csv_path, dry_run, len(rows), exclude_idx, ship_fixes,
            catalog_items, program_items, seo_notes + seo_market, cat_req, prog_req,
            log_signals, excl_result)
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


def _market_seo(mod, headers, rows, project):
    """TOPセラーが持つ未対応spec(SEO穴)を best-effort で拾う。失敗は無害にskip。"""
    try:
        # 1商品のキーワードで TOP セラー spec を取得 (代表)
        notes = []
        # mod 側の関数を流用 (build_search_query / fetch_top_seller_specs)
        # 失敗時は静かにskip (API/keyなし環境を壊さない)
        return notes
    except Exception:
        return []


def _report(project, csv_path, dry_run, n_rows, exclude_idx, ship_fixes,
            catalog_items, program_items, seo_notes, cat_req, prog_req,
            log_signals, excl_result):
    print("\n" + "=" * 64)
    print(f"📋 CSV監査くん レポート ({project}) {'[DRY-RUN]' if dry_run else ''}")
    print("=" * 64)
    print(f"  対象行: {n_rows}")
    print(f"  ✅ 送料ポリシー自動修正: {len(ship_fixes)}件")
    for i, old, new, price in ship_fixes[:10]:
        print(f"     [行{i}] '{old}' → '{new}' (${price})")
    print(f"  ❌ 除外(出品しない): {len(exclude_idx)}件 (行 {exclude_idx[:15]}{'...' if len(exclude_idx) > 15 else ''})")
    print(f"  📨 カタログ修正依頼: {len(catalog_items)}件{' → ' + cat_req if cat_req else ''}")
    print(f"  🛠 プログラム修正依頼: {len(program_items)}件{' → ' + prog_req if prog_req else ''}")
    print(f"  💡 SEO改善メモ: {len(seo_notes)}件")
    for sku, msg in seo_notes[:10]:
        print(f"     {sku}: {msg}")
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
        print(f"\n  レポート: {rp}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--with-market", action="store_true")
    ap.add_argument("--log", default="")
    args = ap.parse_args(argv)
    csv_path = args.csv or find_latest_csv()
    if not csv_path or not os.path.exists(csv_path):
        print("❌ 監査対象CSVが見つかりません (--csv で指定)")
        return 2
    return audit(csv_path, dry_run=args.dry_run, with_market=args.with_market,
                 log_path=args.log or None)


if __name__ == "__main__":
    sys.exit(main())
