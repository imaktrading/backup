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
    # 取下再出品 ①②③ を上段、✏️タイトル改修/💲価格抵抗 を下段に並べる (3列グリッド=d1)。
    # 表示順は _ugroup "relist" 群の SCRIPTS 出現順なので ①②③→タイトル改修→価格抵抗 の順で置く。
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
        # ④: NO_CLICK ∩ watcher有 を手 revise 対象として CSV 出力 (2026-06-05)。①の下段
        "category": None, "type": "utility",
        "label": "✏️ タイトル改修",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "noclick_targets.py"],
        "params": [],
        # 結果は「既存メンテ」スプシ タイトル改修タブに集約 (CSV廃止)
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit",
    },
    {
        # NO_CONVERT: 高クリック無販売を自分の実売(proven)と照合=価格抵抗 (2026-06-05)。②の下段
        "category": None, "type": "utility",
        "label": "💲 価格抵抗",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "price_resistance.py"],
        "params": [],
        # 結果は「既存メンテ」スプシ 価格抵抗タブに集約 (CSV廃止)
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit",
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
        "open_url": "https://docs.google.com/spreadsheets/d/1UkaI4W6YCJgUbjgF7LLNN9_fHeVuz5qB4r9RqImElwg/edit",
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
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit",
    },
    {
        "category": None, "type": "utility",
        "label": "📈 需要・新規強化",
        "label_fg": "blue",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "demand_winners.py"],
        "params": [],
        # 結果は「既存メンテ」スプシ 需要・新規強化タブに集約 (CSV廃止)
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit",
    },
    # 2026-06-04: G-SHOCK価格調査(amazon_v8_check/mercari_gshock_resource)とタイトル改修(title_keyword_proposal)は
    #   一度きりの調査ツールで在庫あり文脈で紛らわしいためパネルから除外 (tools/ に .py は残置=直叩き可)。
    {
        "category": None, "type": "utility",
        "label": "🃏 PSA再仕入れ照合",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        # 2チャネル(Mercari＆SNKRDUNK)ゲート。探索前に①現物(出品PSA)=②catalog の目視確認ゲートが
        # ブラウザで開く→一致分だけ探索。不一致はPDCA台帳(原因別振り分け)。旧 mercari_psa_resource.py
        # (Mercari単体・確認/PDCA無し)から張替 (2026-06-17)。
        "cmd": ["python", "psa_resource_gate.py"],
        "params": [],
        # 結果は「既存メンテ」スプシ PSA再仕入れタブに集約 (CSV廃止。再仕入れ系をシート統一)
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit",
    },
    {
        # RESTOCK後工程① 視覚確証で確定したカードを 新コア生成→Revise CSV化(手動UL用)。2026-06-18
        "category": None, "type": "utility",
        "label": "♻ RESTOCK Revise CSV生成",
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
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "psa_restock_writeback.py"],
        "params": [],
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit",
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
        "open_url": "https://docs.google.com/spreadsheets/d/1UAVBdosIqqOI8qx-P-4k_ftTGuGWGzfIOU7vk7S2dz4/edit",
    },
    {
        # B: CULL(在庫切れ&需要皆無) を age>=21・CAP50/回 で段階 End CSV 化 (2026-06-05)
        "category": None, "type": "utility",
        "label": "🧹 CULL停止 (50件/回)",
        "cwd": f"{WORKSPACE}/iMakHQ/tools",
        "cmd": ["python", "cull_end.py"],
        "params": [],
        "open_after": r"C:/Users/imax2/OneDrive/デスクトップ/CULL出品停止候補_*.csv",
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
            if any(s in cmd for s in ("mercari_psa_resource", "restock_worklist", "cull_end")):
                return "oos"       # 在庫なし 再仕入れ(RESTOCK) / 整理(CULL)
            if any(s in cmd for s in ("casio_finder", "montbell_outlet_scraper", "mercari_scout.py")):
                return "discover"  # 新規ネタ探し
            # 在庫あり listing を直す: 取下再出品①②③(NO_SEARCH) / ✏️タイトル(NO_CLICK) / 💲価格(NO_CONVERT)
            if any(s in cmd for s in ("relist_from_funnel", "relist_add_from_pending",
                                      "relist_writeback", "dump_us_qty1_sku",
                                      "noclick_targets", "price_resistance")):
                return "relist"
            return "report"
        ug = {"analyze": [], "oos": [], "discover": [], "relist": [], "report": [], "audit": []}
        for idx in utilities:
            ug[_ugroup(idx)].append(idx)

        # 共通: (label, idx) のリストを ncol 列グリッドで描画 (compact=詰めた配置)
        def _grid_named(parent, items, ncol=4, compact=False):
            # height=2 で2行ぶんの高さを確保 (ラベルが折返しても見切れない)。width は最小値=
            # columnconfigure(weight) と sticky="nsew" で実幅は親いっぱいに伸びる。
            w, h, pad, wl = (14, 2, 2, 150) if compact else (16, 2, 4, 230)
            ncol = max(1, min(ncol, len(items)))  # 項目数より多い列は作らない (右の空セル防止)
            for col in range(ncol):
                parent.columnconfigure(col, weight=1, uniform=f"g{id(parent)}")
            for k, (text, idx) in enumerate(items):
                color = SCRIPTS[idx].get("label_fg") or ("#0066cc" if SCRIPTS[idx].get("verified", False) else "black")
                tk.Button(parent, text=text, font=("", 9, "bold"), fg=color,
                          width=w, height=h, wraplength=wl, justify="center",
                          command=lambda i=idx: self.run_script(i)).grid(
                    row=k // ncol, column=k % ncol, padx=pad, pady=pad, sticky="nsew")

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
                tk.Button(cat_grid, text=cat_name, font=("", 12, "bold"), fg=color,
                          width=15, height=2, wraplength=150, justify="center",
                          command=lambda idx=new_idx: self.run_script(idx)).grid(
                    row=gi // n_cat_cols, column=gi % n_cat_cols, padx=2, pady=2, sticky="nsew")
                gi += 1
            if ug["discover"]:
                disc = ttk.LabelFrame(new_sec, text="発見・巡回 (新規ネタ探し)", padding=4)
                disc.pack(fill="x", pady=(8, 0))
                _grid_named(disc, [(SCRIPTS[i]["label"], i) for i in ug["discover"]])
            if ug["audit"]:
                aud = ttk.LabelFrame(new_sec, text="🔍 出品前チェック (CSV生成後に実行)", padding=4)
                aud.pack(fill="x", pady=(8, 0))
                _grid_named(aud, [(SCRIPTS[i]["label"], i) for i in ug["audit"]])
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
                    fs = _glob.glob(os.path.join(REPORTS_DIR, pat))
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
            # 3列: 上段①②③ / 下段✏️タイトル改修(①下)・💲価格抵抗(②下) が縦に揃う
            _grid_named(d1, relist_items, ncol=3)
            d2 = ttk.LabelFrame(scroll_frame, text="📦 在庫なし — 再仕入れ / 整理", padding=4)
            d2.pack(fill="x", padx=4, pady=(6, 0))
            _grid_named(d2, [(SCRIPTS[i]["label"], i) for i in ug["oos"]], ncol=4)

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
                    _runs = -(-_cull_n // 50)  # ceil
                    tk.Label(scroll_frame, anchor="w", font=("Yu Gothic UI", 9, "bold"),
                             fg="#444", text=(f"   🛒 RESTOCK再仕入れ(US) {_rs_n}商品   "
                                              f"｜   🧹 CULL停止 残 {_cull_n}件 (50件/回 = 約{_runs}回分)")
                             ).pack(anchor="w", padx=4, pady=(2, 0))
            except Exception:
                pass

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

    def poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "__done__":
                    self.append_log(f"\n--- 終了 (returncode={item[1]}) ---\n")
                    # open_after: 結果ファイル(最新)を自動で開く (ファネル分析/需要強化 等)
                    _cur = SCRIPTS[getattr(self, "_current_idx", -1)] if getattr(self, "_current_idx", -1) >= 0 else {}
                    _oa = _cur.get("open_after")
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
                            captured_log = self.log.get("1.0", "end") if hasattr(self, 'log') else ""
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
                    if not _skip_pp:
                        try:
                            _run_dedupe_for_latest_csv(self.append_log, since_ts=getattr(self, '_listing_start_ts', None))
                        except Exception as _e:
                            self.append_log(f"\n⚠️ dedupe hook 失敗: {_e}\n")
                    # Step 4.5: RESTOCK Revise 変換 (2026-06-20)。excluder/title-fix/dedup の **後** に、
                    # 最終クリーンな Add CSV を Add→Revise 化する(順序保証=赤字/重複/旧タイトルを含めない)。
                    # ♻ ボタン (restock_revise=True) の時のみ。旧: psa_restock_build が dedup 前に変換→混入バグ。
                    try:
                        _ridx = getattr(self, "_current_idx", -1)
                        if _ridx >= 0 and SCRIPTS[_ridx].get("restock_revise"):
                            _run_restock_revise_for_latest_csv(
                                self.append_log, since_ts=getattr(self, '_listing_start_ts', None))
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
                    if _verify_before_build:
                        self.append_log("\n(post_psa_review: verify→build で生成前に確認済 — 後付け hook skip)\n")
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
                        if _latest_csv and not _verify_before_build:
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
