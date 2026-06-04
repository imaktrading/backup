#!/usr/bin/env python3
"""iMak Trading Japan 操作パネル
スクリプト直接実行用GUI。Claude仲介不要。

追加方法: SCRIPTS リストに項目を1つ追加するだけ。
"""
import os
import re
import sys
import subprocess
import threading
import time
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WORKSPACE = r"c:/dev/iMak"
EBAY_SELLER = "imax-64"
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
        if result["removed"] > 0:
            append_log_func("\n" + "=" * 70 + "\n▶ csv_postprocess_excluder (NO-GO 行物理除外)\n" + "=" * 70 + "\n")
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

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

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
        "params": [],
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
    {
        "category": None, "type": "utility",
        "label": "取下再出品",
        "label_fg": "red",  # ボタンラベル赤文字 (取下→再出品のフロー起点を強調)
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "relist_from_funnel.py"],  # ファネルRELIST候補→End CSV (snapshot不要)
        "params": [],
        "open_after": r"C:/Users/imax2/OneDrive/デスクトップ/取下再出品候補_*.csv",
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
        "open_after": r"C:/Users/imax2/OneDrive/デスクトップ/出品ファネル分析_*.xlsx",
    },
    {
        "category": None, "type": "utility",
        "label": "📈 需要・新規強化リスト",
        "label_fg": "blue",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "demand_winners.py"],
        "params": [],
        "open_after": r"C:/Users/imax2/OneDrive/デスクトップ/新規出品強化_グループ別_*.csv",
    },
    # 2026-06-04: G-SHOCK価格調査(amazon_v8_check/mercari_gshock_resource)とタイトル改修(title_keyword_proposal)は
    #   一度きりの調査ツールで在庫あり文脈で紛らわしいためパネルから除外 (tools/ に .py は残置=直叩き可)。
    {
        "category": None, "type": "utility",
        "label": "🃏 PSA再仕入れ照合(メルカリ)",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "mercari_psa_resource.py"],
        "params": [],
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
        ttk.Button(nav, text="🔄 更新", command=self.refresh_dashboard).pack(side="right", padx=2)
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

        # ツールバー (共有 🛑 停止)
        toolbar = ttk.Frame(root, padding=(8, 4))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="🛑 実行中を停止", width=18,
                   command=self.stop_script).pack(side="right")

        top_frame = ttk.LabelFrame(root, text="スクリプト一覧", padding=8)
        top_frame.pack(fill="x", padx=8, pady=(0, 4))

        canvas = tk.Canvas(top_frame, height=320)
        scrollbar = ttk.Scrollbar(top_frame, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        _win_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        # 内側フレームを canvas 幅いっぱいに広げる (= 右側の空白を無くし全幅レイアウトに)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(_win_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 5/12 構成変更: カテゴリ別 Labelframe + 新規/再出品 2ボタン + Utility 単独ボタン
        # - 新規ボタン: verified=True → 青、それ以外 → 黒 (既存ルール維持)
        # - 再出品ボタン: 黒
        # - verified カテゴリを先頭にまとめる (ユーザー要望)
        self.param_entries = {}
        self._run_log = None

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
            if any(s in cmd for s in ("listing_funnel", "demand_winners")):
                return "analyze"   # 📊 分析 (Plan/Check)
            if "mercari_psa_resource" in cmd:
                return "oos"       # 在庫なし 再仕入れ
            if any(s in cmd for s in ("casio_finder", "montbell_outlet_scraper", "mercari_scout.py")):
                return "discover"  # 新規ネタ探し
            if "dump_us_qty1_sku" in cmd:
                return "relist"    # 在庫あり 取り下げ再出品(view0死蔵)
            return "report"
        ug = {"analyze": [], "oos": [], "discover": [], "relist": [], "report": []}
        for idx in utilities:
            ug[_ugroup(idx)].append(idx)

        # 共通: (label, idx) のリストを ncol 列グリッドで描画。ボタンは全画面で同一サイズ
        # (左右=狭め width / 上下=広め height、中央寄せ=ストレッチさせず統一見た目)。
        BTN_W, BTN_H, BTN_WL = 13, 3, 110

        def _grid_named(parent, items, ncol=4, compact=False):
            ncol = max(1, min(ncol, len(items)))  # 項目数より多い列は作らない
            for col in range(ncol):
                parent.columnconfigure(col, weight=1, uniform=f"g{id(parent)}")
            for k, (text, idx) in enumerate(items):
                color = SCRIPTS[idx].get("label_fg") or ("#0066cc" if SCRIPTS[idx].get("verified", False) else "black")
                tk.Button(parent, text=text, font=("", 9, "bold"), fg=color,
                          width=BTN_W, height=BTN_H, wraplength=BTN_WL, justify="center",
                          command=lambda i=idx: self.run_script(i)).grid(
                    row=k // ncol, column=k % ncol, padx=3, pady=3)  # sticky無し=中央寄せ・統一サイズ

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
                color = "#0066cc" if SCRIPTS[new_idx].get("verified", False) else "black"
                tk.Button(cat_grid, text=cat_name, font=("", 11, "bold"), fg=color,
                          width=BTN_W, height=BTN_H, wraplength=BTN_WL, justify="center",
                          command=lambda idx=new_idx: self.run_script(idx)).grid(
                    row=gi // n_cat_cols, column=gi % n_cat_cols, padx=3, pady=3)  # 統一サイズ・中央寄せ
                gi += 1
            if ug["discover"]:
                disc = ttk.LabelFrame(new_sec, text="発見・巡回 (新規ネタ探し)", padding=4)
                disc.pack(fill="x", pady=(8, 0))
                _grid_named(disc, [(SCRIPTS[i]["label"], i) for i in ug["discover"]])
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
                text=("Seller Hub で下記4レポートをDL → 📁reports フォルダに置く:\n"
                      "  ・eBay-all-active-listings\n"
                      "  ・ebay-all-orders-report\n"
                      "  ・eBay-unsold-listings-report\n"
                      "  ・Listing quality report"),
            ).pack(anchor="w", pady=(4, 0))

            # 📊 分析 (押すと結果ファイルが開く)
            ana = ttk.LabelFrame(scroll_frame, text="📊 分析 (押すと結果ファイルが開く)", padding=4)
            ana.pack(fill="x", padx=4, pady=(4, 0))
            _grid_named(ana, [(SCRIPTS[i]["label"], i) for i in ug["analyze"]])

            # 🔧 在庫あり / 📦 在庫なし を横並び (詰めて配置)
            stock_row = ttk.Frame(scroll_frame)
            stock_row.pack(fill="x", padx=4, pady=(6, 0))
            stock_row.columnconfigure(0, weight=1, uniform="stk")
            stock_row.columnconfigure(1, weight=1, uniform="stk")
            relist_items = [(SCRIPTS[i]["label"], i) for i in ug["relist"]]
            relist_items += [(f"{cat} 再出品", categories[cat]["relist"])
                             for cat in cat_order if categories[cat].get("relist") is not None]
            d1 = ttk.LabelFrame(stock_row, text="🔧 在庫あり — 取り下げ再出品", padding=2)
            d1.grid(row=0, column=0, sticky="nsew", padx=(0, 3))
            _grid_named(d1, relist_items, ncol=3, compact=True)
            d2 = ttk.LabelFrame(stock_row, text="📦 在庫なし — 再仕入れ", padding=2)
            d2.grid(row=0, column=1, sticky="nsew", padx=(3, 0))
            _grid_named(d2, [(SCRIPTS[i]["label"], i) for i in ug["oos"]], ncol=2, compact=True)

            if ug["report"]:
                rep = ttk.LabelFrame(scroll_frame, text="📈 レポート", padding=4)
                rep.pack(fill="x", padx=4, pady=(8, 0))
                _grid_named(rep, [(SCRIPTS[i]["label"], i) for i in ug["report"]])

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
        cmd = list(script["cmd"])
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

    def poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "__done__":
                    self.append_log(f"\n--- 終了 (returncode={item[1]}) ---\n")
                    # open_after: 結果ファイル(最新)を自動で開く (ファネル分析/需要強化 等)
                    _oa = SCRIPTS[getattr(self, "_current_idx", -1)].get("open_after") if getattr(self, "_current_idx", -1) >= 0 else None
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
                    # Step 2: csv_postprocess_excluder (check_csv NO-GO 行を CSV 物理除外)
                    # Step 2.5: post_title_fix (TCG タイトル長補強・PSA 名前正規化, 2026-05-02 追加)
                    # Step 3: rarara (CSV outlier 検出) - excluder 後の CSV を分析
                    try:
                        captured_log = self.log.get("1.0", "end") if hasattr(self, 'log') else ""
                        _run_excluder_for_latest_csv(self.append_log, captured_log)
                    except Exception as _e:
                        self.append_log(f"\n⚠️ excluder hook 失敗: {_e}\n")
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
                    try:
                        _run_dedupe_for_latest_csv(self.append_log, since_ts=getattr(self, '_listing_start_ts', None))
                    except Exception as _e:
                        self.append_log(f"\n⚠️ dedupe hook 失敗: {_e}\n")
                    # Step 5: post_psa_review (2026-05-28 追加、 PSA TCG cert HTML viewer ユーザー判定 hook)
                    # 5/29 修正: 今 cycle で生成された tcg_upload_*.csv のみ対象 (= TCG 以外 cycle で毎回 HTML 出る問題対策)
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
                        if _latest_csv:
                            run_post_psa_review(_latest_csv, self.append_log)
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
                    self.append_log("\n" + "=" * 70 + "\n")
                    self.append_log("🎉 全 process 完了 — 入稿準備 OK\n")
                    if _latest_csv:
                        self.append_log(f"   出力 CSV: {_latest_csv}\n")
                    from datetime import datetime as _dt
                    self.append_log(f"   終了時刻: {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    self.append_log("=" * 70 + "\n")
                    self.status_var.set("待機中")
                    self.now_processing.set("")
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
