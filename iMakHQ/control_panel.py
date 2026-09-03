#!/usr/bin/env python3
"""iMak Trading Japan 操作パネル
スクリプト直接実行用GUI。Claude仲介不要。

追加方法: SCRIPTS リストに項目を1つ追加するだけ。
"""
import csv
import json          # ★module レベルに無く、`import json as _json` だけだった。
                     #   補URL 残件バッジの `json.loads` が NameError → 握り潰されて
                     #   「(残件 取得できず)」と出続けていた (2026-08-10)。
import os
import re
import sys
import subprocess
import threading
import time
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WORKSPACE = r"c:/dev/iMak"
EBAY_SELLER = "imax-64"
# ★2026-08-21: 鍵の場所は credentials.py が決める (共有領域が本物)。
#   2か所に置いたまま片方だけ更新されると腐るため (カタログ依頼)。
sys.path.insert(0, f"{WORKSPACE}/iMakeBayAPI")
try:
    from credentials import keys_path as _keys_path
    EBAY_KEYS_FILE = _keys_path()
except Exception:                                        # noqa: BLE001
    EBAY_KEYS_FILE = f"{WORKSPACE}/iMakeBayAPI/ebay keys.txt"

# 各 listing run の subprocess stdout を永続化する log dir
# (ListingPanel / KujiWizardDialog から共通利用、ウィザード閉じても残る)
RUN_LOGS_DIR = f"{WORKSPACE}/iMakHQ/run_logs"


def _open_run_log(category):
    """timestamped run log を開く. 呼出側は close() 責任."""
    os.makedirs(RUN_LOGS_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_cat = re.sub(r"[^A-Za-z0-9_\-]", "_", category)[:30]
    log_path = os.path.join(RUN_LOGS_DIR, f"{safe_cat}_{ts}.log")
    return open(log_path, "w", encoding="utf-8"), log_path

# ============ 進捗ダッシュボード: カテゴリ定義 ============
# (ラベル, 検索キーワード, eBayカテゴリID, 目標出品数, 月次追加目標)
# ※ eBay Browse APIは q=* を受け付けないため、カテゴリ特定キーワードで絞る
# カテゴリは スプシR列から自動取得。target/monthly は既知カテゴリは下記から、未知は DEFAULT_TARGETS を適用
# 新カテゴリをスプシに追加 → ダッシュボードに自動表示（コード修正不要）
DEFAULT_TARGETS = (50, 10)  # (全期間目標, 月次目標) 未知カテゴリ用

CATEGORY_TARGETS = {
    # ラベル(スプシR列値): (全期間目標, 月次目標)
    "Tシャツ":              (250, 50),
    "G-shock":              (350, 30),
    "TCG":                  (150, 40),
    "アウトドア・ジャケット": (80, 15),
    "バッグ":               (60, 10),
    "一番くじ":              (120, 20),
    "tomica":               (50, 10),
    "カプセルトイ":          (100, 20),
    "フィギュア":            (200, 30),
    "グッズ":               (150, 25),
    "スニーカー":            (50, 10),
    "ヴィンテージ":          (30, 5),
    "ゴルフ":               (20, 5),
    "リール":               (15, 3),
    "その他":               (10, 2),
}

# ============ 統合High/Lowスプシ から進捗集計 ============
# 統合シート構造: A=URL, B=ItemID, D=売り切れ, R=カテゴリ, U=追加日(YYYY-MM-DD)
CONSOLIDATED_SHEETS = {
    "hight": ("19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk", 851100680),  # 統合Hight
    "low":   ("1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0", 851100680),  # 統合Low
}
# ★公式在庫要チェック シート1 (UT/Montbell/GU 等の公式在庫listing。統合と別管理→現在数に合算)
#   構造: col1=title, col2=item ID, col5=仕入元URL。カテゴリは URL ドメインで判定。
OFFICIAL_STOCK_SHEET_ID = "101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0"
# SHEET_CATEGORY_MAP は廃止（自動取得に変更）
GSHEET_CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"


def _official_stock_category(url):
    """公式在庫シートの仕入元URLから dashboard カテゴリを推定。"""
    u = (url or "").lower()
    if "montbell" in u:
        return "アウトドア・ジャケット"
    if "uniqlo" in u or "gu-global" in u or "gu.com" in u:
        return "Tシャツ"
    return "その他"

# ============================================================================
def summarize_audit_log(log: str) -> str:
    """CSV監査くんの stdout から要点を抽出して短いサマリー文字列を返す (純関数・test可)。

    出品くんが監査完走時にポップアップ表示する用 (対話セッションは外部から起こせないため、
    結果報告を GUI 側で能動的に行う。2026-06-29)。抽出できなければ空文字。
    """
    if not log:
        return ""
    import re as _re
    lines = []

    def _find(pat):
        m = _re.search(pat, log)
        return m.group(1) if m else None

    up = _find(r"CSV UPシグナル[^\n]*?(\d+)\s*件\s*入稿OK")
    if up is not None:
        lines.append(f"🟢 入稿OK: {up}件 → UPして")
    excl = _find(r"除外\(出品しない\):\s*(\d+)\s*件")
    if excl and excl != "0":
        lines.append(f"❌ 出品除外: {excl}件 (CSVから物理除外済)")
    # 重複除外は「捨てた」のでなく「弾いた2枚目の仕入元を primary の補URLに移した」= 供給を厚くした
    # (hoju_url_from_dupes)。除外件数だけ報告すると機会損失に見えるので、補URL 追加とセットで出す。
    dup = _find(r"removed \(真の重複[^\n]*?\):\s*(\d+)")
    hoju_n = _re.search(r"追加対象primary\s*\d+\s*行\s*/\s*追加URL\s*(\d+)", log)
    if dup and dup != "0":
        if hoju_n and hoju_n.group(1) != "0":
            lines.append(f"♻ 重複除外 {dup}件 → 補URL {hoju_n.group(1)}本 追加 (供給を厚くした)")
        else:
            lines.append(f"♻ 重複除外 {dup}件 (補URL 追加なし=既存収載 or 満杯)")
    nogo = _find(r"❌NO-GO\s*(\d+)")
    if nogo and nogo != "0":
        lines.append(f"🚫 市場NO-GO: {nogo}件 (入稿前に要確認)")
    cat = _find(r"カタログ修正依頼:\s*(\d+)\s*件")
    if cat and cat != "0":
        lines.append(f"📨 catalog依頼: {cat}件 (自動投入済)")
    prog = _find(r"プログラム修正依頼:\s*(\d+)\s*件")
    if prog and prog != "0":
        lines.append(f"🛠 program修正NG: {prog}件")
    backlog = _find(r"未対応 program修正 backlog\s*(\d+)\s*件")
    if backlog and backlog != "0":
        lines.append(f"🛠 program backlog: {backlog}件 (実装=HQ・要対応)")
    recur = _find(r"再発finding[^\n]*?(\d+)\s*件")
    if recur and recur != "0":
        lines.append(f"🔁 再発: {recur}件 (catalog scope外中心・既知)")
    if not lines:
        return ""
    return "\n".join(lines)


# catalog DB (drop原因分類の照会先・read-only)
CATALOG_DB_PATH = r"C:/dev/iMak_data/catalog/products.sqlite"


def build_problem_report(log: str, catalog_db_path: str = CATALOG_DB_PATH) -> str:
    """生成+監査ログ → 統合「問題提起」テキスト (純関数寄り・catalog照会のみI/O)。

    ユーザー方針(2026-06-30): 毎回の生成+監査後に、**CSV化分・非化分の両方**について
    「原因→対策案」を自動で問題提起する(判断は人)。これが目的=PDCAのCheck→Act提起。
      - CSV化分の問題: 監査findings(入稿可否/catalog依頼/program backlog/再発) = summarize_audit_log
      - CSV非化分:     drop_classifier で原因分類(収録漏れ/scope外/promo衝突/目視未確定)+対策案
    """
    parts = []
    audit = summarize_audit_log(log)
    if audit:
        parts.append("【CSV化分の問題(監査)】\n" + audit)
    try:
        import sys as _sys
        _here = os.path.dirname(os.path.abspath(__file__))
        _tools = os.path.join(_here, "tools")
        for _p in (_here, _tools):
            if _p not in _sys.path:
                _sys.path.insert(0, _p)
        import drop_classifier as _dc
        se, ce = _dc.make_catalog_lookups(catalog_db_path)
        # 生成 CSV 本文を渡すと drop 集合を「処理cert − CSV cert」の差分で確定できる
        # (2026-08-01: 分類ルールの足し忘れで毎回 ⚠️件数不一致 が出ていたのの根本対策)。
        _csv_text = None
        try:
            _csv_p = _dc.csv_path_from_log(log)
            if _csv_p and os.path.isfile(_csv_p):
                with open(_csv_p, "r", encoding="utf-8", errors="replace") as _f:
                    _csv_text = _f.read()
        except Exception:
            _csv_text = None   # 読めなければ従来のパターン方式にフォールバック
        # 生成後に落ちた分は走行ログに出ない (ログが閉じた後の処理)。CSV 並置の記録を読む。
        _extra = {}
        try:
            import json as _json
            with open(_csv_p + ".excluded.json", encoding="utf-8") as _f:
                _extra = _dc.post_drop_reasons(_json.load(_f))
        except Exception:
            _extra = {}
        _drops = _dc.classify_drops(log, set_exists=se, card_exists=ce,
                                    csv_text=_csv_text, extra=_extra)
        rep = _dc.render_problem_report(_drops)
        if rep:
            parts.append(rep)
        recon = _dc.reconcile_counts(log, _drops, csv_text=_csv_text)   # 件数照合(silent drop検出)
        if recon:
            parts.append(recon)
    except Exception as _e:
        parts.append(f"⚠ drop原因分類 失敗(非致命): {type(_e).__name__}: {_e}")
    return "\n\n".join(parts)


# csv_postprocess_excluder helper (check_csv NO-GO 行を CSV から物理除外)
# 2026-04-28 追加: dual_gate_disagreement.md CRITICAL 問題の応急対処.
# psa_to_csv ↔ check_csv の市場ゲート判定矛盾で、check_csv が「除外済」表示しても
# 物理除外されない bug の補正. SSOT 化 (Phase C) までの安全弁.
# ============================================================================
def _run_excluder_for_latest_csv(append_log_func, captured_stdout: str):
    """check_csv の stdout text から NO-GO 行を抽出 → 最新 CSV から物理除外.

    Args:
        append_log_func: panel 固有のログ追記関数
        captured_stdout: subprocess の stdout 全体 (check_csv の出力含む)
    """
    try:
        if not captured_stdout or "NO-GO" not in captured_stdout:
            return  # NO-GO 検出なし、何もしない
        csv_dir = os.path.join(WORKSPACE, "iMakHQ", "csv_output")
        if not os.path.isdir(csv_dir):
            return
        csvs = [
            os.path.join(csv_dir, f)
            for f in os.listdir(csv_dir)
            if f.endswith(".csv") and not f.endswith("_cost.json")
        ]
        if not csvs:
            return
        latest_csv = max(csvs, key=os.path.getmtime)
        excluder_dir = os.path.join(WORKSPACE, "iMakeBayAPI", "csv_postprocess")
        if excluder_dir not in sys.path:
            sys.path.insert(0, excluder_dir)
        from excluder import exclude_from_check_csv_stdout, render_report
        result = exclude_from_check_csv_stdout(latest_csv, captured_stdout)
        # 2026-06-20 価格NO-GO廃止: 高め(旧NO-GO)は除外せず出品 + 既存メンテ追跡。記録のみ。
        if result.get("high_count", 0) > 0:
            append_log_func("\n" + "=" * 70 + "\n▶ 価格高め記録 (除外せず出品・既存メンテ追跡)\n" + "=" * 70 + "\n")
            append_log_func(render_report(result) + "\n")
    except Exception as e:
        append_log_func(f"\n⚠️ excluder 実行失敗: {type(e).__name__}: {e}\n")
        # 失敗しても入稿準備には影響なし (人手確認の保険あり)


# ============================================================================
# rarara helper (CSV outlier 検出を listing script 完了後に自動実行)
# 2026-04-28 追加: ListingPanel / KujiWizardDialog / 他 panel の subprocess 完了 hook
# から共通利用. 本体 listing script は無変更. orchestrator 側の 1 step 追加.
# ロールバック: この関数 + 各 panel の呼出 1 行 をコメントアウトで完全復元.
# ============================================================================
def _run_rarara_for_latest_csv(append_log_func, since_ts=None):
    """csv_output/ の最新 CSV に対して rarara を実行.

    Args:
        append_log_func: panel 固有のログ追記関数 (self.append_log 等)
        since_ts: listing script 起動時刻 (time.time()). 指定時、最新 CSV の
                  mtime が since_ts より古い (= 今回 listing で出力されていない)
                  場合は skip. 古い CSV を誤って表示するのを防ぐ (2026-05-05).
    """
    try:
        csv_dir = os.path.join(WORKSPACE, "iMakHQ", "csv_output")
        if not os.path.isdir(csv_dir):
            return
        csvs = [
            os.path.join(csv_dir, f)
            for f in os.listdir(csv_dir)
            if f.endswith(".csv") and not f.endswith("_cost.json")
        ]
        if not csvs:
            return
        latest_csv = max(csvs, key=os.path.getmtime)
        # 今回 listing で新規 CSV が出力されていない (= listing 失敗 or 入力ゼロ) なら skip
        if since_ts is not None and os.path.getmtime(latest_csv) < since_ts:
            append_log_func("\n⚠️ rarara: 今回 listing で新規 CSV 出力なし → skip\n")
            return
        rarara_path = os.path.join(WORKSPACE, "iMakeBayAPI", "rarara", "rarara.py")
        if not os.path.exists(rarara_path):
            return
        append_log_func("\n" + "=" * 70 + "\n▶ rarara (CSV outlier 検出)\n" + "=" * 70 + "\n")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        r = subprocess.run(
            [sys.executable, rarara_path, latest_csv],
            env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            creationflags=creationflags, timeout=60,
        )
        append_log_func(r.stdout or "")
        if r.stderr:
            append_log_func(r.stderr)
    except Exception as e:
        append_log_func(f"\n⚠️ rarara 実行失敗: {type(e).__name__}: {e}\n")
        # 失敗しても listing 出力には影響なし


# ============================================================================
# 重複くん dedupe_excluder helper (2026-05-27 追加)
# 入稿前 CSV に対して (KEY1, KEY2) tuple 突合 + 真の重複行を物理除外.
# - 既存 HIGH/LOW/公式 スプシの AI/AJ 列 (KEY1/KEY2) と突合
# - variant 違い (= 通常版 vs Alt Art) は別商品扱いで残存 = false positive ゼロ
# - 出品くん本体 (= psa_to_csv 等) 触らず、 chain 末尾 hook 追加で完結
# ロールバック: この関数 + poll_queue 内呼出 1 行 をコメントアウトで完全復元.
# ============================================================================
DEDUPE_WORKTREE = r"C:\dev\iMak_dedupe\iMakDedupe"


# ============================================================================
# live重複除外 cert への KEY 書込 (浪費ループ対策・2026-07-18)
# ----------------------------------------------------------------------------
# 症状: 同一カードが既に live 出品済(例 Bloodmoon Ursaluna SV5a-091)だと、その2枚目の
#   cert 行はスプシで KEY 空のまま抽出される → 生成 → Step 4a(check-csv)が「live重複」として
#   物理除外 → KEY書込(4b)は deduped CSV を見るので cert に KEY が付かない → 次回also抽出。
#   結果、1回10件の franchise 枠を毎回1つ浪費(2026-07-16/17 で Bloodmoon が連続空振り)。
# 対策: 4a が消した cert にも KEY を書く。除外理由=live重複=出品済の兄弟がいる → KEY を書いても
#   orphan掃除(psa_orphan_key_clean: listed兄弟が無い時のみ消す)に消されない=安全。
# 重要な境界: intra-CSV間引き(4a-2)で消える分は兄弟が未出品なので KEY を書くと orphan 化する。
#   ∴ 対象は **4a(check-csv)が消した分のみ**。4a-2 の前に diff を取って切り分ける。
# ============================================================================
def _row_label(header, row):
    """CSV 行の一意ラベル(CustomLabel=PSA cert-sku)。純関数。"""
    try:
        i = header.index("CustomLabel")
    except ValueError:
        i = 0
    return row[i].strip() if i < len(row) else ""


def _read_csv_rows(path):
    """CSV を (data_rows, header) に読む。純関数(I/Oのみ)。"""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return (rows[1:], rows[0]) if rows else ([], [])


def _livedup_removed_rows(pre_rows, pre_header, post_rows, post_header):
    """4a(live重複除外)で消えた行を返す(純関数・CustomLabel で突合・test可)。"""
    post_labels = {_row_label(post_header, r) for r in post_rows}
    return [r for r in pre_rows if _row_label(pre_header, r) not in post_labels]


# 入稿CSVの cert 列 (drop の記録は cert を鍵にする = メールも監査も同じ物を数える)
CSV_CERT_COL = "CDA:Certification Number - (ID: 27503)"


def _row_cert(header, row):
    """行の cert (無ければ空)。純関数。"""
    i = header.index(CSV_CERT_COL) if CSV_CERT_COL in header else -1
    return (row[i].strip() if 0 <= i < len(row) else "")


def build_post_drops(pre_header, livedup_rows, mid_header, intra_rows):
    """生成後に落ちた行 → [{cert, title, reason}] (純関数・test可)。

    ★2026-08-19: 生成後の間引きは **どこにも記録されず** メールにも監査にも出なかった。
      8/19 は CSV内に同じカードが2枚入って1枚を落としたが、その1件だけ行方不明になり
      「処理20 = 出品12 + 落ち7」と数が合わなくなった (ユーザー指摘)。落ちたら必ず記録する。
    """
    return (drop_records(pre_header, livedup_rows, "live-dup")
            + drop_records(mid_header, intra_rows, "intra-dup"))


def drop_records(header, rows, reason):
    """落ちた行 → [{cert, title, reason}] (純関数)。"""
    ti = header.index("*Title") if "*Title" in (header or []) else -1
    return [{"cert": _row_cert(header, r),
             "title": (r[ti].strip() if 0 <= ti < len(r) else ""),
             "reason": reason} for r in (rows or [])]


def _write_post_drops(append_log_func, latest_csv, drops, **extra):
    """生成後 drop を CSV 並置の `<csv>.excluded.json` に **追記** する (失敗許容)。

    工程ごと (重複除外 / 売り切れ除外 …) に呼ばれるので、前の工程の記録を消さない。
    """
    import json as _json
    from datetime import datetime as _dt
    f_path = latest_csv + ".excluded.json"
    try:
        with open(f_path, encoding="utf-8") as f:
            prev = _json.load(f)
    except Exception:                                          # noqa: BLE001
        prev = {}
    try:
        drops = (prev.get("drops") or []) + list(drops or [])
        rec = dict(prev)
        rec.update(extra)
        rec.update({"at": _dt.now().isoformat(timespec="seconds"),
                    "csv": os.path.basename(latest_csv), "drops": drops})
        with open(f_path, "w", encoding="utf-8") as f:
            _json.dump(rec, f, ensure_ascii=False, indent=1)
        n = {}
        for d in drops:
            n[d["reason"]] = n.get(d["reason"], 0) + 1
        append_log_func(f"\n  📝 生成後に落ちた分を記録: {n or '0件'}\n")
    except Exception as e:                                     # noqa: BLE001
        append_log_func(f"\n(生成後 drop の記録に失敗: {type(e).__name__})\n")


def _write_keys_for_livedup_removed(append_log_func, latest_csv, pre_rows, pre_header, env):
    """4a が live重複として消した cert に KEY を書く(浪費ループ対策)。write-only・失敗許容。"""
    if not pre_rows:
        return
    try:
        post_rows, post_header = _read_csv_rows(latest_csv)
    except Exception as e:
        append_log_func(f"\n(live重複KEY書込: 事後読込失敗 skip: {type(e).__name__})\n")
        return
    removed = _livedup_removed_rows(pre_rows, pre_header, post_rows, post_header)
    if not removed:
        return
    append_log_func("\n======================================================================\n")
    append_log_func(f"▶ live重複除外 cert に KEY 書込 (浪費ループ対策・{len(removed)}件)\n")
    append_log_func("======================================================================\n")
    tmp = latest_csv + ".livedup_removed.csv"
    try:
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            w.writerow(pre_header)
            w.writerows(removed)
        r = subprocess.run(
            [sys.executable, "-m", "dedupe.checker", "--write-keys-from-csv", tmp],
            cwd=DEDUPE_WORKTREE, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180, env=env)
        if r.stdout:
            append_log_func(r.stdout)
        if r.returncode != 0:
            append_log_func(f"\n⚠️ live重複KEY書込 returncode={r.returncode}(続行)\n")
    except Exception as e:
        append_log_func(f"\n⚠️ live重複KEY書込 失敗(続行): {type(e).__name__}: {e}\n")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _run_dedupe_for_latest_csv(append_log_func, since_ts=None):
    """csv_output/ の最新 CSV に対して 重複くん --check-csv を実行 (= 物理除外)."""
    csv_dir = os.path.join(WORKSPACE, "iMakHQ", "csv_output")
    try:
        csv_files = [
            f for f in os.listdir(csv_dir)
            if f.endswith(".csv") and not (".bak" in f) and not f.endswith("_cost.json")
        ]
        if not csv_files:
            return
        csv_files_with_mtime = [
            (f, os.path.getmtime(os.path.join(csv_dir, f))) for f in csv_files
        ]
        csv_files_with_mtime.sort(key=lambda x: x[1], reverse=True)
        latest_csv = os.path.join(csv_dir, csv_files_with_mtime[0][0])
        if since_ts is not None and csv_files_with_mtime[0][1] < since_ts:
            return  # listing script 起動前の古い CSV は skip
    except Exception as e:
        append_log_func(f"\n⚠️ dedupe hook CSV 探索失敗: {type(e).__name__}: {e}\n")
        return

    # Mercari 系(porter/montbell/tshirt/reel)は1点もの = catalog canonical KEY を持たない。
    # KEY-based dedupe では全件「解決不能」となり destructive に全除外される
    # (2026-06-16 Porter 10件全消し事故)。catalog-keyed (tcg/gshock/ichibankuji) のみ dedupe 実行。
    # 「判定不能は破壊的動作に倒さない」(failclosed_must_skip) に従い Mercari 系は skip。
    _base = os.path.basename(latest_csv).lower()
    if any(_base.startswith(p) for p in ("porter_", "montbell_", "tshirt_", "reel_", "mercari")):
        append_log_func(
            f"\n(重複くん: {os.path.basename(latest_csv)} は1点もの(catalog KEY無)"
            f" → KEY-based dedupe skip)\n"
        )
        return

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    # 浪費ループ対策(2026-07-18): Step 4a が消す前に CSV 全行を控える(4a diff 用)。
    try:
        _pre_rows, _pre_header = _read_csv_rows(latest_csv)
    except Exception as _e_pre:
        _pre_rows, _pre_header = [], []
        append_log_func(f"\n(live重複KEY書込: 事前読込失敗 skip: {type(_e_pre).__name__})\n")

    # Step 4-pre: live cache の新鮮さを **除外の前に** 保証する (2026-08-09)。
    # 重複くん excluder は cache が 6h より古いと「[FATAL] 判定不能 → CSV 触らず入稿停止」で
    # 除外を丸ごと skip する。cache を取り直す担当が後段の dup_guard しか居なかったため、
    # 「excluder は素通り → 重複は後段が拾えた時だけ消える」順序になっていた
    # (2026-08-09 実測: age=23.7h で excluder skip、重複2件は dup_guard が辛うじて物理除外)。
    append_log_func("\n======================================================================\n")
    append_log_func("▶ live cache の鮮度確保 (除外の前に = excluder を素通りさせない)\n")
    append_log_func("======================================================================\n")
    try:
        _dgp = os.path.join(WORKSPACE, "iMakHQ", "tools", "dup_guard.py")
        r = subprocess.run([sys.executable, _dgp, "--refresh-cache"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300, env=env)
        if r.stdout:
            append_log_func(r.stdout)
        if r.returncode != 0:
            append_log_func(
                "\n⚠️ live cache を取り直せなかった → この後の重複除外は判定不能で skip される\n"
                "   (入稿前に重複が残っていないか目視確認すること)\n")
            if r.stderr:
                append_log_func(r.stderr)
    except Exception as e:
        append_log_func(f"\n⚠️ live cache 鮮度確保 失敗(続行): {type(e).__name__}: {e}\n")

    # Step 4a: 物理除外 (= Phase 1g、 真の重複 row を CSV から削除)
    append_log_func("\n======================================================================\n")
    append_log_func("▶ 重複くん dedupe_excluder ((KEY1, KEY2) tuple 物理除外)\n")
    append_log_func("======================================================================\n")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "dedupe.checker", "--check-csv", latest_csv],
            cwd=DEDUPE_WORKTREE,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, env=env,
        )
        if r.stdout:
            append_log_func(r.stdout)
        if r.returncode != 0:
            append_log_func(f"\n⚠️ dedupe excluder returncode={r.returncode}\n")
            if r.stderr:
                append_log_func(r.stderr)
    except Exception as e:
        append_log_func(f"\n⚠️ dedupe hook (check-csv) 失敗: {type(e).__name__}: {e}\n")

    # Step 4a-diff: 4a(live重複)で消えた cert に KEY を書く(浪費ループ対策)。
    # 必ず 4a-2(intra間引き)の**前**に実行 = 4a が消した分だけを対象化(4a-2 分は兄弟未出品で対象外)。
    _write_keys_for_livedup_removed(append_log_func, latest_csv, _pre_rows, _pre_header, env)

    # ★2026-08-19: 生成後に落ちた行を cert 単位で記録する。ここを記録しないと
    #   メール(内訳)も監査(問題提起)も 4a/4a-2 の間引きを数えられず、毎回 件数が合わない。
    try:
        _mid_rows, _mid_header = _read_csv_rows(latest_csv)
        _livedup = (_livedup_removed_rows(_pre_rows, _pre_header, _mid_rows, _mid_header)
                    if _pre_rows else [])
    except Exception as _e:
        append_log_func(f"(live重複の記録: 読込失敗 {type(_e).__name__})\n")
        _mid_rows, _mid_header, _livedup = [], [], []

    # Step 4a-2: CSV内 同design重複の間引き (2026-06-21)。重複くんは「既出品」としか照合せず
    # 同一CSV内の同design複数コピー(別cert)を間引かない → 同じカードが複数枚出る。ここで
    # (Game,Set,番号)が同一の行を1枚に絞る。KEY書込(4b)の前なので間引いた分は orphan にならない。
    append_log_func("\n======================================================================\n")
    append_log_func("▶ CSV内 同design重複の間引き (同じカードは1枚のみ出品)\n")
    append_log_func("======================================================================\n")
    try:
        idd = os.path.join(WORKSPACE, "iMakHQ", "tools", "tcg_intra_csv_dedup.py")
        r = subprocess.run([sys.executable, idd, latest_csv, "--execute"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, env=env)
        if r.stdout:
            append_log_func(r.stdout)
        if r.returncode != 0:
            append_log_func(f"\n⚠️ 同design間引き returncode={r.returncode}(続行)\n")
    except Exception as e:
        append_log_func(f"\n⚠️ 同design間引き 失敗(続行): {type(e).__name__}: {e}\n")

    try:
        _post_rows, _post_header = _read_csv_rows(latest_csv)
        _intra = (_livedup_removed_rows(_mid_rows, _mid_header, _post_rows, _post_header)
                  if _mid_rows else [])
    except Exception as _e:
        append_log_func(f"(CSV内重複の記録: 読込失敗 {type(_e).__name__})\n")
        _intra = []
    _write_post_drops(append_log_func, latest_csv,
                      build_post_drops(_pre_header, _livedup, _mid_header, _intra))

    # Step 4b: 入稿前 KEY 事前書込 (= Phase 1h、 HIGH I 列 cert 経由で AI/AJ 列補完)
    append_log_func("\n======================================================================\n")
    append_log_func("▶ 重複くん write-keys-from-csv (HIGH I 列 cert 経由で KEY 事前書込)\n")
    append_log_func("======================================================================\n")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "dedupe.checker", "--write-keys-from-csv", latest_csv],
            cwd=DEDUPE_WORKTREE,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, env=env,
        )
        if r.stdout:
            append_log_func(r.stdout)
        if r.returncode != 0:
            append_log_func(f"\n⚠️ dedupe write-keys returncode={r.returncode}\n")
            if r.stderr:
                append_log_func(r.stderr)
    except Exception as e:
        append_log_func(f"\n⚠️ dedupe hook (write-keys) 失敗: {type(e).__name__}: {e}\n")
        # 失敗しても listing 出力には影響なし

    # Step 4b-2: KEY 補完の取りこぼし救済 + 入稿前 重複ガード (2026-07-26)
    # - write-keys が skipped_no_resolution にする種別(DON!! カード等)は KEY が空のまま出品され、
    #   重複くんの母集団から外れて **同一カード2枠 live** を生む(ガンダム RP-028 実例)。
    #   → タイトルの #ID が catalog に完全一致する時だけ KEY を書く(ID-strict・推測なし)。
    # - その上で「同じカードが既に live」を検出して警告する。**出品は止めない**
    #   (仕入元が別なら健全。致命は「同じ仕入元URLを2出品が指す」方で、それは audit が見る)。
    append_log_func("\n======================================================================\n")
    append_log_func("▶ dup_guard (KEY補完の取りこぼし救済 + 入稿前 同一カード検出)\n")
    append_log_func("======================================================================\n")
    # --audit --no-refresh = シートだけで完結(eBay API を叩かないので即時)。致命側である
    # 「同じ仕入元URLを2出品が指す」を **毎サイクル** 0件であることの証跡にする。
    for _mode in (["--fill-keys", latest_csv], ["--pre-upload", latest_csv],
                  ["--audit", "--no-refresh"]):
        try:
            _dgp = os.path.join(WORKSPACE, "iMakHQ", "tools", "dup_guard.py")
            r = subprocess.run([sys.executable, _dgp] + _mode,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180, env=env)
            if r.stdout:
                append_log_func(r.stdout)
            if r.returncode != 0:
                append_log_func(f"\n⚠️ dup_guard {_mode[0]} returncode={r.returncode}(続行)\n")
                if r.stderr:
                    append_log_func(r.stderr)
        except Exception as e:
            append_log_func(f"\n⚠️ dup_guard {_mode[0]} 失敗(続行): {type(e).__name__}: {e}\n")

    # Step 4c: 補URL 自動追記 (2026-07-13)。write-keys で HIGHT に KEー書込済の直後に実行。
    # 重複くんが弾いた「同KEー既出品の2枚目」の A列URL(実在の別個体=vetted supply)を、同KEー
    # 出品中primary の 補URL(AC-AG)に **既存保持+冪等** で追加(= primary が売れたら再ソースする
    # backup 供給源)。read-merge-write なので既存(SNKRDUNK/Mercari由来)は消さない。
    append_log_func("\n======================================================================\n")
    append_log_func("▶ 補URL 自動追記 (弾いた2枚目URL → 出品中primaryの補URL・既存保持+冪等)\n")
    append_log_func("======================================================================\n")
    try:
        hoju = os.path.join(WORKSPACE, "iMakHQ", "tools", "hoju_url_from_dupes.py")
        r = subprocess.run(
            [sys.executable, hoju, "--write"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, env=env,
        )
        if r.stdout:
            append_log_func(r.stdout)
        if r.returncode != 0:
            append_log_func(f"\n⚠️ 補URL 追記 returncode={r.returncode}(続行)\n")
            if r.stderr:
                append_log_func(r.stderr)
    except Exception as e:
        append_log_func(f"\n⚠️ 補URL 追記 失敗(続行): {type(e).__name__}: {e}\n")
        # 失敗しても listing 出力には影響なし

    # Step 4s (sold): 仕入元が売り切れた行を CSV から落とす (2026-08-17)。
    # 人が入稿前に手でやっていた「HIGHT で売り切れを確認 → 売り切れは出品しない」の自動化。
    # 売り切れた現物を出すと仕入れられず、キャンセル = Defect Rate 直行。
    # 根拠はシートの売り切れ欄 (監視くんの巡回結果)。**出品後**の売り切れは監視くんの担当なので
    # ここでは触らない。CSV を変える最後の step にしてある (監査くんは後段でこの CSV を見る)。
    append_log_func("\n======================================================================\n")
    append_log_func("▶ 仕入元が売り切れた行を除外 (入稿前チェック)\n")
    append_log_func("======================================================================\n")
    # ★2026-08-19: ここは timeout=180 だった。中で呼ぶ在庫チェックCLI (ブラウザを1件ずつ
    #   開く) は自前で 900秒 待っていたので、**外側が先に殺す** = 売り切れ除外が毎回
    #   まるごと走らない状態だった (8/19 実測 TimeoutExpired)。シートの巡回結果による
    #   除外まで一緒に消えるのが実害。内側を 300秒 上限にしたので、外はその分 + シート読み。
    _sold_ok, _sold_why = False, ""
    _pre_sold, _pre_sold_h = [], []
    try:
        _pre_sold, _pre_sold_h = _read_csv_rows(latest_csv)
    except Exception:                                          # noqa: BLE001
        pass
    try:
        drop = os.path.join(WORKSPACE, "iMakHQ", "tools", "csv_drop_sold_rows.py")
        r = subprocess.run(
            [sys.executable, drop, latest_csv, "--write"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=420, env=env,
        )
        if r.stdout:
            append_log_func(r.stdout)
        _sold_ok = r.returncode == 0
        if not _sold_ok:
            _sold_why = "returncode=%s" % r.returncode
            append_log_func("\n⚠️ 売り切れ除外 returncode=%s(続行)\n" % r.returncode)
            if r.stderr:
                append_log_func(r.stderr)
    except Exception as e:
        _sold_why = type(e).__name__
        append_log_func(
            "\n🚨 **売り切れ除外が走っていません** (続行するが要確認): %s: %s\n"
            "   仕入元が売り切れた行が入稿CSVに残る = キャンセル risk。"
            "入稿前に目視で確認すること\n" % (type(e).__name__, e))
    try:
        _post_sold, _post_sold_h = _read_csv_rows(latest_csv)
        _sold_rows = (_livedup_removed_rows(_pre_sold, _pre_sold_h, _post_sold, _post_sold_h)
                      if _pre_sold else [])
    except Exception:                                          # noqa: BLE001
        _sold_rows = []
    _write_post_drops(append_log_func, latest_csv,
                      drop_records(_pre_sold_h, _sold_rows, "sold-out"),
                      soldcheck=("ok" if _sold_ok else (_sold_why or "failed")))

    # Step 4e: 「出せるか」(AP列) の塗り直し (2026-08-17)。
    # ★4d は欠番。2026-07-28 に撤去した「補URL候補検索の自動実行」がその名前で、
    #   復活していないことを test_control_panel_hoju_search_hook_20260728 が
    #   **その文字列の不在**で見張っているため、コメントにも書かない。
    # ユーザーは **itemID 欄が空か** で候補を見て「補充はまだ要らない」と判断する。
    # 出品した直後は「今出したカードの2枚目」がまだ白いので、判定が古いままだと
    # また見間違える。夜間バッチでも更新するが、出した直後にも合わせる。
    # 補URL 追記の **後** に置くこと (登録済かどうかで色が変わるため)。
    append_log_func("\n======================================================================\n")
    append_log_func("▶ 「出せるか」の塗り直し (itemID 欄の白/グレー = 出せる/出せない)\n")
    append_log_func("======================================================================\n")
    try:
        flag = os.path.join(WORKSPACE, "iMakHQ", "tools", "sheet_listable_flag.py")
        r = subprocess.run(
            [sys.executable, flag, "--write"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, env=env,
        )
        if r.stdout:
            append_log_func(r.stdout)
        if r.returncode != 0:
            append_log_func(f"\n⚠️ 出せるか判定 returncode={r.returncode}(続行)\n")
            if r.stderr:
                append_log_func(r.stderr)
    except Exception as e:
        append_log_func(f"\n⚠️ 出せるか判定 失敗(続行): {type(e).__name__}: {e}\n")
        # 表示のための塗り直しなので、失敗しても listing 出力には影響なし


def unlisted_from_result(result, started_ts=None, file_mtime=None):
    """出品結果 JSON → 出せずに残った行の list (純関数・test 可)。

    ★2026-08-23: 走行の締めは出品の成否を見ておらず、9件中2件しか出ていない走行でも
      「🎉 全 process 完了 — 入稿準備 OK」と出していた。ここで拾って締めを変える。
    検証のみ (write=False) の走行は出品していないので対象外。
    前回の走行が残した JSON を今回の結果と読み違えないよう、走行開始より古い
    ファイルは無視する。
    """
    if not isinstance(result, dict) or not result.get("write"):
        return []
    if started_ts and file_mtime and file_mtime < started_ts:
        return []
    return [str(x) for x in (result.get("unlisted") or []) if str(x).strip()]


def _run_auto_full_tail(append_log_func, env):
    """🤖PSA自動 の締め: 前回入稿分の後始末 → CSV監査くん (2026-08-18)。

    人が毎回やっていた手順のうち、機械にできる分をこの1押しに畳む。
    ① itemID をスプシに書込   ② 新規分を広告8%に   ③ CSV監査くん

    ①② が **今回の CSV でなく前回入稿分に効く**のは意図どおり。itemID は入稿しないと
    発行されないので、今回生成した分にはまだ付いていない。どちらも冪等なので、
    毎回押せば「入稿済なのに書き戻していない/広告に入っていない」分が必ず片付く。
    (itemID が無い行は監視くんが取り下げられない = 売り切れても売れる状態で残るため、
     放置が一番危ない)
    ③ は最後。①②はシートと広告しか触らないので CSV の監査結果に影響しない。
    """
    tools = os.path.join(WORKSPACE, "iMakHQ", "tools")
    csv_dir = os.path.join(WORKSPACE, "iMakHQ", "csv_output")
    latest = ""
    try:
        cands = [os.path.join(csv_dir, f) for f in os.listdir(csv_dir)
                 if f.startswith("tcg_upload_") and f.endswith(".csv")]
        latest = max(cands, key=os.path.getmtime) if cands else ""
    except Exception:
        latest = ""
    result_json = os.path.join(csv_dir, "last_upload_result.json")
    # ★前回の結果を先に消す。残っていると、今回の入稿が結果を残さずに終わった時に
    #   **前回の出品を今回の結果としてメールしてしまう** (古い成功で失敗が隠れる)。
    try:
        os.remove(result_json)
    except OSError:
        pass
    steps = [
        # ★順番が意味を持つ: 監査 → 入稿 → 書戻し → 広告 → メール。
        #   監査は **入稿前の関所**なので必ず先。itemID は入稿しないと出ないので書戻しは後。
        ("CSV監査くん (入稿前チェック)", [sys.executable, "csv_auditor.py"]),
        ("eBay へ出品 (API)", [sys.executable, "ebay_upload_csv.py", latest, "--write",
                                "--result-json", result_json] if latest else []),
        ("itemID をスプシに書込", [sys.executable, "itemid_writeback_audit.py", "--apply"]),
        ("新規分を広告8%に", [sys.executable, "ads_add_new_listings.py", "--write"]),
    ]
    for label, cmd in steps:
        if not cmd:
            append_log_func(f"\n⚠️ {label}: 対象CSVが見つからず skip\n")
            continue
        append_log_func("\n======================================================================\n")
        append_log_func(f"▶ {label}\n")
        append_log_func("======================================================================\n")
        try:
            r = subprocess.run(cmd, cwd=tools, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=1800, env=env)
            if r.stdout:
                append_log_func(r.stdout)
            if r.returncode != 0:
                append_log_func(f"\n⚠️ {label} returncode={r.returncode}(続行)\n")
                if r.stderr:
                    append_log_func(r.stderr[-2000:])
        except Exception as e:
            append_log_func(f"\n⚠️ {label} 失敗(続行): {type(e).__name__}: {e}\n")
    _mail_upload_result(append_log_func, result_json, env)


def _exclusion_sources(csv_dir):
    """メールの内訳に使う素材を集める (I/O)。読めないものは空で返す。"""
    import glob as _glob
    import json as _json

    def _newest(pat):
        f = sorted(_glob.glob(pat), key=os.path.getmtime, reverse=True)
        return f[0] if f else ""

    def _read(p, as_json=False):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                return _json.load(f) if as_json else f.read()
        except Exception:                                     # noqa: BLE001
            return {} if as_json else ""

    log = _read(_newest(os.path.join(WORKSPACE, "iMakHQ", "run_logs", "*.log")))
    removed = _read(_newest(os.path.join(csv_dir, "*.csv.removed.json")), as_json=True)
    hoju = _read(os.path.join(WORKSPACE, "iMakHQ", "review_logs",
                              "hoju_from_dupes_last.json"), as_json=True)
    # 生成後に落ちた分 (live重複 / CSV内重複)。走行ログが閉じた後の処理なので log には出ない。
    post = _read(_newest(os.path.join(csv_dir, "*.csv.excluded.json")), as_json=True)
    return log, removed, hoju, post


def build_exclusion_lines(log_text="", removed=None, hoju=None, post_drops=None, upload=None):
    """出品されなかった分の「件数 / 中身 / その後どうなるか」(純関数・test 可)。

    ★2026-08-19 ユーザー要望: メールに **除かれた件数と内容、対応状況** を載せる。
      それまでメールは出品できた分しか書いておらず、落ちた分は走行ログを開かないと
      分からなかった (8/19 は 20件中6件が未回答で落ちたのに気づけなかった)。

    ★2026-08-19 追記 (ユーザー指摘「件数が合わないよね」): 内訳を足しても処理件数に届かなかった。
      原因は2つとも **記録していない物を推測で書いていた** こと:
        1. 生成後の間引き (CSV内に同じカードが2枚) はどこにも記録されず、内訳から丸ごと欠けた
        2. 目視の理由を「見送り − 該当なし = 未回答」と **引き算** で作っていた。
           実際には viewer に出せなかった1件が「未回答」と表示され、人が答え忘れたように見えた
      → 理由は記録した物だけを書く。記録が無ければ **書かない** (推測しない)。

    log_text: その走行のログ全文 / removed: `*.csv.removed.json`
    hoju: 補URL の記録 / post_drops: `*.csv.excluded.json` (生成後に落ちた分)。
    """
    import re as _re
    out = []

    def n(pat):
        m = _re.search(pat, log_text or "")
        return int(m.group(1)) if m else 0

    # ★2026-08-19: **母数の違うものを同じ並びに書かない**。
    #   「20件の中で落ちた分」と「20件を選ぶ前に候補から外した分」を混ぜたため、
    #   足すと 24件 になり 20件を超えていた (ユーザー指摘)。節を分ける。
    batch = n(r"(\d+)件を処理します")
    # --- (1) 今回の枠の中の内訳 (足すと batch になる) ---
    # 目視で進まなかった分: post_psa_review が理由ごとに記録した行をそのまま読む。
    after = {"該当なし": "カタログに依頼。1日後にまた出ます",
             "未回答": "次の走行でまた候補に戻ります",
             "保留": "次の走行でまた候補に戻ります",
             "目視に出せなかった": "PSAデータを取り直して次の走行で出します",
             "cert番号の訂正": "番号をシートに直しました。次の走行で取り直します"}
    name = {"該当なし": "「該当なし」", "未回答": "目視で未回答"}
    seen_reasons = _re.findall(r"^\s*・(.+?): (\d+)件 \[#", log_text or "", _re.M)
    if seen_reasons:
        for label, cnt in seen_reasons:
            k = label.split(" (")[0]
            out.append("・%s %s件 → %s" % (name.get(k, k), cnt,
                                           after.get(k, "次の走行でまた候補に戻ります")))
    else:
        # 旧い走行ログ (理由の記録が無い) 向けの読み方。**新しい走行では通らない**。
        none_ng = n(r"NONE/NG\s*(\d+)\s*件\s*→\s*catalog")
        pend = max(0, n(r"目視未確定で出品見送り:\s*(\d+)\s*件") - none_ng)
        if pend:
            out.append("・目視で未回答 %d件 → 次の走行でまた候補に戻ります" % pend)
        if none_ng:
            out.append("・「該当なし」 %d件 → カタログに依頼。1日後にまた出ます" % none_ng)
    self_ng = len(_re.findall(r"selfcheck failed in build_row", log_text or ""))
    if self_ng:
        out.append("・自己チェックで不一致 %d件 → 残務に記録済 (こちらの不具合)" % self_ng)
    # 生成後に落ちた分 (走行ログには出ない = 記録を読むしかない)。
    # 記録 (excluded.json) があればそれを正とし、無ければ従来の removed.json で live重複だけ出す。
    drops = (post_drops or {}).get("drops")
    if drops is None:
        live_n = int((removed or {}).get("removed") or 0)
        live_titles = list((removed or {}).get("removed_titles") or [])
        intra_n = 0
    else:
        live = [d for d in drops if d.get("reason") == "live-dup"]
        live_n, live_titles = len(live), [d.get("title") or "" for d in live]
        intra_n = sum(1 for d in drops if d.get("reason") == "intra-dup")
    if live_n:
        names = [t.split(") ", 1)[-1][:44] for t in live_titles if t]
        tail = (" — " + " / ".join(names[:3]) + (" ほか" if len(names) > 3 else "")) if names else ""
        added = (hoju or {}).get("added")
        aft = ("仕入元は補URLに回しました (今回 %s本 追加)" % added
               if added else "仕入元は補URLの対象になります")
        out.append("・同じカードが既に出品中 %d件 → %s%s" % (live_n, aft, tail))
    if intra_n:
        out.append("・同じカードが今回2枚 %d件 → 1枚だけ出品しました "
                   "(残りは次の走行で候補に戻ります)" % intra_n)
    sold_n = sum(1 for d in (drops or []) if d.get("reason") == "sold-out")
    if sold_n:
        out.append("・仕入元が売り切れ %d件 → 出品しません (仕入れられないため)" % sold_n)
    # 入稿の段で出せなかった分。★2026-08-19: ここが内訳に無く、20件が
    #   出品5 + 該当なし5 + 既出品8 = 18 にしかならなかった (ユーザー指摘)。
    #   eBay に弾かれた分と、停止で試行すらしなかった分を必ず書く。
    up = upload or {}
    n_ng = int(up.get("failed") or 0)
    if n_ng:
        out.append("・eBayに弾かれた %d件 → 理由は上の「失敗」を見てください" % n_ng)
    n_rest = max(0, int(up.get("rows") or 0) - int(up.get("listed") or 0) - n_ng)
    if n_rest:
        out.append("・途中で止まって出せなかった %d件 → 次の走行でまた候補に戻ります" % n_rest)
    # 在庫チェックが走らなかった時は黙らない (売り切れた物が入稿CSVに残っている)
    sc = (post_drops or {}).get("soldcheck")
    if sc and sc != "ok":
        out.append("・⚠️ 仕入元の在庫チェックが走っていません (%s)。"
                   "売り切れた物が混ざっている可能性があります" % sc)
    if out and batch:
        out.insert(0, "(今回の %d件 の内訳)" % batch)
    # --- (2) 枠に入る前に候補から外した分 (母数は候補全体。(1)とは別勘定) ---
    pre = []
    for label, why in (("NO-IMAGE", "カタログに画像が無い"),
                       ("OUT-OF-SCOPE", "参入しないゲーム"),
                       ("GAP", "カタログに未収録")):
        c = n(r"\[%s=[^\]]*\]:\s*(\d+)\s*件" % label)
        if c:
            aft = {"NO-IMAGE": "カタログに依頼済",
                   "OUT-OF-SCOPE": "対象外 (今後も出しません)",
                   "GAP": "カタログに依頼済"}[label]
            pre.append("・%s %d件 → %s" % (why, c, aft))
    if pre:
        out.append("")
        out.append("(枠に入る前に候補から外した分 — 上の内訳とは別勘定)")
        out.extend(pre)
    return out


def build_upload_mail(result):
    """出品結果 → (件名, 本文) (純関数・test可)。件数と出品URLだけの短い本文。

    ★0件でも送る。**「走ったが0件」と「走らなかった」を区別できる**のがこのメールの用途で、
      黙るとそこが分からなくなる (2026-08-18: 結果ファイルを書いていなかったため
      メールが一度も飛ばず、人が「まだ動いている」と思って待っていた)。
    """
    listed = result.get("listed") or []
    failed = result.get("failed") or []
    ng = int(result.get("ng") or 0)
    verify_only = not result.get("write", True)
    head = "[検証のみ] " if verify_only else ""
    subject = f"[自動出品] {head}{len(listed)}件 出品" + (f" / {ng}件 失敗" if ng else "")
    lines = [f"自動出品 {len(listed)}件" + ("  ※検証のみ (出品していません)" if verify_only else "")]
    if ng:
        lines.append(f"失敗 {ng}件")
    if result.get("stopped_early"):
        lines.append("⚠️ 失敗で途中停止しました (残りは出していません)")
    lines.append("")
    for it in listed:
        lines.append(f"{it.get('label', '')}  https://www.ebay.com/itm/{it.get('item_id', '')}")
    if failed:
        lines.append("")
        lines.append("― 失敗 ―")
        for it in failed:
            lines.append(f"{it.get('label', '')}  {it.get('error', '')}")
    excl = result.get("excluded_lines") or []
    if excl:
        lines.append("")
        lines.append("― 出品しなかった分 ―")
        lines.extend(excl)
    return subject, "\n".join(lines)


def _mail_upload_result(append_log_func, result_json, env):
    """出品結果をメールで送る (監視くんの共用CLIを使う・2026-08-18)。

    ★送信失敗を握り潰さない。「メールが飛ばなかったのに成功扱い」が一番まずい失敗
    (監視くんの申し送り)。exit 1 はそのまま画面に出す。
    """
    import json as _json
    if not os.path.exists(result_json):
        # ★ここに来る = 入稿が結果を残さなかった。黙ると「まだ動いている」と誤解される。
        append_log_func("\n⚠️ 出品結果ファイルが無い → メールを送れません "
                        f"({result_json})\n")
        return
    try:
        result = _json.load(open(result_json, encoding="utf-8"))
    except Exception as e:
        append_log_func(f"\n⚠️ 出品結果を読めずメール skip: {type(e).__name__}\n")
        return
    # ★2026-08-19: 出品できた分だけでなく **落ちた分と その後どうなるか** も載せる。
    #   読めなかった素材は省くだけで、メール自体は必ず出す。
    try:
        _csv_dir = os.path.dirname(result_json)
        _rows = 0
        try:
            import csv as _csv
            with open(os.path.join(_csv_dir, result.get("csv") or ""),
                      encoding="utf-8-sig") as _f:
                _rows = sum(1 for _ in _csv.DictReader(_f))
        except Exception:                                      # noqa: BLE001
            _rows = 0
        result["excluded_lines"] = build_exclusion_lines(
            *_exclusion_sources(_csv_dir),
            upload={"rows": _rows, "listed": len(result.get("listed") or []),
                    "failed": len(result.get("failed") or [])})
    except Exception as e:                                    # noqa: BLE001
        append_log_func(f"\n(メールの除外内訳は付けられず: {type(e).__name__})\n")
    subject, body = build_upload_mail(result)
    body_file = os.path.join(os.path.dirname(result_json), "last_upload_mail.txt")
    with open(body_file, "w", encoding="utf-8") as f:
        f.write(body)
    append_log_func("\n======================================================================\n")
    append_log_func("▶ 出品結果をメール送信\n")
    append_log_func("======================================================================\n")
    try:
        r = subprocess.run([sys.executable, r"C:\dev\iMak_data\tools\send_mail.py",
                            "--subject", subject, "--body-file", body_file],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300, env=env)
        if r.stdout:
            append_log_func(r.stdout)
        if r.returncode == 0:
            append_log_func(f"  ✅ 送信しました: {subject}\n")
        else:
            append_log_func(f"  ❌ **メール送信に失敗しました** (exit {r.returncode})。"
                            f"出品自体は完了しています。ログ: "
                            f"C:/dev/iMak_data/tools/logs/send_mail.log\n")
            if r.stderr:
                append_log_func(r.stderr[-800:])
    except Exception as e:
        append_log_func(f"  ❌ **メール送信に失敗しました**: {type(e).__name__}: {e}\n")


def _runs_new_listing_dedupe(script_entry):
    """新規出品用の重複くん(KEY tuple excluder)を走らせてよいエントリかを返す(純関数)。

    RESTOCK Revise(restock_revise)は **既存出品の Action=Revise 修正**(itemID指定で qty 0→1)で、
    新しい出品を1件も作らない=重複は原理的に起き得ない。にもかかわらず新規出品用の重複くんを通すと、
    RESTOCK 対象カードの **自分の既存出品 KEY**(商品管理シート AI列)と自己マッチして RESTOCK 行を
    「真の重複」と誤判定し物理除外する(2026-06-22: OP02-036/S8b-187/ST29-016 の3件が自己重複で誤除外、
    qty=0 の OP02-036 が再出品されない事故)。canonical 母集団は RESTOCK 対象自身を含むため、母集団から
    自 itemID を除く改修は dedupe worktree 側になる。HQ 側の正しい境界は「RESTOCK は新規用 dedupe を
    そもそも通さない」。skip_postprocess(監査/relist)も従来どおり走らせない。
    """
    if script_entry.get("skip_postprocess"):
        return False
    if script_entry.get("restock_revise"):
        return False
    return True


# ============================================================================
# RESTOCK Add→Revise 変換 helper (2026-06-20 追加)
# post-chain (excluder/title-fix/dedup) の **後** に最終クリーン Add CSV を Revise 化。
# 旧: psa_restock_build が dedup の **前** に変換し、赤字(NO-GO)/重複/旧タイトルが Revise に
#     混入していた (2026-06-19 194513 で 11行=赤字3+重複 になった)。順序を保証する。
# ============================================================================
def _run_restock_revise_for_latest_csv(append_log_func, since_ts=None):
    try:
        csv_dir = os.path.join(WORKSPACE, "iMakHQ", "csv_output")
        if not os.path.isdir(csv_dir):
            return
        cands = [f for f in os.listdir(csv_dir)
                 if f.startswith("tcg_upload_") and f.endswith(".csv") and ".bak" not in f]
        if not cands:
            return
        cm = sorted([(f, os.path.getmtime(os.path.join(csv_dir, f))) for f in cands],
                    key=lambda x: x[1], reverse=True)
        latest_csv = os.path.join(csv_dir, cm[0][0])
        if since_ts is not None and cm[0][1] < since_ts:
            append_log_func("\n(♻ RESTOCK Revise: 今回 listing で新規 CSV 出力なし → skip)\n")
            return
    except Exception as e:
        append_log_func(f"\n⚠️ RESTOCK Revise CSV 探索失敗: {type(e).__name__}: {e}\n")
        return
    append_log_func("\n======================================================================\n")
    append_log_func("▶ ♻ RESTOCK Add→Revise 変換 (post-chain後=最終クリーンCSV)\n")
    append_log_func("======================================================================\n")
    try:
        _tools = os.path.join(WORKSPACE, "iMakHQ", "tools")
        if _tools not in sys.path:
            sys.path.insert(0, _tools)
        import psa_restock_revise_csv as rv
        desk = os.path.join(os.path.expanduser("~"), "OneDrive", "デスクトップ")
        out_csv = os.path.join(desk, "RESTOCK_revise_"
                               + os.path.basename(latest_csv).replace("tcg_upload_", ""))
        n, sk = rv.convert_file(latest_csv, out_csv)
        append_log_func(f"✅ Revise CSV生成: {out_csv} ({n}行 / 変換skip {len(sk)})\n")
        for s in sk[:10]:
            append_log_func(f"  ⏭ {s}\n")
        append_log_func("→ check後、FileExchange に手動アップロード → 反映後に writeback(qty verify)\n")
    except Exception as e:
        append_log_func(f"\n⚠️ RESTOCK Revise 変換失敗: {type(e).__name__}: {e}\n")


# ============ スクリプト登録 ============
# 5/12: カテゴリ別に「新規 / 再出品」2ボタン構成 (パネル UI で Labelframe グループ化)
# - category: グループ枠名 (None = utility 単独ボタン)
# - type: "new" / "relist" / "utility"
# - 再出品 ボタンは seller_hub_relist.py --category <key> で対象抽出 + B 列空欄化 + End CSV 生成
SCRIPTS = [
    # ===== カテゴリ別 listing (新規のみ、再出品は 5/13 廃止) =====
    {
        "category": "Tシャツ", "type": "new", "label": "新規",
        "verified": True,  # 2026-04-19 ユーザーチェック合格
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "tshirt_listing.py"],
        "params": [],
    },
    {
        "category": "Montbell", "type": "new", "label": "新規",
        "verified": True,  # 2026-05-05 ユーザーチェック合格
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "montbell_listing.py"],
        "params": [],
    },
    {
        "category": "Porter", "type": "new", "label": "新規",
        "verified": True,  # 2026-04-19 ユーザーチェック合格
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_to_ebay_csv.py", "--sheet", "porter"],
        "params": [],
    },
    {
        "category": "G-SHOCK", "type": "new", "label": "新規",
        "verified": True,  # 2026-05-06 ユーザーチェック合格
        "cwd": f"{WORKSPACE}/iMakG-shock",
        "cmd": ["python", "gshock_to_csv.py"],
        "params": [],
    },
    {
        "category": "PSA TCG", "type": "new", "label": "新規",
        "verified": True,  # 2026-04-24 及第点到達
        "double_check": True,  # 2026-04-26 入稿前の人手ダブルチェック必須
        "cwd": f"{WORKSPACE}/iMakTCG",
        "cmd": ["python", "psa_to_csv.py"],
        # 新コア ON = 本番が catalog 決定論コア (tcg_listing_fields/override) を使用。
        # 2026-06-15 ユーザー明示 go で flip。根拠: Gemini 条件付きGO + parity REGRESSION 0 +
        #   旧コアが毎回再発させる defect (Character/Card Name 汚染・rarity 推測'Common'・
        #   Card Size 'Japanese') を構造的に解消。OFF 復帰は下行 "env" の削除のみ (psa_to_csv 無改変)。
        # PSA_VERIFY_BEFORE_BUILD=1: 先に HTML 目視確認 → 確定したカードだけ CSV 生成
        # (2026-06-15 ユーザー指示「目視確認してからCSV作成にして」)。OFF 復帰= この key 削除のみ。
        "env": {"TCG_USE_NEW_GEN": "1", "PSA_VERIFY_BEFORE_BUILD": "1"},
        "params": [],
    },
    {
        # ★2026-08-18 ユーザー指示「PSA TCG の横に PSA自動を1つだけ。CSV監査くんもセットで」。
        # 中身は 新規 と同じ生成 + 後処理チェーン。違いは締めに auto_full の3手が付くこと
        # (itemID書込 → 広告8% → CSV監査くん)。押すのは1回でよくなる。
        "category": "PSA TCG", "type": "auto", "label": "🤖自動",
        "verified": True,
        "double_check": True,
        "cwd": f"{WORKSPACE}/iMakTCG",
        "cmd": ["python", "psa_to_csv.py"],
        # ★2026-08-18 ユーザー指示「自動だけ20件」。手動 (PSA TCG) は既定 15 のまま。
        #   値は env で注入 = コード側に「自動なら〜」の分岐を作らない。
        # PSA_REVIEW_ALL=1: 確定済 cert も毎回目視に出す。cert 入力ミスは
        #   「仕入元の写真 ↔ PSA写真」の見比べでしか弾けず、自動はここが最後の砦。
        "env": {"TCG_USE_NEW_GEN": "1", "PSA_VERIFY_BEFORE_BUILD": "1",
                "PSA_BATCH_LIMIT": "20", "PSA_REVIEW_ALL": "1"},
        "params": [],
        "auto_full": True,
    },
    {
        "category": "リール", "type": "new", "label": "新規",
        "verified": True,  # 2026-04-24 実戦検証合格
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_to_ebay_csv.py", "--sheet", "reel"],
        "params": [],
    },
    {
        "category": "一番くじ", "type": "new", "label": "新規",
        "verified": True,
        "cwd": f"{WORKSPACE}/iMak_ichibankuji",
        "cmd": ["python", "ichibankuji_to_csv.py"],
        "params": [],
        "custom_buttons": "ichibankuji",
    },
    {
        "category": "Tomica", "type": "new", "label": "新規",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_to_ebay_csv.py", "--sheet", "tomica"],
        "params": [],
    },
    {
        "category": "その他混在", "type": "new", "label": "新規",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_to_ebay_csv.py"],
        "params": [],
    },
    {
        "category": "Workman", "type": "new", "label": "新規",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "workman_listing.py"],
        "params": [],
    },
    # ===== Utility 単独ボタン (カテゴリなし) =====
    {
        "category": None, "type": "utility",
        "label": "🔍 CSV監査くん",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "csv_auditor.py"],  # 引数なし=最新CSV自動。4軸監査+機械修正+依頼
        "params": [],
        # 監査=読取専用。後処理チェーン(excluder/dedupe/write-keys)を再実行させない。
        # 再実行すると 直前 cycle で write-keys が書いた canonical KEY を dedupe が「既存」と
        # 誤認し、未出品(itemID空)の自カードを自己重複として CSV から削除する (2026-06-10 発覚:
        # 3件→1件に誤減。psa_to_csv の post-chain で既に1回処理済=2度目は不要)。
        "skip_postprocess": True,
    },
    {
        "category": None, "type": "utility",
        "label": "G-SHOCK 未出品モデル発見",
        "cwd": f"{WORKSPACE}/iMakG-shock/casio_finder",
        "cmd": ["python", "casio_finder.py"],
        "params": [],
    },
    {
        "category": None, "type": "utility",
        "label": "G-SHOCK 未出品モデル (catalog)",
        "cwd": f"{WORKSPACE}/iMakG-shock/casio_finder",
        "cmd": ["python", "casio_finder_from_catalog.py"],
        "params": [],
    },
    {
        "category": None, "type": "utility",
        "label": "モンベル公式アウトレット 巡回",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "montbell_outlet_scraper.py"],
        "params": [
            {"name": "--categories", "label": "カテゴリID(カンマ区切り)", "default": ""},
            {"name": "--limit", "label": "各cat件数上限", "default": ""},
        ],
    },
    {
        "category": None, "type": "utility",
        "label": "Mercari スカウト",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_scout.py"],
        "params": [],
    },
    # 2026-06-04: 月次レポート生成 / 今、見る はパネルから削除 (ファネル分析が上位互換。.py は残置)
    # 取下再出品 ①②③ を上段、✏️タイトル改修/💲値下げ余地 を下段に並べる (3列グリッド=d1)。
    # 表示順は _ugroup "relist" 群の SCRIPTS 出現順なので ①②③→タイトル改修→値下げ余地 の順で置く。
    {
        "category": None, "type": "utility",
        "label": "取下再出品① 取下げ(End)",
        "label_fg": "red",  # ボタンラベル赤文字 (取下→再出品のフロー起点を強調)
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        # ファネルRELIST候補→End CSV+保留リスト (再出品済は自動除外/初回・2回目END振分)。候補確認はスプシ「取下再出品」タブ
        "cmd": ["python", "relist_from_funnel.py"],
        "params": [],
    },
    {
        "category": None, "type": "utility",
        "label": "取下再出品② Add生成(即live)",
        "label_fg": "red",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "relist_add_from_pending.py"],  # 保留リスト→カテゴリ振り分け→各--relist→Add CSV+skumap
        "params": [],
        # relist は同型番を意図的に再出品 → excluder/重複くん が「重複」誤判定で削除するのを防ぐ
        "skip_postprocess": True,
    },
    {
        "category": None, "type": "utility",
        "label": "取下再出品③ 書戻し(B列)",
        "label_fg": "red",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        # デスクトップの最新Add結果レポート自動検出→スプシB列に新ItemID上書き+ダッシュボード更新
        "cmd": ["python", "relist_writeback.py", "--auto", "--execute"],
        "params": [],
    },
    {
        # NO_CONVERT 価格見直し (2026-07-01 price_resistance から差替。タイトル改修と順序入替=価格見直しを先に)。
        # 利益率(V8・ライブUSD)算出 → 値下げ余地シート + B列pp(既定5/手動可) + AL列flag書込。
        # リバイス君が週1で AL列を読み apply_pricedown_override を適用。旧 price_resistance は役割終了。
        "category": None, "type": "utility",
        "label": "💲 価格見直し",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "noconvert_pricedown.py"],
        "params": [],
        # 結果は「既存メンテ」スプシ 値下げ余地タブ(gid直開き) + 商品管理シート AL列(値下FLG)
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit#gid=1187422007",
    },
    {
        # ④: NO_CLICK ∩ watcher有 を手 revise 対象として CSV 出力 (2026-06-05)。①の下段
        "category": None, "type": "utility",
        "label": "✏️ タイトル改修",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "noclick_targets.py"],
        "params": [],
        # 結果は「既存メンテ」スプシ タイトル改修タブに集約 (CSV廃止)
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit#gid=903147763",  # タイトル改修
    },
    # ============ PDCA 出品改善 (Seller Hub 4レポート → ファネル分析) ============
    # 前提: Seller Hub の 4レポート(all-active/Listing quality/unsold/orders)を
    #       C:/dev/iMak_data/seller_hub/reports/ に置く (無ければデスクトップの所定フォルダ)
    {
        "category": None, "type": "utility",
        "label": "📊 ファネル分析",
        "label_fg": "blue",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "listing_funnel.py"],
        "params": [],
        # 結果は「ファネル分析」スプシに集約 (xlsx廃止)。実行後そのスプシを開く
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit#gid=1505533226",  # 取下再出品
    },
    {
        # ①効果測定ループ: 直近2世代の funnel を突合し「直した結果が効いたか」を測る (2026-06-05)
        "category": None, "type": "utility",
        "label": "📉 効果測定",
        "label_fg": "blue",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "funnel_diff.py"],
        "params": [],
        # 結果は「既存メンテ」スプシ 効果測定タブに集約 (CSV廃止)
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit#gid=854452140",  # 効果測定
    },
    {
        "category": None, "type": "utility",
        "label": "📈 需要・新規強化",
        "label_fg": "blue",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "demand_winners.py"],
        "params": [],
        # 結果は「既存メンテ」スプシ 需要・新規強化タブに集約 (CSV廃止)
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit#gid=69747990",  # 需要・新規強化
    },
    # 2026-06-04: G-SHOCK価格調査(amazon_v8_check/mercari_gshock_resource)とタイトル改修(title_keyword_proposal)は
    #   一度きりの調査ツールで在庫あり文脈で紛らわしいためパネルから除外 (tools/ に .py は残置=直叩き可)。
    {
        "category": None, "type": "utility",
        "label": "🃏 PSA再仕入れ照合",
        "badge": "psa_gate",
        "tip": "在庫切れしたPSA10のうち、まだ需要がある物の仕入元 (メルカリ/スニダン) を探して、"
               "現物と見比べて確定します。確定した分は次の ♻ でCSVになります。"
               "1回で新規10件見つかるまで掘ります。",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        # 2チャネル(Mercari＆SNKRDUNK)ゲート。探索前に①現物(出品PSA)=②catalog の目視確認ゲートが
        # ブラウザで開く→一致分だけ探索。不一致はPDCA台帳(原因別振り分け)。旧 mercari_psa_resource.py
        # (Mercari単体・確認/PDCA無し)から張替 (2026-06-17)。
        "cmd": ["python", "psa_resource_gate.py"],
        "params": [],
        # ★新規再仕入れ可が10件見つかるまで保留分を検索(2026-07-26 ユーザー要望「10件出したい」)。
        # SNKRDUNK先取り→メルカリ保留分をtargetまで掘る。BAN上限=RESTOCK_MAX_SCRAPE(既定60)/1走行。
        "env": {"RESTOCK_TARGET_NEW": "10"},
        # 結果は「既存メンテ」スプシ PSA再仕入れタブに集約 (CSV廃止。再仕入れ系をシート統一)
        
    },
    {
        # RESTOCK後工程① 視覚確証で確定したカードを 新コア生成→Revise CSV化(手動UL用)。2026-06-18
        "category": None, "type": "utility",
        "label": "♻ RESTOCK Revise CSV生成",
        "badge": "restock_build",
        "tip": "🃏 で仕入元が確定した分を、出品しなおすCSVにします (手でアップロードする用)。"
               "一度出した分は自動で除きます。",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "psa_restock_build.py"],
        "params": [],
        # post-chain(excluder/title-fix/dedup)の **後** に Add→Revise 変換する(順序保証)。
        # psa_restock_build は Add CSV 生成までで、Revise 化は control_panel が最終CSVに対して実施。
        "restock_revise": True,
        "open_after": r"C:/Users/imax2/OneDrive/デスクトップ/RESTOCK_revise_*.csv",
    },
    {
        # RESTOCK後工程② アップロード反映後、実eBay qty を verify してスプシ書戻し(状態同期)。2026-06-18
        "category": None, "type": "utility",
        "label": "🔄 RESTOCK状態同期(書戻し)",
        "badge": "restock_wb",
        "tip": "♻ のCSVをアップロードした後に押します。eBayの実際の在庫数を見て、"
               "本当に戻っている物だけ「実行済」にします。戻っていない物は残るので、"
               "取りこぼしになりません。",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "psa_restock_writeback.py"],
        "params": [],
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit#gid=2106548521",  # RESTOCK確定
    },
    # ★2026-07-31: 「💰 オファー判定(自動読込)」はここから撤去。
    #   トップの nav に **青字「💰 オファー対応」**ボタンを新設し、そちらへ集約した
    #   (同じ `offer_calc.py` を叩くだけの重複だった)。実装は HomePanel.open_offer_calc。
    #   オファーは「既存メンテ」の作業ではなく、来たら即判断する独立の入口なので上段に置く。
    # ---- 補URL能動充填 (2026-07-25 Phase1)。出品が「仕入元1本切れ」で死なないよう補URL(AC-AG)を厚く保つ。
    #   夜=検索(無人・8件毎cacheコミット=途中死で残る) → 昼=視覚確証で正変種だけ補URL書込 → status=件数感。
    #   RESTOCKゲートと同一 primitives・共有cache。設計: discussion/2026-07-24_psa_hoju_url_replenishment_design.md ----
    {
        "category": None, "type": "utility",
        "label": "📊 補URL件数感(status)",
        "label_fg": "#0a7",
        "badge": "hoju_status",
        "tip": "見るだけのボタン。仕入元の予備 (補URL) が何本あるかの内訳を出します。"
               "押しても何も変わらないので、色は変わりません。",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "psa_hoju_fill.py", "status"],
        "params": [],
        "skip_postprocess": True,
    },
    {
        # ★2026-07-28: **入稿して itemID を書き終えた直後に押す**ボタン。
        # 補URL検索の対象は「itemID が入っている(=出品済)」行なので、CSV生成直後の自動実行では
        # 当日の新規カードを拾えない(itemID がまだ無い)。itemID が付いた時点は人しか知らないため、
        # 自動化せずボタンにする(ユーザー提案)。対象は新規優先の並びで先頭に来る。
        "category": None, "type": "utility",
        "label": "🆕 補URL 当日分",
        "tip": "出品した直後に押す。その日に出した分だけ、仕入元の候補を今すぐ検索する。夜間検索(slice2)を待たずに供給を確保したい時に使う。",
        "badge": "hoju_search",
        "label_fg": "#0a7",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "psa_hoju_fill.py", "search", "--limit=15"],
        "params": [],
        "skip_postprocess": True,
    },
    {
        # slice2: 補が薄い live PSA を mercari/snkrdunk 検索→候補+画像を cache(補URL列は触らない)。無人可・停止可。
        "category": None, "type": "utility",
        "label": "🔎 補URL slice2",
        "tip": "夜間検索。補URLが薄い出品の仕入元候補を探して溜めるだけで、補URL欄には書かない。毎晩23:30 に自動で走るので、普段は押す必要がない。",
        "badge": "hoju_search",
        "label_fg": "#0a7",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "psa_hoju_fill.py", "search"],
        "params": [],
        "skip_postprocess": True,
    },
    {
        # slice3: cache済候補を現物と視覚確証(ブラウザ)→正変種だけ補URL(AC-AG)へ既存保持+空き枠冪等書込。主URL不可触。
        "category": None, "type": "utility",
        "label": "🩹 補URL slice3",
        "tip": "昼の目視確認。夜に溜めた候補を現物と見比べて、同じ物だけ補URL欄に書く。1回10件ずつ。出した分は最後までやり切る作り。",
        "badge": "hoju_confirm",
        "label_fg": "#0a7",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        # ★2026-07-28: 1回10件ずつ(ユーザー要望「途中で辞められないから」)。
        # 確証UIは全件まとめて送信する作り = 出した分は最後までやり切る必要がある。
        # 補が埋まった行は次回 select_backfill_targets から自然に外れるので、押すたびに続きが出る。
        "cmd": ["python", "psa_hoju_fill.py", "confirm", "--limit=10"],
        "params": [],
        "skip_postprocess": True,
        # ★2026-08-09: 従来は「既存メンテ」スプシの**先頭タブ(抽出ロジック)**を開いていた。
        #   slice3 が書くのは **商品管理シートの補URL列(AC-AG)** なので、まったく関係ない
        #   タブが開いていた。書いた結果をその場で確認できる場所へ飛ばす。
        "open_url": ("https://docs.google.com/spreadsheets/d/"
                     "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk/edit#gid=851100680"),
    },
    {
        # ★2026-08-13: 補URL確証で「違う(別商品)」「要調査」と捨てた候補を、**新規出品の種**に戻す。
        #   「違う」は *その出品のカードでない* としか言っておらず、**別の実在カードの仕入元**である
        #   ことが多い (= 出品していないカードの供給を毎日捨てていた)。
        #   ただし同定は**ゼロからやり直す**: 候補タイトル→カード番号→catalog で版を引き、
        #   版が複数ある時だけ絵柄で選ぶ。決まらなければ出品に回さない (fail-closed)。
        "category": None, "type": "utility",
        "label": "🌱 捨てた候補→新規出品の種",
        "label_fg": "#0a7",
        "badge": "newcand",
        # ★2026-08-31: tip が無いと _attach_tip 自体が呼ばれず (_grid_named は
        #   `if _tip else None`)、refresh_hoju_badge が数えていた件数 (n_txt) が
        #   一度も画面に出ていなかった。ヒントに件数を出すにはこの1行が要る。
        "tip": "補URL確証で「違う(別商品)」「要調査」と捨てた候補を、新規出品の種として"
               "目視画面に戻します。",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "newcand_confirm.py", "--limit=20"],
        "params": [],
        "skip_postprocess": True,
        # ★書込先は「既存メンテ」スプシの 新規出品候補 タブ (2026-08-13 修正)。
        #   商品管理シートを開いていたが、このツールは本体に一切書かない = 別の場所を見せていた。
        "open_url": ("https://docs.google.com/spreadsheets/d/"
                     "1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit#gid=641366106"),
    },
    {
        # ★2026-08-22: 一番くじの補URLも PSA と同じ 2段 (夜=検索 / 昼=目視) にした。
        #   画面は PSA の確証UI をそのまま使う (見た目・操作が分かれないように)。
        "category": None, "type": "utility",
        "label": "🎴 くじ補URL slice2",
        "badge": "kuji_search",
        "tip": "一番くじ版の夜間検索。候補と、その詳細 (新品か/送料込みか/セラー評価) を先に取って溜める。補URL欄には書かない。",
        "label_fg": "#0a7",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        # ★2026-08-22: 候補 (prefetch-live) だけでは セラー名/星/発送日数 が入らない。
        #   詳細ページの先読み (prefetch-detail) まで通して初めて画面に出る。
        "cmd": ["python", "run_kuji_night.py"],
        "params": [],
        "skip_postprocess": True,
    },
    {
        # slice3: 夜に貯めた候補を現物と見比べて、選んだ分だけ補URL(AC-AG)へ書く。主URL不可触。
        "category": None, "type": "utility",
        "label": "🎴 くじ補URL slice3",
        "badge": "kuji_confirm",
        "tip": "一番くじ版の昼の目視確認。夜に溜めた候補を現物と見比べて、同じ物だけ補URL欄に書く。新品・送料込み・セラー評価で先に絞ってある。1回10件ずつ。",
        "label_fg": "#0a7",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        # PSA と同じく1回10件ずつ (確証UIは全件まとめて送信する = 出した分はやり切る)。
        "cmd": ["python", "ichibankuji_restock.py", "hoju", "10"],
        "params": [],
        "skip_postprocess": True,
        # 書いた結果 (商品管理シートの補URL列) をその場で見られるようにする。
        "open_url": ("https://docs.google.com/spreadsheets/d/"
                     "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk/edit#gid=851100680"),
    },
    # ---- 一番くじ 在庫補充 (PSA再仕入れの下に配置。2026-07-01 順序変更)。CLI: ichibankuji_restock.py ----
    # ①でsupply確定(スプシ記録のみ・eBay未変更)→②で在庫復活+内容刷新を Revise/Add CSV 一括出力。
    {
        "category": None, "type": "utility",
        "label": "🎴一番くじ補充① supply確定",
        "label_fg": "#0a7",
        "badge": "kuji_supply",
        "tip": "在庫切れした一番くじの仕入元を探して、現物と見比べて確定します。"
               "確定した分は次の ② でCSVになります。",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "ichibankuji_restock.py", "supply", "10"],
        "params": [],
        "skip_postprocess": True,
    },
    # ★2026-08-22: 「🎴一番くじ 補URL補充(目視)」を撤去。
    #   2026-08-16 に作ったが、2026-08-22 に「🎴 くじ補URL slice3」を同じ `hoju` に
    #   向け直した結果、**まったく同じコマンドのボタンが2つ**になった。
    #   同じ物が2つあると、どちらを押せばいいか分からない (ユーザー指摘)。
    #   役割は slice2 (夜=候補集め) / slice3 (昼=目視して書く) の2つで足りる。
    {
        "category": None, "type": "utility",
        "label": "🎴一番くじ補充② 刷新→CSV",
        "label_fg": "#0a7",
        "badge": "kuji_refresh",
        "tip": "① で確定した分の説明文・画像を作りなおして、出品CSVにします。"
               "① をやっていないと対象0件です。",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "ichibankuji_restock.py", "refresh-csv"],
        "params": [],
        "skip_postprocess": True,
    },
    {
        # 売れた分を入口にする唯一のボタン (2026-08-28)。他の補充系は全部ファネル起点で、
        # 売れて閉じた出品は RESTOCK に乗らないため一覧に出てこなかった (実測: 8/27 の PSA 4枚)。
        # 作り直さない = Relist/Revise で qty=1 + 仕入値から出した価格/送料ポリシーを送るだけ。
        # 既定は「何をやるか出すだけ」。実行は --write (パネルからは params で渡す)。
        "category": None, "type": "utility",
        "label": "🔁 売れた分を補充",
        "label_fg": "blue",
        "badge": "sold_restock",
        "tip": "PSA/G-Shock/一番くじで売れた分を、作り直さず qty=1 に戻すだけで補充します。"
               "対象外(アパレル等)は監視くんが在庫を見て自動で戻します。",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "sold_restock.py"],
        "params": [],
    },
    {
        # A: 在庫切れ ∩ 需要実証済(RESTOCK) を全vein分まとめて再仕入れワークシート化 (2026-06-05)
        "category": None, "type": "utility",
        "label": "🛒 在庫切れ再仕入れ",
        "label_fg": "blue",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "restock_worklist.py"],
        "params": [],
        # 結果は「既存メンテ」スプシ 再仕入れタブに集約 (CSV廃止)
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit#gid=373045082",  # 再仕入れ
    },
    {
        # B: CULL(在庫切れ&需要皆無) を age>=21・CAP/回 で段階 End CSV 化 (2026-06-05)
        # ★2026-08-23: 50→200 (件数は cull_end.CAP が正)。**月末までに落とすと翌月の枠が空く**
        #   — eBay 公式「月末時点で生きている出品は翌月の枠にも計上される」。
        "category": None, "type": "utility",
        # ★2026-08-24: **押すだけで完結**する。選ぶ → 1件ずつ実状態を確認 → eBay に送る →
        #   スプシ更新 (B列を空 + Q列に CULL の印)。FileExchange への手アップは不要。
        #   2026-06-05 の「自動アップ無し」はユーザー指示で外した (送る直前に実状態を見ており、
        #   対象は qty=0 = そもそも買えない出品なので売上を失わない)。
        "label": "🗑 取下げ (200件/回・自動)",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "cull_end.py"],
        "params": [],
        # ★2026-08-24 ユーザー要望: 対象が出たらラベルを青に、残数はヒントに出す。
        #   数えるのは funnel CSV と済み台帳だけで **eBay は1回も叩かない**
        #   (同日に API の1日上限で取下げが5時間止まったため、表示のために使わない)。
        "badge": "cull_end",
        "tip": "在庫切れ&需要皆無の出品を取り下げます。押すだけで完結 "
               "(1件ずつ実状態を確認 → eBay に送る → スプシ更新)。",
        "open_after": r"C:/Users/imax2/OneDrive/デスクトップ/CULL出品停止候補_*.csv",
    },
    {
        # ★2026-09-03 ユーザー確定: **在庫ありの取下げはボタンを分ける**。
        #   ①は「買えないので落として損が無い」。②は「売れるかもしれない物を捨てる」
        #   判断で重さが違う。混ぜると重い方を軽い気持ちで押すことになる。
        "category": None, "type": "utility",
        "label": "📉 棚② 売れない在庫を落とす (重い・要確認)",
        "badge": "shelf_evict",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "shelf_evict.py", "--end", "--tier", "2"],
        "params": [],
        "ask_amount": True,
        "tip": "在庫はあるが売れていない出品を落とします。**売れるかもしれない物を"
               "捨てる判断**なので、候補CSV (デスクトップ 棚END候補_日付.csv) を見てから"
               "押してください。条件は 一度も売れていない / TCG 30日超・G-SHOCK 365日超 / "
               "US出品。G-SHOCK は中央値284日で売れるので30日では落としません。",
    },
    ]


# ============ ログ着色パターン ============
LOG_TAGS = [
    (re.compile(r'^\[\d+/\d+\]'),               "header",   "#0066cc"),  # 青: 商品開始
    (re.compile(r'Claude API|API送信|API:'),    "api",      "#cc6600"),  # 橙: API呼出
    (re.compile(r'eBay|TOPセラー|中央値'),       "ebay",     "#669900"),  # 緑: eBay情報
    (re.compile(r'🎯|💲|✅|✨|完了|成功'),       "success",  "#006600"),  # 緑: 成功
    (re.compile(r'❌|失敗|ERROR|エラー'),        "error",    "#cc0000"),  # 赤: 失敗
    (re.compile(r'⚠️|警告|WARNING'),             "warn",     "#cc6600"),  # 橙: 警告
    (re.compile(r'⏸|スキップ|SKIP'),             "skip",     "#888888"),  # 灰: スキップ
    (re.compile(r'^={3,}|^─{3,}'),               "sep",      "#999999"),  # 灰: セパレータ
]


# ============ ウィンドウサイズ保存・復元 ============
import json as _json
WINDOW_GEOMETRY_FILE = f"{WORKSPACE}/iMakHQ/.window_geometry.json"


def _load_geometry(window_name, default):
    try:
        with open(WINDOW_GEOMETRY_FILE, encoding="utf-8") as f:
            data = _json.load(f)
            return data.get(window_name, default)
    except Exception:
        return default


def _save_geometry(window_name, geometry_str):
    try:
        data = {}
        if os.path.exists(WINDOW_GEOMETRY_FILE):
            with open(WINDOW_GEOMETRY_FILE, encoding="utf-8") as f:
                data = _json.load(f)
        data[window_name] = geometry_str
        with open(WINDOW_GEOMETRY_FILE, "w", encoding="utf-8") as f:
            _json.dump(data, f, indent=2)
    except Exception:
        pass


# ============ 宿題（pending tasks）読み込み ============
INSTRUCTION_LOG = f"{WORKSPACE}/iMakHQ/instruction_log.md"


def _read_pending_tasks():
    """instruction_log.md から「宿題（保留、今後実装予定）」セクションを抽出。
    戻り値: (pending_count, body_markdown)
    """
    try:
        with open(INSTRUCTION_LOG, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return 0, f"読込失敗: {e}"
    marker = "## 宿題"
    idx = content.find(marker)
    if idx < 0:
        return 0, "宿題セクションが見つかりません"
    body = content[idx:]
    # 宿題の行数をカウント（| 宿題XXX | で始まる行）
    import re
    rows = re.findall(r'^\|\s*宿題\d+', body, flags=re.MULTILINE)
    return len(rows), body



_NIGHTLY_TASK = r"\iMakHQ_HojuSearch_2330"
_NIGHTLY_CACHE = {}


def nightly_search_state(task=_NIGHTLY_TASK):
    """補URL夜間検索の定期タスクの状態 (1セッション1回だけ見る)。

    戻り: {"ok": bool, "at": "23:30", "why": 理由}
    ★止まっている時に「自動で走ります」と出すと、誰も押さないまま止まり続ける。
      状態を見てから文言を決める (ラベルに嘘を書かない)。
    """
    if _NIGHTLY_CACHE:
        return _NIGHTLY_CACHE
    out = {"ok": False, "at": "23:30", "why": "確認できず"}
    try:
        import subprocess
        r = subprocess.run(["schtasks", "/query", "/tn", task, "/fo", "csv"],
                           capture_output=True, timeout=15)
        txt = r.stdout.decode("cp932", errors="replace")
        if r.returncode != 0:
            out["why"] = "タスクがありません"
        else:
            line = [x for x in txt.splitlines() if task.lstrip("\\") in x]
            cells = line[0].split('","') if line else []
            state = cells[2].strip('"') if len(cells) > 2 else ""
            nxt = cells[1].strip('"') if len(cells) > 1 else ""
            if "無効" in state or "Disabled" in state:
                out["why"] = "無効になっています"
            else:
                out["ok"] = True
                if " " in nxt:
                    out["at"] = nxt.split(" ")[1][:5]
    except Exception as e:                                    # noqa: BLE001
        out["why"] = "%s" % type(e).__name__
    _NIGHTLY_CACHE.update(out)
    return out


def _attach_tip(widget, text):
    """ボタンにカーソルを乗せたら説明を出す (2026-08-22 ユーザー要望)。

    ラベルを短くする代わりに、長い説明はここへ逃がす。
    表示に失敗しても**ボタンの動作は妨げない** (装飾なので握って良い)。
    """
    import tkinter as _tk
    state = {"win": None, "text": text}

    def show(_e=None):
        if state["win"] is not None:
            return
        try:
            x = widget.winfo_rootx() + 12
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            w = _tk.Toplevel(widget)
            w.wm_overrideredirect(True)
            w.wm_geometry("+%d+%d" % (x, y))
            _tk.Label(w, text=state["text"], justify="left", background="#ffffe0",
                      relief="solid", borderwidth=1, font=("", 9),
                      wraplength=420, padx=6, pady=4).pack()
            state["win"] = w
        except Exception:                                     # noqa: BLE001
            state["win"] = None

    def hide(_e=None):
        w = state["win"]
        state["win"] = None
        if w is not None:
            try:
                w.destroy()
            except Exception:                                 # noqa: BLE001
                pass

    widget.bind("<Enter>", show)
    widget.bind("<Leave>", hide)
    widget.bind("<ButtonPress>", hide)

    def set_text(t):
        """件数など、後から変わる内容を差し替える (2026-08-22)。"""
        state["text"] = t
    return set_text


class TasksDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("📝 宿題（保留タスク）")
        self.geometry("900x600")
        count, body = _read_pending_tasks()
        header = ttk.Label(
            self, text=f"未対応宿題: {count}件", font=("", 12, "bold"),
            foreground="#cc5500"
        )
        header.pack(pady=(10, 4))
        txt = scrolledtext.ScrolledText(self, wrap="word", font=("Yu Gothic UI", 10))
        txt.pack(fill="both", expand=True, padx=10, pady=6)
        txt.insert("1.0", body)
        txt.config(state="disabled")
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=6)
        ttk.Button(btn_frame, text="📄 instruction_log.md を開く",
                   command=lambda: self._open_file(INSTRUCTION_LOG)).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="閉じる", command=self.destroy).pack(side="left", padx=4)

    def _open_file(self, path):
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("エラー", f"ファイル開けませんでした: {e}")


# ============ eBay API クライアント（進捗ダッシュボード用） ============
def _get_ebay_token():
    import base64
    import urllib.request
    import json
    keys = {}
    with open(EBAY_KEYS_FILE, encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                keys[k.strip()] = v.strip()
    creds = base64.b64encode(f"{keys['AppID']}:{keys['AppSecret']}".encode()).decode()
    req = urllib.request.Request(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {creds}",
        },
        data=b"grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["access_token"]


def _fetch_category_count(token, keyword, category_id, since_iso=None):
    """指定eBayカテゴリ + キーワードで imax-64 アクティブ出品数を取得。
    since_iso 指定時は出品開始日がその日以降のもののみカウント（月次進捗用）。
    """
    import urllib.request
    import urllib.parse
    import json
    filters = [f"sellers:{{{EBAY_SELLER}}}", f"categoryIds:{{{category_id}}}"]
    if since_iso:
        filters.append(f"itemStartDate:[{since_iso}]")
    params = {
        "q": keyword,
        "filter": ",".join(filters),
        "limit": 1,
    }
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
            return data.get("total", 0)
    except Exception:
        return None


def _month_start_iso():
    """今月1日 00:00 UTC の ISO 8601 文字列。"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return month_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")


_CACHED_SHEET_COUNTS = {"data": None, "ts": 0}

def _fetch_consolidated_counts(month_yyyymm, cache_seconds=60):
    """統合High/Low シートを読込→R列で自動グルーピングしてカウント返す。
    Returns: {category_label: {'current': int, 'monthly': int}}
    """
    import time as _t
    now = _t.time()
    if _CACHED_SHEET_COUNTS["data"] and now - _CACHED_SHEET_COUNTS["ts"] < cache_seconds:
        return _CACHED_SHEET_COUNTS["data"]

    import gspread
    from google.oauth2.service_account import Credentials
    import concurrent.futures as _cf
    creds = Credentials.from_service_account_file(
        GSHEET_CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)

    def _read(args):
        key, sid, gid = args
        try:
            sh = gc.open_by_key(sid)
            ws = sh.get_worksheet_by_id(gid)
            data = ws.get_all_values()
            return key, data[1:] if len(data) > 1 else []
        except Exception as e:
            print(f"⚠️ 統合{key} 読込失敗: {e}")
            return key, []

    args_list = [(k, sid, gid) for k, (sid, gid) in CONSOLIDATED_SHEETS.items()]
    sheet_data = {}
    with _cf.ThreadPoolExecutor(max_workers=2) as ex:
        for key, data in ex.map(_read, args_list):
            sheet_data[key] = data

    # R列で自動グルーピング
    result = {}  # category → {current, monthly}
    seen_ids = set()  # 公式在庫シートとの重複排除用
    for sheet_key, rows in sheet_data.items():
        for row in rows:
            row = list(row) + [''] * (21 - len(row))
            url      = row[0].strip()
            item_id  = row[1].strip()
            sold     = row[3].strip()
            cat      = row[17].strip()
            added    = row[20].strip()
            if not url or not cat:
                continue
            if cat not in result:
                result[cat] = {'current': 0, 'monthly': 0}
            if item_id and not sold:
                result[cat]['current'] += 1
                seen_ids.add(item_id)
            if added.startswith(month_yyyymm):
                result[cat]['monthly'] += 1

    # ★公式在庫要チェック シート1 を現在数に合算 (item ID で重複排除)
    try:
        ws2 = gc.open_by_key(OFFICIAL_STOCK_SHEET_ID).get_worksheet(0)  # シート1
        for row in ws2.get_all_values()[1:]:
            row = list(row) + [''] * 8
            item_id = row[2].strip()
            src_url = row[5].strip()
            if not item_id or item_id in seen_ids:
                continue
            cat = _official_stock_category(src_url)
            result.setdefault(cat, {'current': 0, 'monthly': 0})['current'] += 1
            seen_ids.add(item_id)
    except Exception as e:
        print(f"⚠️ 公式在庫シート読込失敗: {e}")

    _CACHED_SHEET_COUNTS["data"] = result
    _CACHED_SHEET_COUNTS["ts"] = now
    return result


def _fetch_seller_stats(token):
    """セラー全体の feedback / 販売数 / フォロワーは Browse API では取れないので最初の1件から seller情報抽出。"""
    import urllib.request
    import urllib.parse
    import json
    params = {
        "q": "Japan",  # ワイルドカード不可のため全セラー商品が引っかかるであろう "Japan" を使う
        "filter": f"sellers:{{{EBAY_SELLER}}}",
        "limit": 1,
    }
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
            total_active = data.get("total", 0)
            items = data.get("itemSummaries", [])
            seller_info = items[0].get("seller", {}) if items else {}
            return {
                "total_active": total_active,
                "feedback_score": seller_info.get("feedbackScore", "?"),
                "feedback_percentage": seller_info.get("feedbackPercentage", "?"),
            }
    except Exception as e:
        return {"total_active": None, "feedback_score": "?", "feedback_percentage": "?", "error": str(e)}


class DashboardDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("📊 進捗ダッシュボード")
        self.geometry("900x650")

        # ヘッダー
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        self.status_var = tk.StringVar(value="データ取得中...")
        ttk.Label(top, textvariable=self.status_var, font=("", 11, "bold")).pack(side="left")
        ttk.Button(top, text="🔄 更新", command=self.refresh).pack(side="right")

        # ストア概要
        self.store_info_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.store_info_var, foreground="#0066cc").pack(anchor="w", padx=10)

        # テーブル
        frame = ttk.LabelFrame(self, text="カテゴリ別アクティブ出品数", padding=6)
        frame.pack(fill="both", expand=True, padx=10, pady=8)

        cols = ("カテゴリ", "現在", "目標", "不足", "進捗", "月次目標", "優先度")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=10)
        widths = (200, 60, 60, 60, 280, 80, 80)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w" if c in ("カテゴリ", "進捗") else "center")
        self.tree.pack(fill="both", expand=True)

        # 推奨メッセージ
        self.reco_frame = ttk.LabelFrame(self, text="💡 推奨アクション", padding=6)
        self.reco_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.reco_label = tk.Label(self.reco_frame, text="", justify="left", wraplength=860, fg="#cc5500", font=("Yu Gothic UI", 10, "bold"))
        self.reco_label.pack(anchor="w")

        self.after(200, self.refresh)

    def refresh(self):
        self.status_var.set("取得中...")
        self.tree.delete(*self.tree.get_children())
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self):
        try:
            token = _get_ebay_token()
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"❌ eBayトークン取得失敗: {e}"))
            return

        stats = _fetch_seller_stats(token)
        rows = []
        for label, cat_id, target, monthly in DASHBOARD_CATEGORIES:
            count = _fetch_category_count(token, cat_id)
            if count is None:
                rows.append((label, "?", target, "?", "エラー", monthly, "?"))
            else:
                lack = max(0, target - count)
                progress_pct = min(100, int(count / target * 100)) if target else 0
                bar = "█" * (progress_pct // 5) + "░" * (20 - progress_pct // 5)
                bar_str = f"{bar} {progress_pct}%"
                # 優先度: 不足数が大きいほど高い
                if lack == 0:
                    priority = "✅達成"
                elif lack > target * 0.5:
                    priority = "🔴高"
                elif lack > target * 0.2:
                    priority = "🟡中"
                else:
                    priority = "🟢低"
                rows.append((label, count, target, lack, bar_str, monthly, priority))

        # 推奨アクション文言
        reco_lines = []
        for label, cat_id, target, monthly in DASHBOARD_CATEGORIES:
            count = _fetch_category_count(token, cat_id)
            if count is not None:
                lack = max(0, target - count)
                if lack > target * 0.5:
                    reco_lines.append(f"🔴 {label}: 目標まで{lack}件不足 → 最優先で出品")

        def apply():
            self.tree.delete(*self.tree.get_children())
            for r in rows:
                tag = "ok" if r[6] == "✅達成" else ("high" if r[6] == "🔴高" else ("mid" if r[6] == "🟡中" else ""))
                self.tree.insert("", "end", values=r, tags=(tag,))
            self.tree.tag_configure("ok", background="#d4ffd4")
            self.tree.tag_configure("high", background="#ffd4d4")
            self.tree.tag_configure("mid", background="#fff4d4")

            self.store_info_var.set(
                f"セラー: {EBAY_SELLER} | "
                f"Feedback: {stats.get('feedback_score','?')} ({stats.get('feedback_percentage','?')}%) | "
                f"総アクティブ: {stats.get('total_active','?')}件"
            )
            self.status_var.set("✅ 更新完了")
            if reco_lines:
                self.reco_label.config(text="\n".join(reco_lines))
            else:
                self.reco_label.config(text="全カテゴリ目標達成🎉 新しいカテゴリ展開を検討", fg="#006600")
        self.after(0, apply)


class HomePanel:
    """トップページ: 進捗ダッシュボード中心。リスティング実行は別ウィンドウへ。"""
    def __init__(self, root):
        self.root = root
        root.title("出品くん v2 [C:\\dev\\iMak] - iMak Trading Japan")
        root.geometry(_load_geometry("home", "1100x820"))
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 上段: ナビゲーション
        nav = ttk.Frame(root, padding=8)
        nav.pack(fill="x")
        ttk.Label(nav, text="🎁 出品くん", font=("", 16, "bold")).pack(side="left")
        ttk.Label(nav, text=" v2", font=("", 16, "bold"), foreground="#cc0000").pack(side="left")
        ttk.Label(nav, text=" [C:\\dev\\iMak]", font=("", 10, "bold"), foreground="#008000").pack(side="left")
        ttk.Label(nav, text="  ©iMak Trading", font=("", 10), foreground="gray").pack(side="left")
        # 2026-06-04: 宿題ボタン撤去(open_tasks/TasksDialog は残置=戻せる)。
        #   URL入力(TCG)は仕組みのレベルアップで不要化 → URLInputDialog/open_url_input ごと削除。
        #   リスティングを 新規出品 / 既存メンテ の2ボタンに分割。
        # ★2026-07-31: オファー対応 を 既存メンテ と 更新 の間に追加 (青字)。
        #   side="right" は **pack した順に右から左へ**並ぶので、
        #   見た目を 新規出品 → 既存メンテ → オファー対応 → 更新 にするには
        #   この逆順 (更新 → オファー対応 → 既存メンテ → 新規出品) で pack する。
        try:
            ttk.Style().configure("Offer.TButton", foreground="#0066cc")
        except Exception:                                     # noqa: BLE001
            pass
        ttk.Button(nav, text="🔄 更新", command=self.refresh_dashboard).pack(side="right", padx=2)
        ttk.Button(nav, text="⏰ 定期", command=self.open_schedules).pack(side="right", padx=2)
        # ★2026-08-21: UK/AU/CA のミラー出品に 広告10% と ベストオファー を付ける。
        #   人が3サイトの画面を回って手でやっていた作業 (ユーザー依頼)。
        self.pmbo_btn = ttk.Button(nav, text="📣 Pm/Bo", style="Offer.TButton",
                                   command=self.open_mirror_pmbo)
        self.pmbo_btn.pack(side="right", padx=2)
        self.offer_btn = ttk.Button(nav, text="💰 オファー対応", style="Offer.TButton",
                                    command=self.open_offer_calc)
        self.offer_btn.pack(side="right", padx=2)
        ttk.Button(nav, text="🔧 既存メンテ", command=lambda: self.open_listing("maint")).pack(side="right", padx=2)
        ttk.Button(nav, text="🆕 新規出品", command=lambda: self.open_listing("new")).pack(side="right", padx=2)

        # ストア概要
        self.store_info_var = tk.StringVar(value="データ取得中...")
        ttk.Label(root, textvariable=self.store_info_var, foreground="#0066cc", font=("", 11, "bold")).pack(anchor="w", padx=10, pady=4)

        # 🌍 主要市場の現地時刻 (1秒ごと更新、4地域改行表示)
        clock_frame = ttk.LabelFrame(root, text="🌍 主要市場の現地時刻", padding=4)
        clock_frame.pack(fill="x", padx=10, pady=2)
        self.clock_var = tk.StringVar(value="")
        ttk.Label(clock_frame, textvariable=self.clock_var, font=("Consolas", 10, "bold"),
                  foreground="#333333", justify="left").pack(anchor="w")
        self._update_clocks()

        # === 担当者の稼働状況 (2026-07-31) ===
        #   worktree_board.py は前から在ったが **CLI にしか出ておらず、誰も見ていなかった**。
        #   実際に「監視くんの依頼が6日前から相手ボールのまま」「ルーティング待ちが8時間放置」
        #   が起きていた。トップに常設して、放置が目に入るようにする。
        wt_frame = ttk.LabelFrame(root, text="👷 担当者の稼働状況", padding=6)
        wt_frame.pack(fill="x", padx=10, pady=(0, 6))
        self.wt_var = tk.StringVar(value="読込中…")
        ttk.Label(wt_frame, textvariable=self.wt_var, font=("Consolas", 9),
                  justify="left", foreground="#222222").pack(anchor="w")
        threading.Thread(target=self._refresh_worktree_board, daemon=True).start()

        # === 進捗テーブル (総合 / 今月 を横並び・各半幅) ===  推奨アクション枠は撤去
        prog_row = ttk.Frame(root)
        prog_row.pack(fill="x", padx=10, pady=(6, 8))
        prog_row.columnconfigure(0, weight=1, uniform="prog")
        prog_row.columnconfigure(1, weight=1, uniform="prog")

        def _tags(tree):
            for tag, bg, fg in (("done", "#d4ffd4", "#006600"), ("blue", "#d4e6ff", "#003366"),
                                ("yel", "#fff4c4", "#806600"), ("red", "#ffd4d4", "#800000")):
                tree.tag_configure(tag, background=bg, foreground=fg)
            tree.tag_configure("total", background="#e0e0ff", foreground="#000066", font=("", 10, "bold"))

        dash_frame = ttk.LabelFrame(prog_row, text="📊 総合進捗 (vs 目標)", padding=6)
        dash_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        cols = ("カテゴリ", "目標", "現在", "不足", "進捗", "優先度")
        self.tree = ttk.Treeview(dash_frame, columns=cols, show="headings", height=9)
        for c, w in zip(cols, (130, 44, 44, 44, 130, 50)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w" if c in ("カテゴリ", "進捗") else "center")
        self.tree.pack(fill="both", expand=True)
        _tags(self.tree)

        month_frame = ttk.LabelFrame(prog_row, text="📅 今月の進捗 (月次目標)", padding=6)
        month_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        mcols = ("カテゴリ", "目標", "現在", "不足", "進捗")
        self.month_tree = ttk.Treeview(month_frame, columns=mcols, show="headings", height=9)
        for c, w in zip(mcols, (130, 54, 54, 44, 130)):
            self.month_tree.heading(c, text=c)
            self.month_tree.column(c, width=w, anchor="w" if c in ("カテゴリ", "進捗") else "center")
        self.month_tree.pack(fill="both", expand=True)
        _tags(self.month_tree)

        self.listing_windows = {}  # mode("new"/"maint") → リスティング別ウィンドウ (遅延生成)
        self.root.after(300, self.refresh_dashboard)

    def _on_close(self):
        _save_geometry("home", self.root.geometry())
        self.root.destroy()

    def _set_reco(self, text, fg="#cc5500"):
        """推奨アクション枠は 2026-06-04 撤去 (no-op。呼び出し側は残置)。"""
        return

    def _update_clocks(self):
        """主要市場の現地時刻 + バイヤー活発時間カウントダウンを1秒ごと更新。

        各国別に eBay バイヤー一般ピークタイム (現地時間) を設定:
          weekday: 平日 (Mon-Fri)
          weekend: 土日 + 祝日 (holidays ライブラリで国別判定)
        現在時刻が ACTIVE 内: 🟢 ACTIVE (終了まで Nh) [祝日なら 🎌]
        ACTIVE 外:           ⏰ 次のアクティブ開始まで Nh
        """
        from datetime import datetime, timedelta
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            self.clock_var.set("(zoneinfo 未対応)")
            return
        # 祝日判定 (holidays ライブラリ、未インストール時は祝日対応スキップ)
        try:
            import holidays as _holidays
            _hd = {
                "US": _holidays.country_holidays("US"),
                "GB": _holidays.country_holidays("GB"),
                "DE": _holidays.country_holidays("DE"),
                "AU": _holidays.country_holidays("AU"),
            }
        except ImportError:
            _hd = {}

        zones = [
            ("🇺🇸 米国 (NY)  ", "America/New_York",   "US", {"weekday": (19, 23), "weekend": (12, 22)}),
            ("🇬🇧 英国 (LON) ", "Europe/London",      "GB", {"weekday": (19, 22), "weekend": (11, 21)}),
            ("🇩🇪 独国 (BER) ", "Europe/Berlin",      "DE", {"weekday": (19, 21), "weekend": (11, 20)}),
            ("🇦🇺 豪州 (SYD) ", "Australia/Sydney",   "AU", {"weekday": (18, 21), "weekend": (10, 20)}),
        ]

        def _is_off_day(dt, country):
            """土日 or 祝日 か判定。祝日名 (str) or False を返す。"""
            if dt.weekday() >= 5:
                return "週末"
            hd_obj = _hd.get(country)
            if hd_obj and dt.date() in hd_obj:
                return hd_obj.get(dt.date()) or "祝日"
            return False

        def _hours(active_hours, dt, country):
            """土日/祝日なら weekend 時間、平日なら weekday 時間を返す."""
            return active_hours["weekend"] if _is_off_day(dt, country) else active_hours["weekday"]

        parts = []
        for label, tz, country, active_hours in zones:
            try:
                now = datetime.now(ZoneInfo(tz))
                time_str = now.strftime("%m/%d(%a) %H:%M:%S")
                start_h, end_h = _hours(active_hours, now, country)
                # 祝日マーク
                off_reason = _is_off_day(now, country)
                holiday_mark = ""
                if off_reason and off_reason != "週末":
                    holiday_mark = f" 🎌 {off_reason}"

                if start_h <= now.hour < end_h:
                    # 🟢 ACTIVE
                    end_today = now.replace(hour=end_h, minute=0, second=0, microsecond=0)
                    remaining_h = (end_today - now).total_seconds() / 3600
                    status = f"🟢 ACTIVE (あと {remaining_h:.1f}h)"
                else:
                    # 次のアクティブ開始時刻を計算
                    if now.hour >= end_h:
                        next_day = now + timedelta(days=1)
                        next_start_h, _ = _hours(active_hours, next_day, country)
                        next_start = next_day.replace(
                            hour=next_start_h, minute=0, second=0, microsecond=0
                        )
                    else:
                        next_start = now.replace(
                            hour=start_h, minute=0, second=0, microsecond=0
                        )
                    wait_h = (next_start - now).total_seconds() / 3600
                    status = f"⏰ アクティブまで {wait_h:.1f}h"
                parts.append(f"{label}  {time_str}  {status}{holiday_mark}")
            except Exception:
                parts.append(f"{label}  ?")
        self.clock_var.set("\n".join(parts))
        self.root.after(1000, self._update_clocks)

    def open_tasks(self):
        TasksDialog(self.root)

    # schtasks の「前回の結果」で、失敗ではないもの
    #   0          正常終了
    #   267009     現在実行中          (0x41301)
    #   267011     まだ一度も実行していない (0x41303)
    #   -2147020576 既に実行中のインスタンスがある (0x800710E0)。常駐 watcher で普通に出る
    _SCH_OK = {"0", "267009", "267011", "-2147020576"}

    # (対象, 何をしているか)
    # ★schtasks の `Task To Run` と、呼ばれる .bat/.py の中身を **実際に読んで**書いた。
    #   「一覧に無い = やっていない と判断されても文句言えない」(2026-07-31 ユーザー指摘) ので、
    #   仕入元と対象範囲まで書く。全商品なのか一部なのかが分からないのが一番困る。
    # ★2026-08-02: 表に無いタスクを「—」で静かに通していた。
    #   実害: 8/2 に登録した `iMakCatalog_OpcgDumpRefresh` が担当者「—」で末尾に落ち、
    #   何をする task なのか誰にも分からない状態でパネルに並んでいた。
    #   タスクを登録したのに説明を書き忘れる = **見えないのと同じ**なので、
    #   「—」ではなく **⚠️未登録** と出して、書けと促す。
    _SCH_UNKNOWN = ("⚠️未登録", "—", "★このタスクの説明が無い。control_panel.py の _SCH_DESC に追記すること")

    _SCH_DESC = {
        # (担当者, 対象, 何をしている)
        # ★担当者はユーザーの呼び方 (グローバル CLAUDE.md の呼称に合わせる):
        #   監視くん=iMakInventory / 抽出くん=iMakHarvest / カタログ=iMakCatalog /
        #   リバイスくん=iMakRevise / 出品くん=iMakHQ
        "iMakHarvest_YodobashiSnapshot_0600": ("抽出くん", "G-shock", "ヨドバシ公式の在庫を撮る (1日3回の1回目)"),
        "iMakHarvest_YodobashiSnapshot_1400": ("抽出くん", "G-shock", "ヨドバシ公式の在庫を撮る (2回目)"),
        "iMakHarvest_YodobashiSnapshot_2200": ("抽出くん", "G-shock", "ヨドバシ公式の在庫を撮る (3回目)"),
        "iMakHarvest_YodobashiHarvest_2100": ("抽出くん", "G-shock", "ヨドバシ公式から新規商品を拾う"),
        "iMakHarvest_GshockMerge_2130": ("抽出くん", "G-shock", "Amazon + ヨドバシ公式 の2ソースを型番でまとめる"),
        "iMakInventory_Cycle": ("監視くん", "出品中 全商品 (HIGHシート)",
                                "公式(UNIQLO/GU・montbell)+メルカリ/Amazon/スニダン/ラクマ を見て 売切れたら取下げ"),
        "iMakInventory_Cycle_LOW": ("監視くん", "出品中 全商品 (LOWシート)", "同上 (公式在庫も含む)"),
        "iMakInventory_Monitor_Daily": ("監視くん", "出品中 全商品", "在庫監視の日次レポート (巡回結果のまとめ)"),
        "iMakInventory_ReverseAudit_Daily": ("監視くん", "出品中 全商品", "意図 と 実eBay状態 の突合 (取下げ漏れ検出)"),
        "iMakInventory_Backup": ("監視くん", "商品管理シート", "シート全体のバックアップ"),
        "iMakRevise_DailyAutoRevise": ("リバイスくん", "出品中 全商品", "価格の自動改定"),
        "iMakRevise_WeeklyReminder": ("リバイスくん", "—", "週次リマインダー ★巡回を定期化したので意図的に無効"),
        "iMak_Catalog_prune_missing_models": ("カタログ", "カタログ宿題", "解決済みの宿題を掃除"),
        "iMak_Catalog_set_name_audit_daily": ("カタログ", "カタログ 全カテゴリ", "set名 の整合を毎日監査"),
        "iMak Catalog Integrity Weekly": ("カタログ", "カタログ 全カテゴリ", "整合監査 + 可視化スプシ更新 (週次)"),
        "iMakCatalog_OpcgDumpRefresh": ("カタログ", "ONE PIECE 公式 dump",
                                        "公式から dump を取り直す (月次)。壊れていたら巻き戻す"),
        "iMakHQ_DispatchWatch": ("出品くん", "6担当の依頼箱", "依頼を検知して担当を自動起動する常駐watcher"),
        "iMakHQ_ClerkPatrol": ("出品くん", "6担当の依頼箱", "滞留した依頼を集計・仕分け (事務員巡回)"),
        "iMakHQ_HojuSearch_2330": ("出品くん", "PSA(TCG) + 一番くじ / 1回30件",
                                   "補URL(仕入元の予備)を夜間に検索。補0本→補1本→再仕入れ の順"),
    }

    def open_schedules(self):
        """定期スケジュールを別ウィンドウで一覧 (2026-07-31)。

        `iMak Catalog Integrity Weekly` が 07-27 から結果=255 で失敗し続けていたのに
        誰も気づいていなかった。schtasks を叩かないと分からない = 見えないのと同じ。
        """
        win = getattr(self, "_sched_win", None)
        if win is not None and tk.Toplevel.winfo_exists(win):
            win.lift()
            win.focus_force()
            return
        win = tk.Toplevel(self.root)
        self._sched_win = win
        win.title("⏰ 定期スケジュール")
        win.geometry(_load_geometry("schedules", "1360x620"))

        head = ttk.Frame(win, padding=8)
        head.pack(fill="x")
        self.sch_head = tk.StringVar(value="読込中…")
        ttk.Label(head, textvariable=self.sch_head, font=("", 11, "bold")).pack(side="left")
        ttk.Button(head, text="🔄 更新",
                   command=lambda: threading.Thread(
                       target=self._refresh_schedules, daemon=True).start()).pack(side="right")
        ttk.Label(head, text="🔵 正常   🟡 注意(無効/未実行)   🔴 失敗",
                  foreground="#555").pack(side="right", padx=12)

        cols = ("#", "状態", "担当者", "対象", "何をしている", "前回", "結果", "次回")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=20)
        for c, w in zip(cols, (32, 44, 96, 190, 360, 112, 92, 112)):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="w")
        tree.tag_configure("ok", background="#e8f0ff", foreground="#003366")
        tree.tag_configure("warn", background="#fff4c4", foreground="#806600")
        tree.tag_configure("ng", background="#ffd4d4", foreground="#800000")
        tree.tag_configure("hdr", background="#e0e0e0", foreground="#000000",
                           font=("", 10, "bold"))
        tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.sch_tree = tree
        threading.Thread(target=self._refresh_schedules, daemon=True).start()

    def _refresh_schedules(self):
        """schtasks を読んで一覧を作る。信号は 🔵正常 / 🟡注意 / 🔴失敗。"""
        import re
        import subprocess

        try:
            r = subprocess.run(["schtasks", "/query", "/fo", "LIST", "/v"],
                               capture_output=True, text=True,
                               encoding="cp932", errors="replace", timeout=120)
            seen = {}
            for blk in (r.stdout or "").split("\n\n"):
                d = {}
                for ln in blk.splitlines():
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        d[k.strip()] = v.strip()
                name = d.get("TaskName") or d.get("タスク名") or ""
                if not re.search(r"iMak", name, re.I):
                    continue
                seen[name.lstrip("\\")] = (
                    d.get("Last Run Time") or d.get("前回の実行時刻") or "",
                    d.get("Last Result") or d.get("前回の結果") or "",
                    d.get("Next Run Time") or d.get("次回の実行時刻") or "",
                    d.get("Scheduled Task State") or d.get("スケジュールされたタスクの状態") or "",
                )

            def _hm(s):                      # "2026/07/31 4:00:01" → "07/31 04:00"
                m = re.search(r"(\d+)/(\d+)\s+(\d+):(\d+)", s or "")
                return (f"{int(m.group(1)):02d}/{int(m.group(2)):02d} "
                        f"{int(m.group(3)):02d}:{m.group(4)}") if m else "—"

            # ★担当者ごとにまとめて並べる (2026-07-31 要望)。
            #   担当内は 名前順。担当の並びは「毎日動く順」= 業務の流れに合わせて固定。
            ORDER = ["抽出くん", "監視くん", "リバイスくん", "カタログ", "出品くん"]

            def _key(item):
                who = self._SCH_DESC.get(item[0], (_SCH_UNKNOWN[0],))[0]
                return (ORDER.index(who) if who in ORDER else len(ORDER), who, item[0])

            rows, ng, warn = [], 0, 0
            prev_who = None
            i = 0
            for name, (last, res, nxt, state) in sorted(seen.items(), key=_key):
                who, tgt, desc = self._SCH_DESC.get(name, _SCH_UNKNOWN)
                if who != prev_who:                       # 担当の切れ目に見出し行
                    rows.append(("hdr", ("", "", f"◆ {who}", "", "", "", "", "")))
                    prev_who = who
                i += 1
                if state in ("無効", "Disabled"):
                    sig, tag = "🟡 無効", "warn"
                    warn += 1
                elif res in self._SCH_OK:
                    sig, tag = "🔵 正常", "ok"
                else:
                    sig, tag = "🔴 失敗", "ng"
                    ng += 1
                rows.append((tag, (i, sig, who, tgt, desc, _hm(last), res, _hm(nxt))))
            head = (f"全 {len(seen)} 件   🔵 {len(seen) - ng - warn}   "
                    f"🟡 {warn}   🔴 {ng}" + ("   ← 要対応" if ng else ""))
        except Exception as e:                                # noqa: BLE001
            rows, head = [], f"⚠️ 取得失敗: {e}"

        def _apply():
            if getattr(self, "sch_head", None) is not None:
                self.sch_head.set(head)
            t = getattr(self, "sch_tree", None)
            if t is None or not t.winfo_exists():
                return
            t.delete(*t.get_children())
            for tag, vals in rows:
                t.insert("", "end", values=vals, tags=(tag,))

        try:
            self.root.after(0, _apply)
        except Exception:                                     # noqa: BLE001
            pass

    def _refresh_worktree_board(self):
        """`worktree_board.py` の集計を 1 行/担当 に畳んでトップに出す (2026-07-31)。

        全文はボタンから開ける CLI があるので、ここは **放置が目に入る**ことだけを狙う。
        赤 = 窓口が返す (担当宛の未処理 / 窓口宛の依頼) / 🟡 = headless下書きのレビュー待ち。
        """
        import re
        import subprocess

        try:
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "tools", "worktree_board.py")
            r = subprocess.run([sys.executable, "-X", "utf8", script],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120,
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            lines, route = [], 0
            for ln in (r.stdout or "").splitlines():
                s = ln.strip()
                # ★🔀 行を先に判定する。この行も " — " を含むので、
                #   一般の「## 名前 — 本文」パターンに先に食われる (2026-07-31 実測)
                if s.startswith("## 🔀"):
                    mm = re.search(r"(\d+)件", s)
                    route = int(mm.group(1)) if mm else 0
                    continue
                m = re.match(r"^## (.+?) — (.*)$", s)
                if m:
                    name, body = m.group(1), m.group(2)
                    # 「動きなし」以外で 要返球/窓口宛 があれば目立たせる
                    mark = "  "
                    if re.search(r"自分が返す [1-9]", body):
                        mark = "🔴"
                    elif re.search(r"窓口宛 [1-9]", body):
                        mark = "🔴"
                    elif re.search(r"レビュー待ち [1-9]", body):
                        mark = "🟡"
                    lines.append(f"{mark} {name:<12} {body}")
            if route:
                lines.append(f"🔀 ルーティング待ち {route}件 — 窓口が宛先を確認して投入")
            txt = "\n".join(lines) if lines else "(集計できませんでした)"
        except Exception as e:                                # noqa: BLE001
            txt = f"⚠️ 取得失敗: {e}"
        try:
            self.root.after(0, lambda: self.wt_var.set(txt))
        except Exception:                                     # noqa: BLE001
            pass

    def open_offer_calc(self):
        """オファー判定 HTML を生成してブラウザで開く (2026-07-31)。

        受信中の Best Offer を eBay から読み、**国・出品価格・仕入値**まで自動で埋める。
        オファーは期限が短い (実例: 受信から丸1日) ので、人が探す時間がそのまま判断の遅れになる。
        生成 → ブラウザ表示まで offer_calc.py 側でやるので、ここは起動するだけ。
        """
        import threading

        # ★HomePanel には status_var が無い (別クラスのもの)。
        #   進捗はボタン文言で出し、失敗時だけ messagebox で知らせる。
        btn = getattr(self, "offer_btn", None)

        def _label(text):
            if btn is not None:
                try:
                    self.root.after(0, lambda: btn.config(text=text))
                except Exception:                             # noqa: BLE001
                    pass

        def _run():
            script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "tools", "offer_calc.py")
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            _label("💰 取得中…")
            try:
                r = subprocess.run([sys.executable, "-X", "utf8", script],
                                   cwd=os.path.dirname(script), env=env,
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=900)
                if r.returncode != 0:
                    raise RuntimeError((r.stdout or r.stderr or "")[-300:])
            except Exception as e:                            # noqa: BLE001
                self.root.after(0, lambda: messagebox.showerror(
                    "オファー判定", f"起動に失敗しました:\n{e}"))
            finally:
                _label("💰 オファー対応")

        threading.Thread(target=_run, daemon=True).start()

    def open_mirror_pmbo(self):
        """UK/AU/CA のミラー出品に 広告10% と ベストオファー を付ける (2026-08-21)。

        ★いきなり書かない。**まず対象を数えて見せて、人が了解してから**実行する。
          3,500件規模を1件ずつ書き換える処理なので、押し間違いで走らせない。
        """
        import threading

        btn = getattr(self, "pmbo_btn", None)
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "tools", "mirror_promo_bestoffer.py")

        def _label(text):
            if btn is not None:
                try:
                    self.root.after(0, lambda: btn.config(text=text))
                except Exception:                             # noqa: BLE001
                    pass

        def _run(write):
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            args = [sys.executable, "-X", "utf8", script] + (["--write"] if write else [])
            _label("📣 実行中…" if write else "📣 数えています…")
            try:
                r = subprocess.run(args, cwd=os.path.dirname(script), env=env,
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=10800 if write else 1800)
                out = (r.stdout or "") + (r.stderr or "")
                if r.returncode not in (0, 1):
                    raise RuntimeError(out[-400:])
            except Exception as e:                            # noqa: BLE001
                self.root.after(0, lambda: messagebox.showerror(
                    "Pm/Bo", f"失敗しました:\n{e}"))
                _label("📣 Pm/Bo")
                return
            _label("📣 Pm/Bo")
            if write:
                self.root.after(0, lambda: messagebox.showinfo("Pm/Bo 完了", out[-1500:]))
                return
            # 一覧を見せて、了解が取れた時だけ本番へ
            summary = "\n".join(ln for ln in out.splitlines()
                                 if ln.strip() and not ln.startswith("→"))

            def _ask():
                if messagebox.askyesno("Pm/Bo — この内容で付けますか",
                                       summary[-1500:] + "\n\n実行しますか?"):
                    threading.Thread(target=_run, args=(True,), daemon=True).start()
            self.root.after(0, _ask)

        threading.Thread(target=_run, args=(False,), daemon=True).start()

    def open_listing(self, mode="new"):
        """新規出品 / 既存メンテ を別ウィンドウで開く（既にあれば前面表示）。"""
        win = self.listing_windows.get(mode)
        if win is not None and tk.Toplevel.winfo_exists(win):
            win.lift()
            win.focus_force()
            return
        title = "🆕 新規出品" if mode == "new" else "🔧 既存メンテ"
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry(_load_geometry(f"listing_{mode}", "1000x760"))
        win.protocol("WM_DELETE_WINDOW", lambda: self._on_close_listing(mode))
        self.listing_windows[mode] = win
        ListingPanel(win, mode=mode)

    def _on_close_listing(self, mode):
        win = self.listing_windows.get(mode)
        if win is not None:
            _save_geometry(f"listing_{mode}", win.geometry())
            win.destroy()
            self.listing_windows[mode] = None

    def refresh_dashboard(self):
        self.store_info_var.set("取得中...")
        self.tree.delete(*self.tree.get_children())
        self.month_tree.delete(*self.month_tree.get_children())
        threading.Thread(target=self._fetch_and_update, daemon=True).start()
        # 担当者の稼働状況も一緒に更新 (放置を見逃さないため)
        self.wt_var.set("読込中…")
        threading.Thread(target=self._refresh_worktree_board, daemon=True).start()

    def _fetch_and_update(self):
        import time as _time
        from datetime import datetime as _dt
        t0 = _time.time()
        # スプシ集計（高速、メイン）
        month_yyyymm = _dt.now().strftime("%Y-%m")
        try:
            sheet_counts = _fetch_consolidated_counts(month_yyyymm)
        except Exception as e:
            self.root.after(0, lambda: self.store_info_var.set(f"❌ 統合シート読込失敗: {e}"))
            return
        load_sec = _time.time() - t0
        print(f"📊 統合シート読込: {load_sec:.2f}秒")
        self._sheet_load_sec = load_sec
        self.root.after(0, lambda: self.store_info_var.set(
            f"📊 統合シート読込: {load_sec:.2f}秒（eBay API取得中…）"
        ))

        # eBay APIはバックグラウンドで取得、終わり次第 store_info を更新
        stats = {"total_active": "?", "feedback_score": "?", "feedback_percentage": "?"}

        def _fetch_stats_bg():
            try:
                token = _get_ebay_token()
                s = _fetch_seller_stats(token)
                ls = getattr(self, '_sheet_load_sec', 0)
                self.root.after(0, lambda: self.store_info_var.set(
                    f"セラー: {EBAY_SELLER} | "
                    f"Feedback: {s.get('feedback_score','?')} ({s.get('feedback_percentage','?')}%) | "
                    f"総アクティブ: {s.get('total_active','?')}件 | "
                    f"📊 シート読込: {ls:.2f}秒"
                ))
            except Exception as e:
                print(f"⚠️ eBay API失敗: {e}")
        threading.Thread(target=_fetch_stats_bg, daemon=True).start()

        total_rows = []
        month_rows = []
        reco_lines = []

        def _bar(pct):
            """進捗率に応じた絵文字バー（20分割）。色は行tagで制御。"""
            filled = pct // 5
            return "█" * filled + "░" * (20 - filled) + f"  {pct}%"

        def _color_tag(pct, target):
            if target == 0:
                return ""
            if pct >= 100:
                return "done"
            elif pct >= 66:
                return "blue"
            elif pct >= 33:
                return "yel"
            else:
                return "red"

        # スプシR列から自動取得したカテゴリを反復
        # 既知カテゴリは CATEGORY_TARGETS から、未知は DEFAULT_TARGETS を適用
        # 表示順: CATEGORY_TARGETS の定義順 → 未知カテゴリ
        ordered_cats = list(CATEGORY_TARGETS.keys())
        for cat in sheet_counts.keys():
            if cat not in ordered_cats:
                ordered_cats.append(cat)

        for label in ordered_cats:
            sc = sheet_counts.get(label, {'current': 0, 'monthly': 0})
            count = sc['current']
            month_count = sc['monthly']
            target, monthly = CATEGORY_TARGETS.get(label, DEFAULT_TARGETS)

            # 総合進捗
            lack = max(0, target - count)
            pct = min(100, int(count / target * 100)) if target else 0
            priority = "✅達成" if lack == 0 else ("🔴高" if lack > target * 0.5 else ("🟡中" if lack > target * 0.2 else "🟢低"))
            tag = _color_tag(pct, target)
            total_rows.append((label, target, count, lack, _bar(pct), priority, tag))
            if lack > target * 0.5:
                reco_lines.append(f"🔴 {label}: 目標まで{lack}件不足 → 最優先で出品")

            # 月次進捗
            mlack = max(0, monthly - month_count)
            mpct = min(100, int(month_count / monthly * 100)) if monthly else 0
            mtag = _color_tag(mpct, monthly)
            month_rows.append((label, monthly, month_count, mlack, _bar(mpct), mtag))

        def apply():
            # 総合進捗テーブル
            total_cur = sum(r[2] for r in total_rows if isinstance(r[2], int))
            total_tgt = sum(r[1] for r in total_rows if isinstance(r[1], int))
            total_lack = sum(r[3] for r in total_rows if isinstance(r[3], int))
            total_pct = min(100, int(total_cur / total_tgt * 100)) if total_tgt else 0
            for r in total_rows:
                tag = r[6]
                self.tree.insert("", "end", values=r[:6], tags=(tag,) if tag else ())
            self.tree.insert("", "end",
                values=("━━━ 合計 ━━━", total_tgt, total_cur, total_lack, _bar(total_pct), f"{total_pct}%"),
                tags=("total",))

            # 月次進捗テーブル
            m_cur = sum(r[2] for r in month_rows if isinstance(r[2], int))
            m_tgt = sum(r[1] for r in month_rows if isinstance(r[1], int))
            m_lack = sum(r[3] for r in month_rows if isinstance(r[3], int))
            m_pct = min(100, int(m_cur / m_tgt * 100)) if m_tgt else 0
            for r in month_rows:
                tag = r[5]
                self.month_tree.insert("", "end", values=r[:5], tags=(tag,) if tag else ())
            self.month_tree.insert("", "end",
                values=("━━━ 合計 ━━━", m_tgt, m_cur, m_lack, _bar(m_pct)),
                tags=("total",))

            self.store_info_var.set(
                f"セラー: {EBAY_SELLER} | "
                f"Feedback: {stats.get('feedback_score','?')} ({stats.get('feedback_percentage','?')}%) | "
                f"総アクティブ: {stats.get('total_active','?')}件 "
                f"(7カテゴリ合計: {total_cur}件 | 今月追加: {m_cur}件)"
            )
            if reco_lines:
                self._set_reco("\n".join(reco_lines), fg="#cc0000")
            else:
                self._set_reco("全カテゴリ目標達成🎉 新しいカテゴリ展開を検討", fg="#006600")
        self.root.after(0, apply)


def _kill_process_tree(proc, log=None):
    """proc とその子孫を確実に終了 (Windows: taskkill /T で子=seller_hub_view/chromedriver も殺す)。
    + 孤児化した Selenium(chromedriver) も停止 (取下再出品 --fresh-snapshot が止まらない対策)。
    注: 監視くん cron 等が同時に Selenium 巡回中だとその chromedriver も止まる (停止ボタン押下時のみ)。"""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    if proc and proc.poll() is None:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, creationflags=flags)
            else:
                proc.terminate()
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        if log:
            log("\n🛑 停止 (プロセスツリー終了)\n")
    else:
        if log:
            log("実行中スクリプトなし (Selenium が残っていれば下記で停止)\n")
    if sys.platform == "win32":
        r = subprocess.run(["taskkill", "/F", "/T", "/IM", "chromedriver.exe"],
                           capture_output=True, creationflags=flags)
        if r.returncode == 0 and log:
            log("🛑 残存 Selenium(chromedriver) も停止\n")


class ListingPanel:
    """従来の ControlPanel 相当（スクリプト一覧）。HomePanel から呼び出される。"""
    def __init__(self, root, mode="new"):
        self.root = root
        self.mode = mode  # "new"=新規出品 / "maint"=既存メンテ
        self._hoju_btns = []      # 残件をラベルに出すボタン [(widget, 元ラベル)]

        # ツールバー (共有 🛑 停止)
        toolbar = ttk.Frame(root, padding=(8, 4))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="🛑 実行中を停止", width=18,
                   command=self.stop_script).pack(side="right")
        # ★2026-08-18: 開く時は前回値を出すだけにしたので、数え直す口をここに置く。
        #   このパネルには「更新」が無く、走行後 (poll_queue) までラベルが古いままになるため。
        ttk.Button(toolbar, text="🔄 残件を数え直す (約20秒)", width=26,
                   command=self._recount_hoju).pack(side="right", padx=4)

        top_frame = ttk.LabelFrame(root, text="スクリプト一覧", padding=8)
        top_frame.pack(fill="x", padx=8, pady=(0, 4))

        canvas = tk.Canvas(top_frame, height=470, highlightthickness=0)
        scrollbar = ttk.Scrollbar(top_frame, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        def _fit_canvas(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 内容が canvas(470) より低い場合(新規モード等)は内容高さまで縮め、下の空白を詰めて上段寄せ。
            # 高い場合(既存メンテ)は 470 でクリップしスクロール。
            canvas.configure(height=min(scroll_frame.winfo_reqheight(), 470))
        scroll_frame.bind("<Configure>", _fit_canvas)
        _win_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        # 内側フレームを canvas 幅いっぱいに広げる (= 右側の空白を無くし全幅レイアウトに)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_win_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        # マウスホイールでスクロール (カーソルが領域内のときだけ)
        def _on_wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # 5/12 構成変更: カテゴリ別 Labelframe + 新規/再出品 2ボタン + Utility 単独ボタン
        # - 新規ボタン: verified=True → 青、それ以外 → 黒 (既存ルール維持)
        # - 再出品ボタン: 黒
        # - verified カテゴリを先頭にまとめる (ユーザー要望)
        self.param_entries = {}
        self._run_log = None
        self._run_log_path = None   # 完走後の要約はログ欄でなくこのファイルを読む(2026-08-03)

        # 1) SCRIPTS をカテゴリ別に分類
        categories: dict[str, dict[str, int]] = {}  # {category: {type: script_idx}}
        utilities: list[int] = []
        for i, script in enumerate(SCRIPTS):
            cat = script.get("category")
            typ = script.get("type", "new")
            if cat is None or typ == "utility":
                utilities.append(i)
            else:
                categories.setdefault(cat, {})[typ] = i
            self.param_entries[i] = {}

        # verified=True カテゴリ (= 新規が青文字) を先頭にソート
        def _cat_verified(cat_name: str) -> int:
            new_idx = categories[cat_name].get("new")
            if new_idx is None:
                return 1
            return 0 if SCRIPTS[new_idx].get("verified", False) else 1
        cat_order = sorted(categories.keys(), key=_cat_verified)

        # 2) utility をグループ分類 (cmd のスクリプト名で判定)
        def _ugroup(idx):
            cmd = " ".join(SCRIPTS[idx].get("cmd", []))
            if "csv_auditor" in cmd:
                return "audit"     # 🔍 出品前チェック (新規パネルに表示)
            if any(s in cmd for s in ("listing_funnel", "demand_winners", "funnel_diff")):
                return "analyze"   # 📊 分析 (Plan/Check)
            # ★2026-09-03: 棚は①②で置き場所が違う。①は「買えない & 需要ゼロ」なので
            #   在庫なしの整理と同じ棚、②は「在庫はあるが売れない」ので在庫ありの棚。
            #   混ぜると重い方(②)を軽い気持ちで押すことになる (ユーザー指摘)。
            if "shelf_evict.py" in cmd:
                return "evict2" if "2" in cmd.split("--tier")[-1][:3] else "oos"
            if any(s in cmd for s in ("mercari_psa_resource", "restock_worklist", "cull_end")):
                return "oos"       # 在庫なし 再仕入れ(RESTOCK) / 整理(CULL)
            if any(s in cmd for s in ("casio_finder", "montbell_outlet_scraper", "mercari_scout.py")):
                return "discover"  # 新規ネタ探し
            # ★2026-07-28: 出品直後に押す補URL2ボタン(🆕検索/🩹確証)は **新規出品パネル**に置く。
            # 出品→itemID書込→補URL確保 は一連の流れなので、既存メンテ側に離すと導線が切れる
            # (ユーザー指示)。件数感/夜間検索は定常運用なのでメンテ側に残す。
            if "psa_hoju_fill.py" in cmd and "--limit=15" in cmd:
                return "hoju"      # 🆕 は出品直後専用 = 新規パネルのみ
            # ★2026-08-22: 一番くじの補URL2ボタンも **新規出品パネル**に置く
            #   (ユーザー指示)。PSA と同じ導線 = 出品→itemID→補URL確保 の並び。
            if "ichibankuji_restock.py" in cmd and ("prefetch-live" in cmd or "hoju" in cmd):
                return "hoju"
            # 在庫あり listing を直す: 取下再出品①②③(NO_SEARCH) / ✏️タイトル(NO_CLICK) / 💲価格(NO_CONVERT)
            if any(s in cmd for s in ("relist_from_funnel", "relist_add_from_pending",
                                      "relist_writeback", "dump_us_qty1_sku",
                                      "noclick_targets", "noconvert_pricedown")):
                return "relist"
            return "report"
        ug = {"analyze": [], "oos": [], "discover": [], "relist": [], "report": [],
              "audit": [], "hoju": [], "evict2": []}
        for idx in utilities:
            ug[_ugroup(idx)].append(idx)

        # 共通: (label, idx) のリストを ncol 列グリッドで描画 (compact=詰めた配置)
        def _grid_named(parent, items, ncol=4, compact=False):
            # height=2 で2行ぶんの高さを確保 (ラベルが折返しても見切れない)。width は最小値=
            # columnconfigure(weight) と sticky="nsew" で実幅は親いっぱいに伸びる。
            # ★2026-08-16 ユーザー指示「ラベルがボタンからはみ出ている」。
            #   2行では残件ラベル(最大4行)が見切れる → 3行ぶん確保し、折返し幅も広げる。
            #   残件つきボタンは refresh_hoju_badge が行数に合わせて更に伸ばす。
            w, h, pad, wl = (16, 3, 2, 170) if compact else (18, 3, 4, 250)
            ncol = max(1, min(ncol, len(items)))  # 項目数より多い列は作らない (右の空セル防止)
            for col in range(ncol):
                parent.columnconfigure(col, weight=1, uniform=f"g{id(parent)}")
            for k, (text, idx) in enumerate(items):
                # ★2026-08-16 ユーザー指示: **既定は全部黒**。青は「今押すといい」だけに使う
                #   (色が意味を持たないと、どれを押せばいいか分からない)。
                #   青にするのは残件ラベルを持つボタンだけで、refresh_hoju_badge が
                #   「押して出てくる件数 > 0」の時に切替える。
                color = "black"
                b = tk.Button(parent, text=text, font=("", 9, "bold"), fg=color,
                              width=w, height=h, wraplength=wl, justify="center",
                              command=lambda i=idx: self.run_script(i))
                b.grid(row=k // ncol, column=k % ncol, padx=pad, pady=pad, sticky="nsew")
                # ★残件をラベルに出すボタンは参照を持つ (2026-08-09 ユーザー要望)。
                #   ログ末尾まで読まないと残件が分からず、押す前に「あと何回か」が見えなかった。
                # ★2026-08-22 ユーザー要望「詳細はヒントテキストにしてラベルはシンプルに」
                _tip = SCRIPTS[idx].get("tip")
                _set_tip = _attach_tip(b, _tip) if _tip else None
                _bg = SCRIPTS[idx].get("badge")
                if _bg:                      # ★badge を持つボタンは全部登録 (newcand も)
                    self._hoju_btns.append((b, text, _bg, _set_tip, _tip or ""))

        if self.mode == "new":
            # ===== 🆕 新規出品 (カテゴリ名ラベルの大ボタン・間隔詰め) =====
            new_sec = ttk.LabelFrame(scroll_frame, text="🆕 新規出品 — カテゴリを選んで出品", padding=6)
            new_sec.pack(fill="x", padx=4, pady=(4, 8))
            cat_grid = ttk.Frame(new_sec)
            cat_grid.pack(fill="x")
            n_cat_cols = 4
            for col in range(n_cat_cols):
                cat_grid.columnconfigure(col, weight=1, uniform="catcol")
            gi = 0
            for cat_name in cat_order:
                new_idx = categories[cat_name].get("new")
                if new_idx is None:
                    continue
                # ★2026-08-18: 1セル = カテゴリボタン (+ あれば 🤖自動)。
                #   カテゴリは type ごとに1つしか持てないので、自動は **別 type** で登録する
                #   (同じ "new" で足すと後勝ちでカテゴリボタンを乗っ取る。実際に一度やった)
                cell = ttk.Frame(cat_grid)
                cell.grid(row=gi // n_cat_cols, column=gi % n_cat_cols,
                          padx=2, pady=2, sticky="nsew")
                auto_idx = categories[cat_name].get("auto")
                # ★2026-08-16: カテゴリも既定は黒 (色は「今押すといい」の意味だけに使う)
                tk.Button(cell, text=cat_name, font=("", 12, "bold"), fg="black",
                          width=16 if auto_idx is None else 11, height=2,
                          wraplength=170, justify="center",
                          command=lambda idx=new_idx: self.run_script(idx)).pack(
                    side="left", fill="both", expand=True)
                if auto_idx is not None:
                    tk.Button(cell, text=SCRIPTS[auto_idx]["label"], font=("", 10, "bold"),
                              fg="black", width=6, height=2, wraplength=70, justify="center",
                              command=lambda idx=auto_idx: self.run_script(idx)).pack(
                        side="left", fill="both")
                gi += 1
            if ug["discover"]:
                disc = ttk.LabelFrame(new_sec, text="発見・巡回 (新規ネタ探し)", padding=4)
                disc.pack(fill="x", pady=(8, 0))
                _grid_named(disc, [(SCRIPTS[i]["label"], i) for i in ug["discover"]])
            if ug["audit"]:
                aud = ttk.LabelFrame(new_sec, text="🔍 出品前チェック (CSV生成後に実行)", padding=4)
                aud.pack(fill="x", pady=(8, 0))
                _grid_named(aud, [(SCRIPTS[i]["label"], i) for i in ug["audit"]])
            if ug["hoju"]:
                hj = ttk.LabelFrame(
                    new_sec, text="🔗 出品後 補URL確保 (入稿 → itemID書込 の後に実行)", padding=4)
                hj.pack(fill="x", pady=(8, 0))
                # 🩹(昼確認)は **メンテ側の定常消化でも使う**ので実体はメンテに残し、
                # 新規パネルには同じ idx を並べて出す(導線を切らないための併置。2026-07-28)。
                _confirm_idx = [i for i, sc in enumerate(SCRIPTS)
                                if "psa_hoju_fill.py" in " ".join(sc.get("cmd", []))
                                and "confirm" in sc.get("cmd", [])]
                # ★2026-08-22: 並びが PSA / くじ / くじ / PSA になっていた (ユーザー指摘)。
                #   `ug["hoju"]` の後ろに PSA の昼確認を足していたため。**系統ごとに固める**。
                _order = ([i for i in ug["hoju"] if "ichibankuji_restock.py" not in
                           " ".join(SCRIPTS[i].get("cmd", []))]
                          + _confirm_idx
                          + [i for i in ug["hoju"] if "ichibankuji_restock.py" in
                             " ".join(SCRIPTS[i].get("cmd", []))])
                _grid_named(hj, [(SCRIPTS[i]["label"], i) for i in _order])
        else:
            # ===== 🔧 既存メンテ =====
            REPORTS_DIR = r"C:/dev/iMak_data/seller_hub/reports"

            def _open_sellerhub():
                import webbrowser
                webbrowser.open("https://www.ebay.com/sh/ovw")

            def _open_reports():
                os.makedirs(REPORTS_DIR, exist_ok=True)
                os.startfile(REPORTS_DIR)

            # 手順ガイド
            guide = ttk.LabelFrame(scroll_frame, text="📋 レポート準備", padding=6)
            guide.pack(fill="x", padx=4, pady=(4, 6))
            hb = ttk.Frame(guide)
            hb.pack(anchor="w")
            tk.Button(hb, text="🌐 レポートDL", font=("", 10, "bold"),
                      command=_open_sellerhub).pack(side="left", padx=(0, 6))
            tk.Button(hb, text="📁 reports フォルダを開く", font=("", 10, "bold"),
                      command=_open_reports).pack(side="left")
            tk.Label(
                guide, justify="left", anchor="w", font=("Yu Gothic UI", 10),
                text=("Seller Hub で下記5レポートをDL → 📁reports フォルダに置く:\n"
                      "  ・eBay-all-active-listings\n"
                      "  ・ebay-all-orders-report\n"
                      "  ・eBay-unsold-listings-report\n"
                      "  ・Listing quality report\n"
                      "  ・eBay-promoted-listing-general-listing-report (露出をorganic+PL累計で正す)"),
            ).pack(anchor="w", pady=(4, 0))

            # ② レポート鮮度: 各レポートの「内容の日付」が何日前か。古いまま判断する事故を防ぐ。
            #   日付はファイル名から読む(eBay が report 生成日を埋める)。mtime はフォルダに
            #   置き直すと更新され実態より新しく見えるので使わない。
            def _file_report_date(path):
                import datetime as _dt
                b = os.path.basename(path)
                m = re.search(r"(\d{4})-(\d{2})-(\d{2})", b)            # YYYY-MM-DD (active/orders/unsold)
                if m:
                    return _dt.date(int(m[1]), int(m[2]), int(m[3]))
                m = re.search(r"(\d{2})_(\d{2})_(\d{4})", b)            # MM_DD_YYYY (quality)
                if m:
                    return _dt.date(int(m[3]), int(m[1]), int(m[2]))
                return _dt.date.fromtimestamp(os.path.getmtime(path))   # fallback: mtime

            def _report_freshness():
                import glob as _glob
                import datetime as _dt
                pats = [("active", "eBay-all-active-listings-report*"),
                        ("orders", "ebay-all-orders-report*"),
                        ("unsold", "eBay-unsold-listings-report*"),
                        ("quality", "Listing quality report*")]
                today = _dt.date.today()
                parts, worst = [], 0
                for nm, pat in pats:
                    # ★2026-08-25: レポートは **日付フォルダの中**に置かれている
                    #   (reports/20260823/eBay-all-active-... 等)。直下しか見ていなかったので
                    #   4種とも 0件 = 常に「✗無し」で、鮮度が一度も更新されなかった。
                    #   どこに置いても拾えるよう再帰で探す。
                    fs = _glob.glob(os.path.join(REPORTS_DIR, "**", pat), recursive=True)
                    if not fs:
                        parts.append(f"{nm} ✗無し")
                        worst = 999
                        continue
                    newest = max(_file_report_date(p) for p in fs)
                    ago = (today - newest).days
                    parts.append(f"{nm} {ago}日前")
                    worst = max(worst, ago)
                return "📅 レポート鮮度:  " + "  /  ".join(parts), worst
            try:
                _fresh_txt, _worst = _report_freshness()
                _fg = "red" if _worst >= 4 else "#0a0"
                _tip = "  ← 古い。再DL推奨" if _worst >= 4 else ""
                tk.Label(guide, anchor="w", font=("Yu Gothic UI", 9, "bold"),
                         fg=_fg, text=_fresh_txt + _tip).pack(anchor="w", pady=(4, 0))
            except Exception:
                pass

            # 📊 分析 (押すと結果ファイルが開く)
            ana = ttk.LabelFrame(scroll_frame, text="📊 分析 (押すと結果ファイルが開く)", padding=4)
            ana.pack(fill="x", padx=4, pady=(4, 0))
            _grid_named(ana, [(SCRIPTS[i]["label"], i) for i in ug["analyze"]])

            # ファネル世代 + 効果測定の準備状況: 「前回いつファネルを回したか」「URL突合できる2世代が
            #   揃ったか」を可視化。次にいつ押せばいいか分からない問題への対策。supply_url が両世代に
            #   入って初めて relist(取下再出品=id/title変) 効果が📉効果測定で測れる。
            def _funnel_generations():
                import glob as _glob
                import csv as _csv
                import datetime as _dt
                fs = _glob.glob(os.path.join(WORKSPACE, "iMakHQ", "funnel_output", "funnel_*.csv"))
                gens = []
                for p in fs:
                    m = re.search(r"funnel_(\d{4})(\d{2})(\d{2})", os.path.basename(p))
                    if m:
                        gens.append((_dt.date(int(m[1]), int(m[2]), int(m[3])), p))
                gens.sort(key=lambda x: x[0])

                def _has_url(path):
                    try:
                        with open(path, encoding="utf-8") as f:
                            rd = _csv.DictReader(f)
                            if "supply_url" not in (rd.fieldnames or []):
                                return False
                            return any((r.get("supply_url") or "").strip() for r in rd)
                    except Exception:
                        return False
                return [(d, _has_url(p)) for d, p in gens[-2:]]
            try:
                _g = _funnel_generations()
                if not _g:
                    _ftxt, _ffg = "📉 ファネル世代: まだ無し → ファネル分析を実行", "#444"
                else:
                    _ds = "  ←  ".join(f"{d:%m/%d}({'URL✓' if u else 'URL✗'})" for d, u in reversed(_g))
                    if len(_g) >= 2 and _g[-1][1] and _g[-2][1]:
                        _msg, _ffg = "効果測定OK (両世代URL✓=relist突合可)", "#0a0"
                    elif _g[-1][1]:
                        _msg, _ffg = "あと1回でペア成立 (次回ファネルから relist効果測定が有効)", "#c80"
                    else:
                        _msg, _ffg = "最新にURL無 → ネット接続環境でファネル再実行を", "red"
                    _ftxt = f"📉 ファネル世代:  {_ds}   {_msg}"
                # ana は _grid_named で grid 配置 → 同フレームに pack 不可 (混在TclError)。
                # ③進捗行と同様 scroll_frame に直接 pack する。
                tk.Label(scroll_frame, anchor="w", font=("Yu Gothic UI", 9, "bold"),
                         fg=_ffg, text=_ftxt).pack(anchor="w", padx=4, pady=(2, 0))
            except Exception:
                pass

            # 🔧 在庫あり / 📦 在庫なし を全幅で縦積み (横2分割の窮屈・ラベル見切れを解消)
            relist_items = [(SCRIPTS[i]["label"], i) for i in ug["relist"]]
            relist_items += [(f"{cat} 再出品", categories[cat]["relist"])
                             for cat in cat_order if categories[cat].get("relist") is not None]
            d1 = ttk.LabelFrame(scroll_frame, text="🔧 在庫あり — 直す (検索/タイトル/価格) 出品≥21日", padding=4)
            d1.pack(fill="x", padx=4, pady=(6, 0))
            # 3列: 上段①②③ / 下段✏️タイトル改修(①下)・💲値下げ余地(②下) が縦に揃う
            _grid_named(d1, relist_items, ncol=3)
            # ★2026-09-03: 在庫ありを「直す」と「落とす」で分ける。同じ枠に置くと、
            #   取り返しのつかない End を、直すのと同じ気持ちで押すことになる。
            if ug["evict2"]:
                d1b = ttk.LabelFrame(
                    scroll_frame,
                    text="🪑 在庫あり — 落として枠を空ける (取り返しがつかない・候補CSVを見てから)",
                    padding=4)
                d1b.pack(fill="x", padx=4, pady=(6, 0))
                _grid_named(d1b, [(SCRIPTS[i]["label"], i) for i in ug["evict2"]], ncol=3)
            d2 = ttk.LabelFrame(scroll_frame, text="📦 在庫なし — 再仕入れ / 整理", padding=4)
            d2.pack(fill="x", padx=4, pady=(6, 0))
            # d2 は 在庫補充(pack)を入れ子にするので、oosボタンは内側Frame(grid)に包む
            # (同一親で grid と pack を混在させると tkinter が描画失敗する。2026-07-01 修正)
            d2_oos = ttk.Frame(d2)
            d2_oos.pack(fill="x")
            _grid_named(d2_oos, [(SCRIPTS[i]["label"], i) for i in ug["oos"]], ncol=4)

            # ③ 在庫なし進捗: CULL停止の残件数(約何回分) と RESTOCK再仕入れ(US)商品数。
            def _oos_progress():
                import glob as _glob
                import csv as _csv
                fs = _glob.glob(os.path.join(WORKSPACE, "iMakHQ", "funnel_output", "funnel_*.csv"))
                if not fs:
                    return None
                rows = list(_csv.DictReader(open(max(fs, key=os.path.getmtime), encoding="utf-8")))

                def _fl(r):
                    return (r.get("flags") or "").split("|")

                def _ai(x):
                    try:
                        return int(float(x))
                    except (ValueError, TypeError):
                        return 0
                cull = sum(1 for r in rows if "CULL" in _fl(r) and _ai(r.get("age_days")) >= 21)
                restock = len({(r.get("title") or "").lower() for r in rows
                               if "RESTOCK" in _fl(r) and r.get("site") == "US"})
                return cull, restock
            try:
                _prog = _oos_progress()
                if _prog:
                    _cull_n, _rs_n = _prog
                    # ★1回あたりの件数は cull_end 側が正 (2026-08-23 に 50→200)。
                    #   ここに数字を書き写すと、片方だけ変えた時に嘘の回数が出る。
                    try:
                        import cull_end as _ce
                        _cap = _ce.CAP
                    except Exception:                              # noqa: BLE001
                        _cap = 200
                    _runs = -(-_cull_n // _cap)  # ceil
                    tk.Label(scroll_frame, anchor="w", font=("Yu Gothic UI", 9, "bold"),
                             fg="#444", text=(f"   🛒 RESTOCK再仕入れ(US) {_rs_n}商品   "
                                              f"｜   🧹 CULL停止 残 {_cull_n}件 "
                                              f"({_cap}件/回 = 約{_runs}回分)")
                             ).pack(anchor="w", padx=4, pady=(2, 0))
            except Exception:
                pass

            if ug["report"]:
                # 在庫補充 は 在庫なし(d2)枠の中に入れ子(2026-07-01)。3列=PSA再仕入れ3が1行目・一番くじ①②が2行目。
                rep = ttk.LabelFrame(d2, text="📦 在庫補充", padding=4)
                rep.pack(fill="x", padx=4, pady=(6, 0))
                _grid_named(rep, [(SCRIPTS[i]["label"], i) for i in ug["report"]], ncol=3)

        # 状態ライン
        status_frame = ttk.Frame(root)
        status_frame.pack(fill="x", padx=8)
        self.status_var = tk.StringVar(value="待機中")
        ttk.Label(status_frame, textvariable=self.status_var, foreground="blue", font=("", 10, "bold")).pack(side="left")
        self.now_processing = tk.StringVar(value="")
        ttk.Label(status_frame, textvariable=self.now_processing, foreground="#0066cc").pack(side="left", padx=20)
        ttk.Button(status_frame, text="ログクリア", command=self.clear_log).pack(side="right")

        # ログ
        log_frame = ttk.LabelFrame(root, text="実行ログ（着色: 青=商品/橙=API/緑=eBay/赤=エラー/灰=スキップ）", padding=4)
        log_frame.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        self.log = scrolledtext.ScrolledText(log_frame, wrap="word", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)

        # tag定義
        for _, name, color in LOG_TAGS:
            self.log.tag_config(name, foreground=color)
        self.log.tag_config("bold", font=("Consolas", 9, "bold"))

        self.proc = None
        self.queue = queue.Queue()
        self.root.after(100, self.poll_queue)
        # ★補URL の残件は **前回値をそのまま出す** (計算しない = 一瞬で開く)。
        #   数え直しは 🔄 を押した時と走行の後。2026-08-18 実測: 数え直すと 18秒 固まる。
        self.root.after(300, self.show_cached_hoju_badge)

    _HOJU_BADGE_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "review_logs", "hoju_badge_cache.json")

    def _hoju_badge_cache(self, save=None):
        """残件ラベルの前回値。Sheets API が一時的に弾いた時に「不明」で潰さないため。

        save を渡せば保存、渡さなければ読み出し (無ければ None)。
        """
        try:
            if save is not None:
                os.makedirs(os.path.dirname(self._HOJU_BADGE_CACHE), exist_ok=True)
                with open(self._HOJU_BADGE_CACHE, "w", encoding="utf-8") as f:
                    json.dump(save, f, ensure_ascii=False)
                return None
            with open(self._HOJU_BADGE_CACHE, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) and d else None
        except Exception:                                         # noqa: BLE001
            return None

    def _recount_hoju(self):
        """🔄 押下: 数え直す。押した本人は待つと分かっているので同期でよい。"""
        try:
            self.status_var.set("残件を数え直しています…")
            self.root.update_idletasks()
        except Exception:                                         # noqa: BLE001
            pass
        try:
            self.refresh_hoju_badge()
        finally:
            try:
                self.status_var.set("待機中")
            except Exception:                                     # noqa: BLE001
                pass

    def paint_hoju_badge(self, by_kind, act_kind=None):
        """数えた結果を **色とヒント** に出す (計算しない・純粋な描画)。

        ★2026-08-22 ユーザー指示「ラベルはシンプルにして、押すべき時は青色に。
          件数や詳細はヒントテキストに移行」。
          以前は件数をラベルに焼いていたので、ボタンが4〜7行に伸びて何のボタンか
          読めなかった。**色 = 今押すべきか / ヒント = 何件あるか**に分けた。

        ★2026-08-31 例外: 「棚を入れ替える」ボタンだけ、ユーザーが明示でラベルにも
          件数・金額を求めた (`shelf_evict_label`)。他のボタンは上の決定のまま変えない。
        """
        act_kind = act_kind or {}
        for b, base, kind, set_tip, tip in self._hoju_btns:
            try:
                extra = (by_kind.get(kind + "_label") or "").strip() if kind == "shelf_evict" else ""
                text = f"{base}\n{extra}" if extra else base
                b.config(text=text, height=(5 if extra else 3),
                         fg=("#0066cc" if act_kind.get(kind) else "black"))
                if set_tip:
                    n = (by_kind.get(kind) or "").strip()
                    set_tip((tip + chr(10) + chr(10) + n) if n else tip)
            except Exception:                                     # noqa: BLE001
                pass

    def show_cached_hoju_badge(self):
        """前回の数字をそのまま出す (計算しない = 一瞬)。

        ★2026-08-18: 開いた時に数え直していたので **18秒 画面が固まっていた**
          (書いた当時は実測3秒。データが増えて伸びた)。ホーム・新規出品・既存メンテの
          どれを開いても同じ待ちが出ていた。
          開く時は前回値、数え直すのは 🔄 を押した時と走行の後 (どうせ画面を見ていない時間)。
          裏スレッドには回さない — 過去に4回失敗している (Tk はスレッドセーフでない)。
        """
        cached = self._hoju_badge_cache() or {}
        # ★2026-08-22: ボタンの種類が増えた時、前回値には入っていないので
        #   **何も出ないまま**になる (一番くじを足した日に実際に起きた)。
        #   前回値が無い種類は「まだ数えていません」と書く。空欄にしない。
        out = {}
        for _b, _base, kind, _st, _tip in self._hoju_btns:
            v = cached.get(kind)
            out[kind] = (v + "\n※前回値 (🔄 で更新)") if v else "\nまだ数えていません (🔄 で更新)"
            # ★2026-08-31: 棚入れ替えボタンのラベル (件数/金額) も前回値をそのまま出す。
            if kind == "shelf_evict":
                out[kind + "_label"] = cached.get(kind + "_label") or "…"
        if out:
            self.paint_hoju_badge(out)

    def refresh_hoju_badge(self):
        """補URL の残件をボタンのラベルに出す (2026-08-09 ユーザー要望)。

        ★同期で数えて焼き込む。スレッド + after ポーリングで4回失敗した:
          Tk はスレッドセーフでなく、ワーカーからの after() は Windows で黙殺される。
          メインスレッドのポーリングに寄せても、初期表示がシグナルを食う / 引数付きの
          再帰予約が再スケジュールされない、と別の穴が出続けた。
          所要は実測 3秒。起動が3秒延びるだけで、確実に出るほうを採る。

        ★重い計算はしない。目視で片づく正確な残件は絵柄の照合まで通す必要があり
          実測 10分近くかかる (= ラベルには載せられない)。status_now と同じ安い母数を出す。
        """
        if not self._hoju_btns:
            return
        # ★2026-08-15: 🌱(捨てた候補→新規出品の種) の残件も同じ subprocess で数える
        #   (ユーザー要望「押すかどうかの判断になる」)。片方が転んでも
        #   もう片方のラベルは出す。
        code = (
            "import sys,json;sys.path.insert(0,r'%s')\n"
            "import psa_hoju_fill as H\n"
            "d={'hoju':H.count_workload()}\n"
            "try:\n"
            "    import newcand_confirm as N\n"
            "    d['newcand']=N.count_workload()\n"
            "except Exception as e:\n"
            "    d['newcand']={'error':'%%s: %%s'%%(type(e).__name__,e)}\n"
            # ★2026-08-22: 一番くじも同じ subprocess で数える (ユーザー要望)。
            #   片方が転んでも もう片方のヒントは出す。
            "try:\n"
            "    import ichibankuji_restock as KJ\n"
            "    d['kuji']=KJ.count_workload()\n"
            "except Exception as e:\n"
            "    d['kuji']={'error':'%%s: %%s'%%(type(e).__name__,e)}\n"
            # ★2026-08-24: 取下げ(CULL)の残数も同じ subprocess で数える。
            #   材料は funnel CSV と 済み台帳だけで **eBay は1回も叩かない**
            #   (同日に API の1日上限で取下げが5時間止まったため、表示のために使わない)。
            "try:\n"
            "    import cull_end as CE\n"
            "    d['cull']=CE.count_workload()\n"
            "except Exception as e:\n"
            "    d['cull']={'error':'%%s: %%s'%%(type(e).__name__,e)}\n"
            # ★2026-08-31: 棚入れ替え (shelf_evict) の残数も同じ subprocess で数える。
            #   count_workload は eBay を叩かない (live キャッシュがあれば使う・無ければ
            #   その旨をヒントに出す。cull_end と同じ理由で表示のために API 枠を使わない)。
            "try:\n"
            "    import shelf_evict as SE\n"
            "    d['shelf']=SE.count_workload()\n"
            "except Exception as e:\n"
            "    d['shelf']={'error':'%%s: %%s'%%(type(e).__name__,e)}\n"
            # ★2026-08-31 ユーザー要望「放置しちゃう」: 売れた分の補充も同じ subprocess で数える。
            #   count_workload は eBay を叩かない (live キャッシュがあれば使う・無ければ
            #   unknown として数え、押すまで actionable と言い切らない)。
            "try:\n"
            "    import sold_restock as SR\n"
            "    d['restock']=SR.count_workload()\n"
            "except Exception as e:\n"
            "    d['restock']={'error':'%%s: %%s'%%(type(e).__name__,e)}\n"
            # ★2026-09-01 ユーザー要望「ボタンが増えて何をしたらいいか分からない」:
            #   既存メンテのヒント無し 6個も同じ subprocess で数える。
            #   どれも **スクレイプも eBay API も使わない** (材料は funnel CSV とスプシ)。
            "try:\n"
            "    import psa_resource_gate as PG\n"
            "    d['psa_gate']=PG.count_workload()\n"
            "except Exception as e:\n"
            "    d['psa_gate']={'error':'%%s: %%s'%%(type(e).__name__,e)}\n"
            # RESTOCK確定タブは ♻ と 🔄 の両方が見るので **1回だけ読んで渡す**。
            "try:\n"
            "    from sheet_io import read_tab as _rt\n"
            "    _rk=_rt('RESTOCK確定')\n"
            "except Exception as e:\n"
            "    _rk=None\n"
            "try:\n"
            "    import psa_restock_build as RB\n"
            "    d['restock_build']=RB.count_workload(_rk)\n"
            "except Exception as e:\n"
            "    d['restock_build']={'error':'%%s: %%s'%%(type(e).__name__,e)}\n"
            "try:\n"
            "    import psa_restock_writeback as RW\n"
            "    d['restock_wb']=RW.count_workload(_rk)\n"
            "except Exception as e:\n"
            "    d['restock_wb']={'error':'%%s: %%s'%%(type(e).__name__,e)}\n"
            "print(json.dumps(d))"
            % os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
        )
        # ★2026-08-10: 「(残件 取得できず)」とだけ出て **理由が分からない**状態だった。
        #   例外を握り潰していたので、原因が exit code なのか JSON なのか判別できない。
        #   → 理由を短くラベルに出し、全文は log に流す。1回だけ retry する
        #     (起動直後は他の集計と Sheets API が競合して弾かれることがあるため)。
        err_reason = ""
        w = None
        for attempt in (1, 2):
            try:
                r = subprocess.run([sys.executable, "-X", "utf8", "-c", code],
                                   capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=180,
                                   # ★2026-09-01: 件数を数えるだけの走行なので、同じタブを
                                   #   何度も読まない (Sheets の 1分あたり読み取り上限 429 対策)。
                                   #   書いてから読み直す通常の走行には効かせない。
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8",
                                            SHEET_READ_MEMO="1"))
                out = (r.stdout or "").strip()
                if r.returncode != 0 or not out:
                    tail = (r.stderr or "").strip().splitlines()
                    err_reason = (tail[-1][:60] if tail else f"exit={r.returncode} 出力なし")
                    raise RuntimeError(err_reason)
                w = json.loads(out.splitlines()[-1])
                err_reason = ""
                break
            except subprocess.TimeoutExpired:
                err_reason = "180秒でタイムアウト"
            except json.JSONDecodeError:
                err_reason = "JSON として読めない出力"
            except Exception as e:                                # noqa: BLE001
                err_reason = err_reason or f"{type(e).__name__}: {e}"[:60]
            if attempt == 1:
                time.sleep(2)                                     # 競合していれば2秒で解ける
        try:
            if w is None:
                raise RuntimeError(err_reason or "不明")
            w0 = w                       # ★上書き前の全体 (kuji もここから取る)
            w, nc = w["hoju"], (w.get("newcand") or {})
            tot = w["targets"]
            # ★2026-08-09: **押したら何件できるか**を出す。母数を出してはいけない。
            #   直前まで「目視待ち32件」と出して実際に出るのは3件だった (足切り8段を
            #   一切通していない母数だったため)。件数は段取りを決めるために見るもので、
            #   10倍ずれる数字はラベルとして意味がない、というユーザー指摘。
            #   検索側も同じで、「未探索10件」の8件は card番号が無く**検索できない**。
            s, cf = w["search"], w["confirm"]
            # ★2026-08-21: 件数だけ出すと「押さないといけないのか」と思わせる (ユーザー指摘)。
            #   slice2 は **毎晩23:30 に自動で走る**ので、押す必要は無い。
            #   ただし自動が止まっている時は押す必要があるので、その時だけそう出す。
            nightly = nightly_search_state()
            if nightly["ok"]:
                s_txt = "\n夜間%sに自動 (押す必要なし)\n今夜の対象 %s件" % (nightly["at"], s["can"])
            else:
                s_txt = "\n⚠️ 夜間自動が止まっています (%s)\n押して検索できる %s件" % (
                    nightly["why"], s["can"])
            if s["no_cardno"]:
                s_txt += "\n※探索不能 %s件 (番号なし)" % s["no_cardno"]
            c_txt = "\n目視できる %s件 (補0本 %s件のうち)" % (cf["ready"], tot)
            if cf["unjudged"]:
                c_txt += "\n※絵柄が未判定 %s件 (押すと判定)" % cf["unjudged"]
            # ★2026-08-14: 0件の時に**理由**を出す。件数だけだと「候補は37件ある」のに
            #   押して空振りする (status の安い母数と、足切り後の実数が食い違うため)。
            #   何で消えたのかが分かれば、次に何をすべきかが決まる。
            # ★2026-08-15: 内部の理由名を並べても読めない (ユーザー指摘「ん?ってなる」)。
            #   **「市場にその版が無い(待ち)」と「手が打てる」** の2分類で出す。
            #   語彙は psa_hoju_fill.split_blocked が SSOT (status と同じ言葉になる)。
            if not cf["ready"] and not cf["unjudged"]:
                try:
                    import psa_hoju_fill as _H
                    _sp = _H.split_blocked(cf.get("blocked") or {})
                    c_txt += "\n※押しても0件"
                    if _sp["wait"]:
                        c_txt += "\n  市場にその版が無い %s件 (%s)" % (
                            _sp["wait"],
                            " / ".join("%s%s" % (n, m) for m, n in _sp["wait_detail"][:3]))
                    if _sp["act"]:
                        c_txt += "\n  手が打てる %s件 (%s)" % (
                            _sp["act"],
                            " / ".join("%s%s" % (n, m) for m, n in _sp["act_detail"][:3]))
                except Exception:                                 # noqa: BLE001
                    pass
            # 🌱: **押したら何件 目視が出るか**を出す (未結論の母数ではない)。
            #   未結論の大半は結論済カードの別の仕入元で、人に見せず補URLに回る。
            if nc.get("error"):
                n_txt = "\n(残件 取得できず: %s)" % str(nc["error"])[:40]
            elif not nc.get("show") and not nc.get("auto"):
                n_txt = "\n※押しても0件 (全部 結論済)"
            else:
                n_txt = "\n目視 %s件" % nc.get("show", 0)
                if nc.get("auto"):
                    n_txt += " (+自動で補URL %s件)" % nc["auto"]
            # 🎴 一番くじ: PSA と同じ考え方 (押したら何件できるか)。2026-08-22 ユーザー要望
            kj = (w0.get("kuji") or {}) if isinstance(w0, dict) else {}
            if kj.get("error"):
                k_s = k_c = "\n(残件 取得できず: %s)" % str(kj["error"])[:40]
            elif kj:
                k_s = "\n今夜の対象 %s件 (補0本 %s件)" % (
                    (kj.get("search") or {}).get("can", 0), kj.get("zero", 0))
                if (kj.get("search") or {}).get("no_query"):
                    k_s += "\n※検索語が作れない %s件" % kj["search"]["no_query"]
                k_c = "\n目視できる %s件" % (kj.get("confirm") or {}).get("ready", 0)
                if not (kj.get("confirm") or {}).get("ready"):
                    k_c += "\n※先に slice2 (夜間検索) を回してください"
            else:
                k_s = k_c = ""
            # 🗑 取下げ (CULL): 押したら何件落ちるか + あと何件残っているか
            #   (2026-08-24 ユーザー要望「対象が出たら青、残数はヒントに」)
            ce = (w0.get("cull") or {}) if isinstance(w0, dict) else {}
            if ce.get("error"):
                ce_txt = "\n(残件 取得できず: %s)" % str(ce["error"])[:40]
            elif ce:
                ce_txt = "\n今回 %s件 落とせます (残り %s件)" % (
                    ce.get("next", 0), ce.get("remaining", 0))
                if ce.get("remaining", 0) > ce.get("cap", 0):
                    ce_txt += "\n※1回 %s件までなので あと %s回" % (
                        ce["cap"], -(-ce["remaining"] // ce["cap"]))
                if not ce.get("remaining"):
                    ce_txt += "\n※押しても0件 (これまでに %s件 落とし済み)" % ce.get("done", 0)
            else:
                ce_txt = ""
            # 📉 棚を入れ替える: 押したら何件・いくら空くか
            #   (2026-08-31 ユーザー要望「ラベルに件数と金額を出せる?」)。
            #   他ボタンは 2026-08-22 の決定でヒント側に寄せたが、このボタンだけは
            #   明示の要望でラベルにも短い1行を出す (se_label)。詳細は従来どおりヒント (se_txt)。
            se = (w0.get("shelf") or {}) if isinstance(w0, dict) else {}
            if se.get("error"):
                se_txt = "\n(残件 取得できず: %s)" % str(se["error"])[:40]
                se_label = ""
            elif se:
                se_txt = ("\n在庫はあるが売れない出品が %s件 ($%s ぶん)\n"
                           "押すと「いくら空けますか」と聞きます\n"
                           "今日の出品額 $%s") % (
                    se.get("max_picked", 0), f"{se.get('max_amount', 0):,.0f}",
                    f"{se.get('listed_today', 0):,.0f}")
                if se.get("cache_note"):
                    se_txt += "\n" + se["cache_note"]
                # ★2026-09-03: 押す前に額を聞けるようにしたので、ボタンには
                #   **今日どこまで空けられるか (上限)** を出す。今日の出品額だけ出すと
                #   「いくらまで指定できるのか」が分からない (ユーザー要望)。
                if se.get("max_picked"):
                    se_label = "最大 %s件 / $%s" % (
                        se["max_picked"], f"{se.get('max_amount', 0):,.0f}")
                    se_txt += "\n空欄で押すと 今日の出品分だけ ($%s)" % (
                        f"{se.get('amount', 0):,.0f}")
                else:
                    se_label = "対象なし"
            else:
                se_txt = se_label = ""
            # 🔁 売れた分を補充: 押したら何件アクションが起きるか
            #   (2026-08-31 ユーザー要望「放置しちゃう」)。
            sr = (w0.get("restock") or {}) if isinstance(w0, dict) else {}
            if sr.get("error"):
                sr_txt = "\n(残件 取得できず: %s)" % str(sr["error"])[:40]
            elif sr:
                if not sr.get("report"):
                    sr_txt = "\n※注文レポート未DL (デスクトップに ebay-all-orders-report-*.csv)"
                else:
                    sr_txt = "\n今すぐ送れる %s件 (要確認 %s件・補充済 %s件)" % (
                        sr.get("actionable", 0), sr.get("unknown", 0), sr.get("done", 0))
                    if sr.get("unknown"):
                        sr_txt += "\n※要確認は押すと分かります (売切れ終了→出し直しの可能性)"
            else:
                sr_txt = ""
            # ===== 2026-09-01: 既存メンテの残り6ボタン (ユーザー要望「何をしたらいいか分からない」) =====
            #   出す数字は **押したら今すぐ動く件数だけ** (ユーザー決定)。0件なら黒のまま。
            def _err(d, what):
                return "\n(%s 取得できず: %s)" % (what, str(d["error"])[:40])

            # 🃏 PSA再仕入れ照合: 今すぐ照合に出せる件数
            pg = (w0.get("psa_gate") or {}) if isinstance(w0, dict) else {}
            if pg.get("error"):
                pg_txt = _err(pg, "件数")
            elif pg:
                pg_txt = "\n今すぐ照合できる %s件 (候補 %s件のうち)" % (
                    pg.get("actionable", 0), pg.get("targets", 0))
                if pg.get("processed"):
                    pg_txt += "\n※確定/レビュー済で伏せている %s件" % pg["processed"]
                if pg.get("note"):
                    pg_txt += "\n※%s" % pg["note"]
                if (pg.get("funnel_age") or 0) >= 3:
                    pg_txt += "\n※ファネルが %s日前です (先に 📊 ファネル分析)" % pg["funnel_age"]
                if not pg.get("actionable") and not pg.get("note"):
                    pg_txt += "\n※押しても0件 (新しい候補が出るのはファネル更新後)"
            else:
                pg_txt = ""
            # ♻ RESTOCK Revise CSV生成: 何件ぶん CSV が出るか
            rb = (w0.get("restock_build") or {}) if isinstance(w0, dict) else {}
            if rb.get("error"):
                rb_txt = _err(rb, "件数")
            elif rb:
                rb_txt = "\nCSVにできる %s件" % rb.get("actionable", 0)
                if rb.get("done"):
                    rb_txt += " (出し済み %s件は除外)" % rb["done"]
                if not rb.get("actionable"):
                    rb_txt += "\n※押しても0件 (先に 🃏 で仕入元を確定)"
            else:
                rb_txt = ""
            # 🔄 RESTOCK状態同期: 何件の実状態を確かめに行くか
            rw = (w0.get("restock_wb") or {}) if isinstance(w0, dict) else {}
            if rw.get("error"):
                rw_txt = _err(rw, "件数")
            elif rw:
                rw_txt = "\n確かめに行く %s件 (実行済 %s件)" % (
                    rw.get("actionable", 0), rw.get("done", 0))
                if not rw.get("actionable"):
                    rw_txt += "\n※押しても0件 (全部 実行済)"
            else:
                rw_txt = ""
            # 📊 補URL件数感: **見るだけ**なので色は変えない。今の内訳をそのまま出す
            hs_txt = "\nlive PSA %s件 / 補が薄い %s件\n(検索できる %s件 / 目視できる %s件)" % (
                w.get("live_psa", "?"), tot, s["can"], cf["ready"])
            # 🎴一番くじ補充① supply確定 / ② 刷新→CSV
            kv = (kj.get("supply") or {}) if isinstance(kj, dict) else {}
            kr = (kj.get("refresh") or {}) if isinstance(kj, dict) else {}
            if kv.get("error"):
                kv_txt = _err(kv, "件数")
            elif kv.get("can") is None:
                kv_txt = ""
            else:
                kv_txt = "\n目視に出せる %s件" % kv["can"]
                if not kv["can"]:
                    kv_txt += "\n※押しても0件 (在庫切れの一番くじが無い)"
            if kr.get("error"):
                kr_txt = _err(kr, "件数")
            elif kr.get("can") is None:
                kr_txt = ""
            else:
                kr_txt = "\nCSVにできる %s件" % kr["can"]
                if not kr["can"]:
                    kr_txt += "\n※押しても0件 (先に ① supply確定)"
            by_kind = {"hoju_search": s_txt, "hoju_confirm": c_txt, "newcand": n_txt,
                       "kuji_search": k_s, "kuji_confirm": k_c, "cull_end": ce_txt,
                       "shelf_evict": se_txt, "shelf_evict_label": se_label,
                       "sold_restock": sr_txt,
                       "psa_gate": pg_txt, "restock_build": rb_txt, "restock_wb": rw_txt,
                       "hoju_status": hs_txt, "kuji_supply": kv_txt, "kuji_refresh": kr_txt}
            # ★2026-08-16: **押すと何か出てくる時だけ青**。0件なら黒のまま
            #   (「いつ押せばいいのか分からない」への答え。色 = 今やる価値があるか)。
            act_kind = {"hoju_search": bool(s.get("can")),
                        "hoju_confirm": bool(cf.get("ready") or cf.get("unjudged")),
                        "newcand": bool(nc.get("show") or nc.get("auto")),
                        # 夜間検索は自動で走るので、押す必要がある時だけ青
                        "kuji_search": bool(not nightly["ok"]
                                            and (kj.get("search") or {}).get("can")),
                        "kuji_confirm": bool((kj.get("confirm") or {}).get("ready")),
                        # 落とすものが在る時だけ青 (0件なら押す意味が無い)
                        "cull_end": bool(ce.get("remaining")),
                        "shelf_evict": bool(se.get("picked")),
                        "sold_restock": bool(sr.get("actionable") or sr.get("unknown")),
                        # ★2026-09-01: 押したら今すぐ動く件数が1件でもある時だけ青。
                        #   📊 補URL件数感 は **見るだけ**なので色を変えない (act_kind に入れない)。
                        "psa_gate": bool(pg.get("actionable")),
                        "restock_build": bool(rb.get("actionable")),
                        "restock_wb": bool(rw.get("actionable")),
                        "kuji_supply": bool(kv.get("can")),
                        "kuji_refresh": bool(kr.get("can"))}
        except Exception as e:                                    # noqa: BLE001
            # 数えられない時は**黙って0と出さない**。分からないと書く。
            # ★理由まで出す。「取得できず」だけでは次に何をすればいいか分からない。
            why = err_reason or f"{type(e).__name__}"
            act_kind = {}
            cached = self._hoju_badge_cache()
            if cached:
                by_kind = {k: v + "\n※前回値" for k, v in cached.items()}
            else:
                msg = f"\n(残件 取得できず: {why[:40]})"
                by_kind = {"hoju_search": msg, "hoju_confirm": msg, "newcand": msg}
            try:
                self.append_log(f"⚠️ 補URL 残件の取得に失敗: {why}\n")
            except Exception:                                     # noqa: BLE001
                pass
        else:
            self._hoju_badge_cache(by_kind)
        self.paint_hoju_badge(by_kind, act_kind)

    def append_log(self, text):
        # tag判定
        applied = False
        for pat, name, _ in LOG_TAGS:
            if pat.search(text):
                self.log.insert("end", text, name)
                applied = True
                # ヘッダー行は status 更新
                if name == "header":
                    m = re.match(r'^\[(\d+)/(\d+)\]\s*(.+?)$', text.strip())
                    if m:
                        self.now_processing.set(f"[{m.group(1)}/{m.group(2)}] {m.group(3)[:50]}")
                break
        if not applied:
            self.log.insert("end", text)
        # ログ膨張防止: 5000行を超えたら古い行を削除（メモリ枯渇対策）
        try:
            line_count = int(self.log.index('end-1c').split('.')[0])
            if line_count > 5000:
                self.log.delete("1.0", "1000.0")  # 先頭1000行削除
        except Exception:
            pass
        self.log.see("end")

    def clear_log(self):
        self.log.delete("1.0", "end")
        self.now_processing.set("")

    def _run_psa_orphan_clean(self):
        """PSA新規生成の前に orphan canonical KEY を掃除(歩留まり激減の恒久対策, 2026-06-21)。

        未出品(B列空)なのに KEY が付いて dedup に誤ブロックされた在庫を出品対象に戻す。同期実行。
        失敗しても新規生成は続行(掃除は best-effort)。dedupe/psa_to_csv は触らずスプシ AI列のみ。
        """
        self.append_log("\n🧹 orphan KEY 掃除(未出品なのに誤ブロックされた在庫を出品対象へ戻す)...\n")
        try:
            tool = os.path.join(WORKSPACE, "iMakHQ", "tools", "psa_orphan_key_clean.py")
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            r = subprocess.run([sys.executable, tool, "--execute"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180, creationflags=flags)
            if r.stdout:
                self.append_log(r.stdout)
            if r.returncode != 0:
                self.append_log(f"⚠️ orphan掃除 returncode={r.returncode}(新規生成は続行)\n")
                if r.stderr:
                    self.append_log(r.stderr[-500:] + "\n")
        except Exception as e:
            self.append_log(f"⚠️ orphan掃除 skip(新規生成は続行): {type(e).__name__}: {e}\n")

    def _check_n_formula_guard(self):
        """統合High/Low の N列(仕入値SSOT)関数の破損検知。壊れていたら False (=run 中止)。

        2026-07-23 設計: N =(M=現在価格 or F)−K=ポイント の ARRAYFORMULA (N1 の1セル)。
        どこかのプロセスが N セルに値を書くと関数が静かに壊れ、陳腐化した仕入値で誤価格
        出品が続く (fail-OPEN)。listing 系 run の前に両シートを確認する。
        LOW は gshock_to_csv 内にも同ガードあり (二重化)。HIGH の主要消費者 psa_to_csv は
        no-touch 運用のため、HIGH はここが唯一のガード。
        ネットワーク等でチェック自体が失敗した場合は警告のみで続行 (可用性優先。破損の
        確証がある時だけ止める)。
        """
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_file(
                GSHEET_CREDS_PATH, scopes=["https://www.googleapis.com/auth/spreadsheets"])
            gc = gspread.authorize(creds)
            for label, (sid, gid) in CONSOLIDATED_SHEETS.items():
                ws = gc.open_by_key(sid).get_worksheet_by_id(gid)
                f = ws.acell("N1", value_render_option="FORMULA").value or ""
                if not f.startswith("=ARRAYFORMULA"):
                    self.append_log(
                        f"🚫 {label} スプシ N列の仕入値関数が壊れています (N1={f[:40]!r})。\n"
                        "   N セルに値を書いたプロセスを特定し、N1 に ARRAYFORMULA を再設置\n"
                        "   してください (memory: amazon_points_net_cost_system 参照)。run 中止。\n")
                    return False
            return True
        except Exception as e:
            self.append_log(f"⚠️ N関数ガード チェック不能(続行): {type(e).__name__}: {e}\n")
            return True

    def run_script(self, idx):
        script = SCRIPTS[idx]
        # 一番くじ: ウィザード式ダイアログを起動
        if script.get("custom_buttons") == "ichibankuji":
            KujiWizardDialog(self.root, self)
            return
        # Seller Hub 分析: カテゴリ選択ダイアログ
        if script.get("custom_buttons") == "seller_hub_view":
            SellerHubCategoryDialog(self.root, self, idx)
            return
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("実行中", "他のスクリプトが実行中です。停止してから実行してください。")
            return
        self._current_idx = idx  # 完了時 open_after 用
        # PSA新規: 生成の前に orphan canonical KEY を自動掃除(2026-06-21 恒久対策)。
        # write-keys が出品確定前に KEY を書く → 未出品在庫を dedup が誤ブロックし歩留まり激減する
        # 問題を、毎回 生成前に掃除して再発防止。control_panel のみ・dedupe/psa_to_csv は不変。
        if script.get("category") == "PSA TCG" and script.get("type") == "new":
            self._run_psa_orphan_clean()
        # listing 系 run 前の N列(仕入値SSOT)関数ガード (2026-07-23、両スプシ)
        if script.get("type") == "new" and not self._check_n_formula_guard():
            self.status_var.set("中止: N列関数の破損検知")
            return
        cmd = list(script["cmd"])
        # ★2026-09-03: 棚は「その日に出した金額」まで落として止まる。もっと空けたい日は
        #   何度押しても2回目以降はほぼ何も落ちない (目標がもう埋まっているため)。
        #   押す回数で調整させず、**空けたい額を1回聞く**。空欄なら従来どおり。
        if script.get("ask_amount"):
            _v = simpledialog.askstring(
                "いくら空けますか",
                "空けたい金額 ($) を入れてください。\n"
                "空欄のままなら「今日出品した金額と同じだけ」落とします。",
                parent=self.root if hasattr(self, "root") else None)
            if _v is None:
                self.status_var.set("中止しました")
                return
            _v = _v.strip().replace(",", "").replace("$", "")
            if _v:
                try:
                    float(_v)
                except ValueError:
                    messagebox.showerror("入力エラー", f"金額として読めません: {_v}")
                    return
                cmd.extend(["--amount", _v])
        for pname, entry in self.param_entries[idx].items():
            v = entry.get().strip()
            if v:
                cmd.extend([pname, v])
        cwd = script["cwd"]
        self.append_log(f"\n{'='*70}\n▶ {script['label']}\n  cwd: {cwd}\n  cmd: {' '.join(cmd)}\n{'='*70}\n")
        self.status_var.set(f"実行中: {script['label']}")
        self.now_processing.set("")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        # script 固有 env (例: PSA TCG の TCG_USE_NEW_GEN=1 新生成コア切替・2026-06-14 flip)
        for _k, _v in (script.get("env") or {}).items():
            env[_k] = _v
            self.append_log(f"  env: {_k}={_v}\n")
        # subprocess stdout を永続化 (UI 閉じても残る、後追い解析可能)
        try:
            self._run_log, log_path = _open_run_log(script["label"])
            self.append_log(f"📝 run log: {log_path}\n")
            self._run_log.write(f"=== {script['label']} ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
            self._run_log.write(f"cwd: {cwd}\ncmd: {' '.join(cmd)}\n\n")
            self._run_log.flush()
        except Exception as _e:
            self._run_log = None
            self.append_log(f"⚠️ run log 開けず (無視して続行): {_e}\n")
        try:
            # Windows: コンソール窓を出さない
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
            self._listing_start_ts = time.time()  # rarara が今回 CSV のみ対象にするための基準
            self.proc = subprocess.Popen(
                cmd, cwd=cwd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            threading.Thread(target=self._reader, daemon=True).start()
        except Exception as e:
            self.append_log(f"❌ 起動失敗: {e}\n")
            self.status_var.set("待機中")

    def _reader(self):
        for line in self.proc.stdout:
            self.queue.put(line)
            if self._run_log:
                try:
                    self._run_log.write(line)
                    self._run_log.flush()
                except Exception:
                    pass
        try:
            self.proc.wait(timeout=10)  # stdout 閉じた後にプロセス終了を待つ → returncode 確定 (None防止)
        except subprocess.TimeoutExpired:
            pass
        if self._run_log:
            try:
                self._run_log.close()
            except Exception:
                pass
            self._run_log = None
        self.queue.put(("__done__", self.proc.returncode))

    def _run_rarara_after(self):
        """ListingPanel: rarara helper 呼出 (互換ラッパ)."""
        _run_rarara_for_latest_csv(self.append_log, since_ts=getattr(self, '_listing_start_ts', None))

    def _run_log_text(self):
        """今回の走行の stdout を **run log ファイル** から読む (2026-08-03)。

        ログ欄(self.log)を読むと 2つの理由で **前の走行が混ざる**:
          - クリアを押し忘れると前走行の全文が残る
            (実害 2026-08-02: gshock の報告に TCG の「入稿OK6件」「#155393557」が混入)
          - 5000行を超えると先頭1000行が削除される(control_panel.py の膨張防止)
        run log は走行ごとに新規ファイルなので、どちらの影響も受けない。
        読めない時だけ従来どおりログ欄にフォールバック (= 報告が消えるより混ざる方がまし)。
        """
        path = getattr(self, "_run_log_path", None)
        if path:
            try:
                fh = getattr(self, "_run_log", None)
                if fh and not fh.closed:
                    fh.flush()
                with open(path, encoding="utf-8", errors="replace") as f:
                    txt = f.read()
                if txt.strip():
                    return txt
            except Exception as _e:
                self.append_log(f"⚠️ run log 読取失敗 → ログ欄で代用: {type(_e).__name__}\n")
        return self.log.get("1.0", "end") if hasattr(self, "log") else ""

    def _show_audit_summary(self, captured_log):
        """CSV監査くん完走 → 要点をポップアップ表示 (出品くん側の能動報告)."""
        summary = summarize_audit_log(captured_log)
        if not summary:
            return
        # ポップアップは廃止(2026-07-01 ユーザー: HQが対話で自動報告する方式に)。log には残す。
        self.append_log("\n" + "=" * 70 + "\n📋 監査サマリー (要点)\n" + summary + "\n" + "=" * 70 + "\n")

    def _show_problem_report(self, captured_log):
        """新規生成完走 → 統合「問題提起」(CSV化分の監査問題 + 非化分の原因→対策案)を log に出力.

        全カテゴリ共通。ポップアップは廃止(2026-07-01)、HQ が対話で自動報告する(判断・指示は人)."""
        report = build_problem_report(captured_log)
        if not report:
            return
        self.append_log("\n" + "=" * 70 + "\n" + report + "\n" + "=" * 70 + "\n")

    def poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "__done__":
                    self.append_log(f"\n--- 終了 (returncode={item[1]}) ---\n")
                    # CSV監査くん 完走 → 要点サマリーをポップアップ (HQチャットの介在なしで結果を即可視化。
                    # 2026-06-29: 対話セッションは外部から起こせないため、出品くん側で報告する)。
                    try:
                        _idx2 = getattr(self, "_current_idx", -1)
                        _cmd2 = SCRIPTS[_idx2].get("cmd", []) if _idx2 >= 0 else []
                        # 新規生成(全カテゴリ)完了時: 統合問題提起(CSV化分の監査問題 + 非化分の原因→対策案)。
                        # 生成ログは drops + inline自己監査を含むので1本で両方カバー。
                        if _idx2 >= 0 and SCRIPTS[_idx2].get("type") == "new":
                            self._show_problem_report(self._run_log_text())
                        elif any("csv_auditor.py" in str(c) for c in _cmd2):
                            self._show_audit_summary(self._run_log_text())
                    except Exception as _e:
                        self.append_log(f"⚠️ サマリー表示失敗: {_e}\n")
                    # open_after: 結果ファイル(最新)を自動で開く (ファネル分析/需要強化 等)
                    _cur = SCRIPTS[getattr(self, "_current_idx", -1)] if getattr(self, "_current_idx", -1) >= 0 else {}
                    _oa = _cur.get("open_after")
                    # restock_revise は Revise CSV が post-chain(後段)で生成されるため、ここで開くと
                    # 一つ前の古いCSVを掴む(2026-06-22 指摘)。生成後(Step4.5の後)に開く。
                    if _oa and _cur.get("restock_revise"):
                        _oa = None
                    if _oa and item[1] in (0, None):  # None=returncode未確定でも完走時は開く
                        try:
                            import glob as _g
                            hits = _g.glob(_oa)
                            if hits:
                                latest = max(hits, key=os.path.getmtime)
                                os.startfile(latest)
                                self.append_log(f"📂 開く: {os.path.basename(latest)}\n")
                            else:
                                self.append_log(f"⚠️ 出力ファイルが見つかりません: {_oa}\n")
                        except Exception as _e:
                            self.append_log(f"⚠️ ファイル起動失敗: {_e}\n")
                    # open_url: 結果スプシ(URL)を自動で開く (集約方針=結果はスプシ。2026-06-07)
                    _ou = _cur.get("open_url")
                    if _ou and item[1] in (0, None):
                        try:
                            import webbrowser as _wb
                            _wb.open(_ou)
                            self.append_log(f"🌐 開く: {_ou}\n")
                        except Exception as _e:
                            self.append_log(f"⚠️ スプシ起動失敗: {_e}\n")
                    # 取下再出品②(relist)は CSV破壊系の後処理をスキップ。
                    # 理由: relist は「同じ型番を意図的に再出品」。重複くん/excluder は通常出品用で、
                    #       取下げ前(=管理シート上はまだACTIVE)の同型番を「重複」と誤判定し CSV から物理削除する。
                    _skip_pp = False
                    try:
                        _idx = getattr(self, "_current_idx", -1)
                        _skip_pp = bool(_idx >= 0 and SCRIPTS[_idx].get("skip_postprocess"))
                    except Exception:
                        _skip_pp = False
                    if _skip_pp:
                        _skip_label = SCRIPTS[_idx].get("label", "") if _idx >= 0 else ""
                        self.append_log(f"\n({_skip_label}: excluder/title-fix/重複くん の後処理をスキップ — skip_postprocess)\n")
                    # Step 2: csv_postprocess_excluder (check_csv NO-GO 行を CSV 物理除外)
                    # Step 2.5: post_title_fix (TCG タイトル長補強・PSA 名前正規化, 2026-05-02 追加)
                    # Step 3: rarara (CSV outlier 検出) - excluder 後の CSV を分析
                    if not _skip_pp:
                        try:
                            captured_log = self._run_log_text()
                            _run_excluder_for_latest_csv(self.append_log, captured_log)
                        except Exception as _e:
                            self.append_log(f"\n⚠️ excluder hook 失敗: {_e}\n")
                    if not _skip_pp:
                        try:
                            _ptf_dir = os.path.join(WORKSPACE, "iMakTCG", "tools")
                            if _ptf_dir not in sys.path:
                                sys.path.insert(0, _ptf_dir)
                            from post_title_fix import run_post_title_fix_for_latest_csv
                            run_post_title_fix_for_latest_csv(self.append_log)
                        except Exception as _e:
                            self.append_log(f"\n⚠️ post_title_fix hook 失敗: {_e}\n")
                    # rarara hook 削除 (= 5/28 ユーザー判断、 DON 仕様で WARN ばかり実害発見ゼロ)
                    # 旧: self._run_rarara_after()
                    # Step 4: dedupe_excluder (2026-05-27 追加、 重複くん (KEY1, KEY2) tuple 物理除外)
                    # RESTOCK Revise は既存出品の修正=重複を作らないので新規用 dedupe を skip
                    # (2026-06-22: 自己重複で RESTOCK 行が誤除外される事故の根治。_runs_new_listing_dedupe 参照)。
                    _entry_now = SCRIPTS[_idx] if _idx >= 0 else {}
                    if _runs_new_listing_dedupe(_entry_now):
                        try:
                            _run_dedupe_for_latest_csv(self.append_log, since_ts=getattr(self, '_listing_start_ts', None))
                        except Exception as _e:
                            self.append_log(f"\n⚠️ dedupe hook 失敗: {_e}\n")
                        # 🤖PSA自動 だけ: 締めに itemID書込 → 広告8% → CSV監査くん (2026-08-18)
                        if _entry_now.get("auto_full"):
                            try:
                                _envf = os.environ.copy()
                                _envf["PYTHONIOENCODING"] = "utf-8"
                                _envf["PYTHONUNBUFFERED"] = "1"
                                _run_auto_full_tail(self.append_log, _envf)
                            except Exception as _e:
                                self.append_log(f"\n⚠️ PSA自動の締め 失敗: {_e}\n")
                    elif _entry_now.get("restock_revise"):
                        self.append_log(
                            "\n(♻ RESTOCK: 新規出品用の重複くんを skip — Revise は既存出品の修正で重複を作らない。"
                            "自己重複による誤除外を防止)\n")
                    # Step 4.5: RESTOCK Revise 変換 (2026-06-20)。excluder/title-fix/dedup の **後** に、
                    # 最終クリーンな Add CSV を Add→Revise 化する(順序保証=赤字/重複/旧タイトルを含めない)。
                    # ♻ ボタン (restock_revise=True) の時のみ。旧: psa_restock_build が dedup 前に変換→混入バグ。
                    try:
                        _ridx = getattr(self, "_current_idx", -1)
                        if _ridx >= 0 and SCRIPTS[_ridx].get("restock_revise"):
                            _run_restock_revise_for_latest_csv(
                                self.append_log, since_ts=getattr(self, '_listing_start_ts', None))
                            # CSV の open_after は post_psa_review の **後** に回す(同時オープン回避)。
                            # 確認ブラウザが開く時は CSV を開かない(2026-06-22 指摘)。フラグだけ立てる。
                            self._restock_open_after_pending = SCRIPTS[_ridx].get("open_after")
                    except Exception as _e:
                        self.append_log(f"\n⚠️ RESTOCK Revise hook 失敗: {_e}\n")
                    # Step 5: post_psa_review (2026-05-28 追加、 PSA TCG cert HTML viewer ユーザー判定 hook)
                    # 5/29 修正: 今 cycle で生成された tcg_upload_*.csv のみ対象 (= TCG 以外 cycle で毎回 HTML 出る問題対策)
                    # 2026-06-15: verify→build (PSA_VERIFY_BEFORE_BUILD=1) の時は CSV 生成 **前** に
                    #   目視確認済 → この後付け hook は二重なので skip (HTML が CSV 後に出る問題の解消)。
                    _verify_before_build = False
                    try:
                        _vidx = getattr(self, "_current_idx", -1)
                        _verify_before_build = bool(
                            _vidx >= 0 and SCRIPTS[_vidx].get("env", {}).get("PSA_VERIFY_BEFORE_BUILD") == "1")
                    except Exception:
                        _verify_before_build = False
                    # RESTOCK Revise は変種を確定KEIから forced 生成済み(既存出品の再出品)。
                    # cert確認 viewer は無関係=Revise CSV は既に確定変種で生成済みなので出さない
                    # (2026-07-24 ユーザー指摘: 無関係なら出すな)。
                    _is_restock_revise = False
                    try:
                        _ridx2 = getattr(self, "_current_idx", -1)
                        _is_restock_revise = bool(_ridx2 >= 0 and SCRIPTS[_ridx2].get("restock_revise"))
                    except Exception:
                        _is_restock_revise = False
                    _skip_review = _verify_before_build or _is_restock_revise
                    if _verify_before_build:
                        self.append_log("\n(post_psa_review: verify→build で生成前に確認済 — 後付け hook skip)\n")
                    elif _is_restock_revise:
                        self.append_log("\n(post_psa_review: RESTOCK Revise は確定変種で生成済 — cert確認 hook skip)\n")
                    try:
                        _tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
                        if _tools_dir not in sys.path:
                            sys.path.insert(0, _tools_dir)
                        from post_psa_review import run_post_psa_review
                        _latest_csv = None
                        _listing_start = getattr(self, '_listing_start_ts', None)
                        _csv_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csv_output")
                        if os.path.isdir(_csv_dir):
                            _candidates = sorted(
                                [os.path.join(_csv_dir, f) for f in os.listdir(_csv_dir) if f.startswith("tcg_upload_") and f.endswith(".csv")],
                                key=os.path.getmtime,
                                reverse=True,
                            )
                            if _candidates and _listing_start:
                                # 今 cycle (= listing_start 以降に生成) のみ対象
                                if os.path.getmtime(_candidates[0]) >= _listing_start:
                                    _latest_csv = _candidates[0]
                        # verify→build は生成前に確認済 → 後付け viewer は出さない (二重防止)。
                        # _latest_csv の算出は Step 6 (no_go_sentinel) が使うため残す。
                        _review_opened = False
                        if _latest_csv and not _skip_review:
                            _review_opened = bool(run_post_psa_review(_latest_csv, self.append_log))
                        # RESTOCK CSV の open_after: 確認ブラウザを開いた時は開かない(同時オープン回避)。
                        # 確認が無い時のみ最新CSVを開く(生成後=新しい方を掴む)。
                        _pend_oa = getattr(self, "_restock_open_after_pending", None)
                        if _pend_oa:
                            self._restock_open_after_pending = None
                            if _review_opened:
                                self.append_log("📄 確認ブラウザを開いたため CSV自動オープンは保留(確認後に手動/同期で)\n")
                            else:
                                try:
                                    import glob as _g2
                                    _hits = _g2.glob(_pend_oa)
                                    if _hits:
                                        _latest_oa = max(_hits, key=os.path.getmtime)
                                        os.startfile(_latest_oa)
                                        self.append_log(f"📂 開く: {os.path.basename(_latest_oa)}\n")
                                except Exception as _e3:
                                    self.append_log(f"⚠️ open_after(restock) 失敗: {_e3}\n")
                    except Exception as _e:
                        self.append_log(f"\n⚠️ post_psa_review hook 失敗: {_e}\n")
                    # Step 6: post_no_go_sentinel (2026-05-28 追加、 NO-GO 除外 cert にスプシ K 列 sentinel 赤字書込)
                    # 5/29: Step 5 と同 _latest_csv 使用 (= 今 cycle TCG のみ。 Porter 等は None で skip)
                    try:
                        from post_no_go_sentinel import run_post_no_go_sentinel
                        if _latest_csv:
                            run_post_no_go_sentinel(_latest_csv, self.append_log)
                    except Exception as _e:
                        self.append_log(f"\n⚠️ post_no_go_sentinel hook 失敗: {_e}\n")
                    # 全 process 完了通知 (= ユーザー要望 2026-05-31)
                    # ★2026-08-23: 出品が途中で止まっていても、ここは常に「🎉 完了」と出ていた。
                    #   9件中2件しか出ていない走行が成功に見えた。出し残しがあるなら締めを変える。
                    _left = []
                    try:
                        _rj = os.path.join(WORKSPACE, "iMakHQ", "csv_output",
                                           "last_upload_result.json")
                        if os.path.isfile(_rj):
                            with open(_rj, encoding="utf-8") as _f:
                                _left = unlisted_from_result(
                                    json.load(_f),
                                    started_ts=getattr(self, "_listing_start_ts", None),
                                    file_mtime=os.path.getmtime(_rj))
                    except Exception as _e:
                        self.append_log(f"\n⚠️ 出品結果の読取に失敗 (締めの判定のみ): {_e}\n")
                    self.append_log("\n" + "=" * 70 + "\n")
                    if _left:
                        self.append_log(
                            f"⚠️ 出品できていない行が {len(_left)}件 あります — 完了していません\n")
                        self.append_log(f"   {', '.join(_left[:20])}\n")
                        self.append_log("   原因を潰してから、この分だけ出し直してください\n")
                    else:
                        self.append_log("🎉 全 process 完了 — 入稿準備 OK\n")
                    if _latest_csv:
                        self.append_log(f"   出力 CSV: {_latest_csv}\n")
                    from datetime import datetime as _dt
                    self.append_log(f"   終了時刻: {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    self.append_log("=" * 70 + "\n")
                    self.status_var.set("待機中")
                    self.now_processing.set("")
                    # ★走行後に残件を数え直す (押した分だけ減ったのが見える)
                    try:
                        self.refresh_hoju_badge()
                    except Exception:                             # noqa: BLE001
                        pass
                else:
                    self.append_log(item)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def stop_script(self):
        _kill_process_tree(self.proc, self.append_log)
        self.status_var.set("停止処理中")


class SellerHubCategoryDialog(tk.Toplevel):
    """Seller Hub 分析: カテゴリ + Status + Snapshot 選択ダイアログ.

    seller_hub_view.py --category <key> [--status <s>] [--save] [--analyze]
    を起動するためのダイアログ.
    """
    CATEGORIES = [
        ("porter",      "Porter (吉田カバン)"),
        ("gshock",      "G-Shock"),
        ("tcg",         "PSA 10 TCG"),
        ("ichibankuji", "一番くじ"),
        ("reel",        "釣具リール (Shimano/Daiwa)"),
        ("",            "全件 (絞込なし)"),
    ]

    def __init__(self, parent, panel, script_idx):
        super().__init__(parent)
        self.panel = panel
        self.script_idx = script_idx
        self.title("📊 Seller Hub 分析")
        self.geometry("440x440")
        self.resizable(False, False)
        self.transient(parent)

        tk.Label(self, text="Seller Hub Active / Ended Listings を分析・保存",
                 font=("Yu Gothic UI", 11, "bold")).pack(pady=(12, 6))
        tk.Label(self, text="View / Watchers / 死蔵候補 / 購買意欲を集計。--save で永続蓄積。",
                 font=("Yu Gothic UI", 9), fg="#666").pack(pady=(0, 8))

        # カテゴリ選択
        ttk.Label(self, text="カテゴリ:", font=("Yu Gothic UI", 10, "bold")).pack(anchor="w", padx=20)
        self.selected = tk.StringVar(value="porter")
        cat_frame = ttk.Frame(self)
        cat_frame.pack(fill="x", padx=30, pady=(2, 8))
        for key, label in self.CATEGORIES:
            ttk.Radiobutton(cat_frame, text=label, value=key,
                            variable=self.selected).pack(anchor="w", pady=1)

        # Status 選択
        ttk.Label(self, text="Status:", font=("Yu Gothic UI", 10, "bold")).pack(anchor="w", padx=20, pady=(4, 0))
        self.status = tk.StringVar(value="active")
        st_frame = ttk.Frame(self)
        st_frame.pack(fill="x", padx=30, pady=(2, 8))
        ttk.Radiobutton(st_frame, text="Active (出品中)", value="active",
                        variable=self.status).pack(anchor="w")
        ttk.Radiobutton(st_frame, text="Ended (90日以内、データ消失前)", value="ended",
                        variable=self.status).pack(anchor="w")

        # Snapshot 保存
        self.do_save = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="📥 snapshot CSV 保存 (iMak_data/seller_hub/)",
                        variable=self.do_save).pack(anchor="w", padx=20, pady=(4, 8))

        # 実行ボタン
        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x", padx=20, pady=(8, 12))
        ttk.Button(button_frame, text="キャンセル",
                   command=self.destroy).pack(side="left")
        ttk.Button(button_frame, text="▶ 実行",
                   command=self._on_run).pack(side="right")

    def _on_run(self):
        category = self.selected.get()
        status = self.status.get()
        do_save = self.do_save.get()
        script = SCRIPTS[self.script_idx]
        cmd = list(script["cmd"])  # python seller_hub_view.py --analyze
        if category:
            cmd += ["--category", category]
        if status != "active":
            cmd += ["--status", status]
        if do_save:
            cmd += ["--save", "--all-pages"]  # 保存時は必ず全件 (--all-pages なしだと 200 件で打切)
        self.destroy()
        # ListingPanel の run_script フロー (subprocess + log) を流用
        if self.panel.proc and self.panel.proc.poll() is None:
            messagebox.showwarning("実行中", "他のスクリプトが実行中です。")
            return
        self.panel.clear_log()
        cwd = script.get("cwd", os.getcwd())
        self.panel.append_log(f"▶ Seller Hub 分析 [{category or '全件'}]\n  cwd: {cwd}\n  cmd: {' '.join(cmd)}\n\n")
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self.panel.proc = subprocess.Popen(
                cmd, cwd=cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=creationflags,
            )
            self.panel.status_var.set("Seller Hub 分析中…")
            threading.Thread(target=self.panel._reader, daemon=True).start()
        except Exception as e:
            self.panel.append_log(f"\n❌ 起動失敗: {e}\n")


class KujiWizardDialog(tk.Toplevel):
    """一番くじ ウィザード：URL入力 → Phase1 → CSV編集待ち → Phase2+CSV生成 を1ダイアログで案内"""

    KUJI_DIR = r"c:\dev\iMak\iMak_ichibankuji"
    KUJI_FILE = KUJI_DIR + r"\kuji_urls.txt"
    PENDING_DIR = KUJI_DIR + r"\pending"

    def __init__(self, parent, listing_panel):
        super().__init__(parent)
        self.title("🎁 一番くじ ワークフロー")
        self.geometry("760x540")
        self.listing_panel = listing_panel
        self.proc = None
        self.queue = queue.Queue()
        self._run_log = None  # subprocess stdout の永続 log file (_run_phase で open)
        self.step = 1

        self.step_label = ttk.Label(self, text="", font=("Yu Gothic UI", 12, "bold"), foreground="#0066cc")
        self.step_label.pack(anchor="w", padx=10, pady=(10, 2))
        self.desc_label = ttk.Label(self, text="", foreground="#333", font=("Yu Gothic UI", 9), wraplength=720, justify="left")
        self.desc_label.pack(anchor="w", padx=10, pady=2)

        self.content = ttk.Frame(self)
        self.content.pack(fill="both", expand=True, padx=10, pady=4)

        self.button_frame = ttk.Frame(self)
        self.button_frame.pack(fill="x", padx=10, pady=8)

        self.after(50, self._poll_queue)
        self._show_step1()

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()
        for w in self.button_frame.winfo_children():
            w.destroy()

    def _show_step1(self):
        """Step 1: URL入力"""
        self.step = 1
        self.step_label.config(text="Step 1/4: 1kuji.com URL を貼り付け")
        self.desc_label.config(text="1行1URL で 1kuji.com のシリーズページURLを貼り付け → 「次へ」でPhase1（スクレイプ）開始")
        self._clear_content()
        self.url_text = scrolledtext.ScrolledText(self.content, height=16, font=("Consolas", 10))
        self.url_text.pack(fill="both", expand=True)
        # 既存kuji_urls.txtの中身を初期表示
        try:
            with open(self.KUJI_FILE, "r", encoding="utf-8") as f:
                existing = f.read().strip()
            if existing:
                self.url_text.insert("1.0", existing)
        except FileNotFoundError:
            pass
        ttk.Button(self.button_frame, text="📂 既存ファイル開く",
                   command=self._open_kuji_file).pack(side="left", padx=2)
        ttk.Button(self.button_frame, text="キャンセル", command=self.destroy).pack(side="right", padx=2)
        ttk.Button(self.button_frame, text="次へ → Phase1実行",
                   command=self._start_phase1).pack(side="right", padx=2)

    def _open_kuji_file(self):
        try:
            if sys.platform == "win32":
                os.startfile(self.KUJI_FILE)
            else:
                subprocess.Popen(["xdg-open", self.KUJI_FILE])
        except Exception as e:
            messagebox.showerror("エラー", f"ファイル開けず: {e}")

    def _start_phase1(self):
        text = self.url_text.get("1.0", "end").strip()
        urls = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("http")]
        if not urls:
            messagebox.showwarning("URL未入力", "http で始まるURL を1行以上入力してください")
            return
        # kuji_urls.txt へ保存（上書き）
        try:
            with open(self.KUJI_FILE, "w", encoding="utf-8") as f:
                f.write("\n".join(urls) + "\n")
        except Exception as e:
            messagebox.showerror("エラー", f"kuji_urls.txt 保存失敗: {e}")
            return
        self._show_step2(urls)

    def _show_step2(self, urls):
        """Step 2: Phase1 実行中（ログ表示）"""
        self.step = 2
        self.step_label.config(text=f"Step 2/4: Phase1 実行中（{len(urls)} URLスクレイプ中）")
        self.desc_label.config(text="1kuji.com を巡回して中間CSVを生成中。完了したら自動で次へ。")
        self._clear_content()
        self.log = scrolledtext.ScrolledText(self.content, height=18, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        ttk.Button(self.button_frame, text="🛑 中止",
                   command=self._cancel_proc).pack(side="right", padx=2)
        self._run_phase(["python", "ichibankuji_to_csv.py", "--phase", "1"], on_done=self._after_phase1)

    def _after_phase1(self, returncode):
        # Chrome __del__ の WinError 6 で returncode=None になることがあるが、
        # 中間CSV が新規作成されていれば成功と判定（returncode 無視）
        import glob, time
        candidates = sorted(glob.glob(os.path.join(self.PENDING_DIR, "intermediate_*.csv")))
        if not candidates:
            self._append_log(f"\n❌ Phase1 失敗 (中間CSV未作成, returncode={returncode})\n")
            ttk.Button(self.button_frame, text="閉じる", command=self.destroy).pack(side="right", padx=2)
            return
        latest = candidates[-1]
        # 5分以内に作られた CSV なら今回の Phase1 成果物とみなす
        if time.time() - os.path.getmtime(latest) > 300:
            self._append_log(f"\n❌ 最新中間CSVが古い (今回のPhase1では作られていない)\n   返却コード={returncode}\n")
            ttk.Button(self.button_frame, text="閉じる", command=self.destroy).pack(side="right", padx=2)
            return
        self.intermediate_path = latest
        self._append_log(f"\n✅ 中間CSV確認: {os.path.basename(latest)}\n")
        # Excel で開く
        try:
            if sys.platform == "win32":
                os.startfile(self.intermediate_path)
            else:
                subprocess.Popen(["xdg-open", self.intermediate_path])
        except Exception as e:
            self._append_log(f"⚠️ Excel 自動オープン失敗: {e}\n")
        self._show_step3()

    def _show_step3(self):
        """Step 3: Excel編集待ち"""
        self.step = 3
        self.step_label.config(text="Step 3/4: 中間CSV を Excel で編集")
        self.desc_label.config(text=f"開いたExcelで mercari_url 列 と cost_jpy 列 を手入力 → 保存 → Excelを閉じる → 「編集完了」をクリック\n\n中間CSV: {os.path.basename(self.intermediate_path)}")
        self._clear_content()
        info = tk.Label(self.content, text=(
            "📋 作業:\n"
            "  1. 開いたExcelで各行の mercari_url 列に商品URL を貼る\n"
            "  2. cost_jpy 列に仕入価格（円、数字のみ）を入力\n"
            "  3. 保存（Ctrl+S）\n"
            "  4. Excelを閉じる（開いたままでも動きますが閉じた方が安全）\n"
            "  5. 下の「編集完了 → CSV生成」ボタン\n\n"
            "※ mercari_url が空欄の行は処理対象から自動除外されます"
        ), anchor="w", justify="left", font=("Yu Gothic UI", 10))
        info.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Button(self.button_frame, text="📂 中間CSVをもう一度開く",
                   command=lambda: os.startfile(self.intermediate_path)).pack(side="left", padx=2)
        ttk.Button(self.button_frame, text="キャンセル", command=self.destroy).pack(side="right", padx=2)
        ttk.Button(self.button_frame, text="編集完了 → CSV生成",
                   command=self._start_phase2_and_csv).pack(side="right", padx=2)

    def _start_phase2_and_csv(self):
        """Phase2 (statOHight転記) → デフォルト(CSV生成) を直列で実行"""
        self.step = 4
        self.step_label.config(text="Step 4/4: スプシ転記 + eBay CSV生成")
        self.desc_label.config(text="統合Hight に追記 → Claude API で英語タイトル生成 → eBay CSV 出力")
        self._clear_content()
        self.log = scrolledtext.ScrolledText(self.content, height=18, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        ttk.Button(self.button_frame, text="🛑 中止",
                   command=self._cancel_proc).pack(side="right", padx=2)
        # Phase 2
        self._run_phase(["python", "ichibankuji_to_csv.py", "--phase", "2"], on_done=self._after_phase2)

    def _after_phase2(self, returncode):
        # returncode=None も正常扱い（Chrome __del__ 等の後始末エラー許容）
        if returncode not in (None, 0):
            self._append_log(f"\n❌ Phase2 失敗 (returncode={returncode})\n")
            ttk.Button(self.button_frame, text="閉じる", command=self.destroy).pack(side="right", padx=2)
            return
        self._append_log("\n--- Phase2 完了、続けて eBay CSV 生成 ---\n\n")
        self._run_phase(["python", "ichibankuji_to_csv.py"], on_done=self._after_csv)

    def _after_csv(self, returncode):
        self._clear_content()
        self.step_label.config(text="✅ 完了")
        self.desc_label.config(text="")
        msg = tk.Label(self.content,
                       text=f"処理完了 (returncode={returncode})\n\n"
                            f"eBay CSV: iMakHQ/csv_output/ichibankuji_upload_*.csv\n"
                            f"統合Hight: A-R + U-Z 追記済み\n\n"
                            f"出品完了後、統合Hight B列に ItemID 手入力で「処理済」化してください",
                       justify="left", font=("Yu Gothic UI", 10))
        msg.pack(fill="both", expand=True, padx=10, pady=20)
        ttk.Button(self.button_frame, text="閉じる", command=self.destroy).pack(side="right", padx=2)

    # ========= subprocess 実行共通 =========
    def _run_phase(self, cmd, on_done):
        self.on_done_callback = on_done
        self._append_log(f"▶ 起動: {' '.join(cmd)}\n")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        # ウィザード閉じても残る subprocess stdout file logging
        # (Phase 1/2/3 各 phase 起動ごとに新規 log file 作成)
        try:
            phase_label = "ichibankuji_" + ("phase1" if "1" in cmd else "phase2" if "2" in cmd else "csv")
            self._run_log, log_path = _open_run_log(phase_label)
            self._append_log(f"📝 run log: {log_path}\n")
            self._run_log.write(f"=== {phase_label} ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
            self._run_log.write(f"cwd: {self.KUJI_DIR}\ncmd: {' '.join(cmd)}\n\n")
            self._run_log.flush()
        except Exception as _e:
            self._run_log = None
            self._append_log(f"⚠️ run log 開けず (無視して続行): {_e}\n")
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._listing_start_ts = time.time()  # rarara が今回 CSV のみ対象にするための基準
            self.proc = subprocess.Popen(
                cmd, cwd=self.KUJI_DIR, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=creationflags,
            )
            threading.Thread(target=self._reader, daemon=True).start()
        except Exception as e:
            self._append_log(f"❌ 起動失敗: {e}\n")

    def _reader(self):
        for line in self.proc.stdout:
            self.queue.put(line)
            if self._run_log:
                try:
                    self._run_log.write(line)
                    self._run_log.flush()
                except Exception:
                    pass
        try:
            self.proc.wait(timeout=10)  # stdout閉じた後、プロセス終了を待つ（returncode確定）
        except subprocess.TimeoutExpired:
            pass
        if self._run_log:
            try:
                self._run_log.close()
            except Exception:
                pass
            self._run_log = None
        self.queue.put(("__done__", self.proc.returncode))

    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "__done__":
                    # Step 2: excluder (check_csv NO-GO 行 物理除外) → Step 3: rarara
                    try:
                        captured_log = self.log.get("1.0", "end") if hasattr(self, 'log') else ""
                        _run_excluder_for_latest_csv(self._append_log, captured_log)
                    except Exception as _e:
                        self._append_log(f"\n⚠️ excluder hook 失敗: {_e}\n")
                    _run_rarara_for_latest_csv(self._append_log, since_ts=getattr(self, '_listing_start_ts', None))
                    cb = getattr(self, 'on_done_callback', None)
                    if cb:
                        self.on_done_callback = None
                        cb(item[1])
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll_queue)

    def _append_log(self, text):
        if hasattr(self, 'log') and self.log.winfo_exists():
            self.log.insert("end", text)
            self.log.see("end")
        # ListingPanel の実行ログにもミラー表示 (Wizard 閉じても親窓で確認可能)
        if getattr(self, 'listing_panel', None):
            try:
                self.listing_panel.append_log(text)
            except Exception:
                pass

    def _cancel_proc(self):
        _kill_process_tree(self.proc, self._append_log)


_SINGLE_INSTANCE_LOCK = None  # ソケットを参照保持してプロセス終了まで占有

def _ensure_single_instance(port=53247):
    """localhost ポートをbindして二重起動を防止。既起動時は警告→終了。
    ポート使用中=既起動とみなす。Windows でも追加依存なしで動作。"""
    import socket
    global _SINGLE_INSTANCE_LOCK
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        _SINGLE_INSTANCE_LOCK = sock  # GC防止のためグローバル保持
        return True
    except OSError:
        # 既起動中
        try:
            from tkinter import messagebox as _mb
            _root = tk.Tk()
            _root.withdraw()
            _mb.showwarning("出品くん 二重起動防止",
                            "出品くんは既に起動しています。\n既存ウィンドウを使用してください。\n\n"
                            "（既存が見つからない場合はタスクマネージャーで python.exe を終了してから再起動）")
            _root.destroy()
        except Exception:
            print("⚠️ 出品くんは既に起動しています。")
        return False


def _flush_dns_at_startup():
    """出品くん起動時に Windows DNS cache を flush.

    2026-05-01 18:17 事故対応: psa_to_csv の getaddrinfo failed → 全件 $100 fallback の
    再発防止. 起動時 1 回 flush することで PSA TCG / G-Shock / Mercari / 一番くじ 等
    出品くんから launch される全 program の最初の API call を clean DNS で開始させる.

    本体 logic 不変、失敗時 silent (= flush できなくても起動は継続).
    """
    try:
        import sys as _sys, os as _os
        _imakeBayAPI = _os.path.join(
            _os.path.dirname(_os.path.abspath(__file__)), "..", "iMakeBayAPI"
        )
        if _imakeBayAPI not in _sys.path:
            _sys.path.insert(0, _imakeBayAPI)
        from dns_resilience import flush_dns_cache
        if flush_dns_cache():
            print("[startup] DNS cache flushed (Windows ipconfig /flushdns)")
    except Exception as _e:
        # 起動を妨げない (Linux/macOS / dns_resilience 不在 等は silent)
        pass


def main():
    _flush_dns_at_startup()
    if not _ensure_single_instance():
        return
    root = tk.Tk()
    HomePanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
