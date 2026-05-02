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
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WORKSPACE = r"c:/dev/iMak"
KEYWORDS_DIR = f"{WORKSPACE}/iMakKeywords"
EBAY_SELLER = "imax-64"
EBAY_KEYS_FILE = f"{WORKSPACE}/iMakeBayAPI/ebay keys.txt"

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
# SHEET_CATEGORY_MAP は廃止（自動取得に変更）
GSHEET_CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"

# ============ 参考リンク（最新売れ筋 / キーワード調査用） ============
# 四半期更新されるeBayキーワードPDFへのリンク（iMakKeywords/）
KEYWORD_PDF = {
    "clothing": f"{KEYWORDS_DIR}/Clothing_Shoes_Accessories_2026Q1.pdf",
    "toys":     f"{KEYWORDS_DIR}/Toys_Hobbies_2026Q1.pdf",
    "collect":  f"{KEYWORDS_DIR}/Collectibles_2026Q1.pdf",
    "watches":  f"{KEYWORDS_DIR}/Jewelry_Watches_2026Q1.pdf",
    "sports":   f"{KEYWORDS_DIR}/Sporting_goods_2026Q1.pdf",
    "cameras":  f"{KEYWORDS_DIR}/Cameras_Photo_2026Q1.pdf",
    "home":     f"{KEYWORDS_DIR}/Home_Garden_2026Q1.pdf",
    "video":    f"{KEYWORDS_DIR}/Video_Games_2026Q1.pdf",
}

# ============ トレンド/相場リサーチ リンク集 ============
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
def _run_rarara_for_latest_csv(append_log_func):
    """csv_output/ の最新 CSV に対して rarara を実行.

    Args:
        append_log_func: panel 固有のログ追記関数 (self.append_log 等)
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


# 全商品共通のリサーチサイト
COMMON_TREND_LINKS = [
    ("Google Trends（日本）", "https://trends.google.co.jp/trends/trendingsearches/daily?geo=JP"),
    ("Google Trends（US）",   "https://trends.google.com/trends/trendingsearches/daily?geo=US"),
    ("ヤフオク 落札相場検索",   "https://aucfan.com/"),
    ("駿河屋 相場検索",        "https://www.suruga-ya.jp/"),
    ("eBay Trending",         "https://pages.ebay.com/trends/"),
    ("eBay Terapeak（有料）",  "https://www.ebay.com/sh/research"),
]

# カテゴリ別リサーチリンク
TREND_LINKS = {
    "tshirt": [
        ("メルカリ UT人気順",    "https://jp.mercari.com/search?keyword=UT&sort=num_likes&order=desc&status=sold_out"),
        ("メルカリ UT SOLD",     "https://jp.mercari.com/search?keyword=UT&sort=created_time&order=desc&status=sold_out"),
        ("UNIQLO 公式コラボ",    "https://www.uniqlo.com/jp/ja/contents/feature/ut/"),
        ("Grailed (海外)",       "https://www.grailed.com/shop/uniqlo"),
        ("StockX Tシャツ",       "https://stockx.com/tees"),
        ("Stock Keeping (Rakuten) eBay売れ筋", "https://www.worthpoint.com/"),
    ],
    "montbell": [
        ("メルカリ montbell 人気順", "https://jp.mercari.com/search?keyword=montbell&sort=num_likes&order=desc"),
        ("メルカリ montbell SOLD",  "https://jp.mercari.com/search?keyword=montbell&status=sold_out&sort=created_time&order=desc"),
        ("Montbell 公式アウトレット", "https://www.montbell.jp/products/list.php?category_id=1040"),
        ("Yamap 人気ギア",         "https://yamap.com/shop"),
        ("Grailed Montbell",       "https://www.grailed.com/shop/montbell"),
    ],
    "porter": [
        ("メルカリ PORTER 人気順", "https://jp.mercari.com/search?keyword=PORTER&sort=num_likes&order=desc"),
        ("メルカリ PORTER SOLD",  "https://jp.mercari.com/search?keyword=PORTER&status=sold_out&sort=created_time&order=desc"),
        ("吉田カバン 公式新作",    "https://www.yoshidakaban.com/"),
        ("Grailed Porter",        "https://www.grailed.com/shop/porter-yoshida-co"),
        ("BEAMS別注検索",         "https://www.beams.co.jp/search/?keyword=porter"),
    ],
    "tomica": [
        ("メルカリ トミカ 人気順", "https://jp.mercari.com/search?keyword=%E3%83%88%E3%83%9F%E3%82%AB&sort=num_likes&order=desc"),
        ("メルカリ トミカ SOLD",  "https://jp.mercari.com/search?keyword=%E3%83%88%E3%83%9F%E3%82%AB&status=sold_out&sort=created_time&order=desc"),
        ("ヤフオク トミカ落札相場", "https://aucfan.com/search1/q-~e3~83~88~e3~83~9f~e3~82~ab/"),
        ("駿河屋 トミカ",         "https://www.suruga-ya.jp/search?category=&search_word=%E3%83%88%E3%83%9F%E3%82%AB"),
        ("トミカランド情報",      "https://www.takaratomymall.jp/shop/contents2/tomicaland.aspx"),
        ("まんだらけ トミカ",     "https://order.mandarake.co.jp/order/listPage/list?keyword=%E3%83%88%E3%83%9F%E3%82%AB&lang=ja"),
    ],
    "tcg": [
        ("メルカリ PSA10 人気順",  "https://jp.mercari.com/search?keyword=PSA10&sort=num_likes&order=desc"),
        ("メルカリ PSA10 SOLD",   "https://jp.mercari.com/search?keyword=PSA10&status=sold_out&sort=created_time&order=desc"),
        ("PriceCharting TCG",     "https://www.pricecharting.com/category/trading-cards"),
        ("TCGplayer",             "https://www.tcgplayer.com/"),
        ("Cardmarket (EU)",       "https://www.cardmarket.com/"),
        ("One Piece TCG Meta",    "https://onepiecetopdecks.com/"),
        ("Pokemon Prices",        "https://www.pokeprice.io/"),
        ("PSA Cert Pop Report",   "https://www.psacard.com/pop"),
    ],
    "gshock": [
        ("メルカリ G-SHOCK人気順", "https://jp.mercari.com/search?keyword=G-SHOCK&sort=num_likes&order=desc"),
        ("メルカリ G-SHOCK SOLD", "https://jp.mercari.com/search?keyword=G-SHOCK&status=sold_out&sort=created_time&order=desc"),
        ("Chrono24 G-SHOCK",      "https://www.chrono24.com/casio/index.htm"),
        ("WatchCharts G-SHOCK",   "https://watchcharts.com/watches/brand/casio"),
        ("G-Central (海外ブログ)", "https://www.g-central.com/"),
        ("CasioFanMag",          "https://casiofanmag.com/"),
        ("CASIO 公式新作",        "https://gshock.casio.com/jp/products/new-arrivals/"),
    ],
    "kuji": [
        ("メルカリ 一番くじ人気順", "https://jp.mercari.com/search?keyword=%E4%B8%80%E7%95%AA%E3%81%8F%E3%81%98&sort=num_likes&order=desc"),
        ("メルカリ ラストワン賞",  "https://jp.mercari.com/search?keyword=%E3%83%A9%E3%82%B9%E3%83%88%E3%83%AF%E3%83%B3&sort=num_likes&order=desc"),
        ("メルカリ 一番くじSOLD", "https://jp.mercari.com/search?keyword=%E4%B8%80%E7%95%AA%E3%81%8F%E3%81%98&status=sold_out&sort=created_time&order=desc"),
        ("1kuji.com 公式",       "https://1kuji.com/"),
        ("駿河屋 一番くじ",       "https://www.suruga-ya.jp/search?category=&search_word=%E4%B8%80%E7%95%AA%E3%81%8F%E3%81%98"),
        ("まんだらけ フィギュア",  "https://order.mandarake.co.jp/order/"),
    ],
    "scout": [
        ("メルカリ 新着（カテゴリ指定）", "https://jp.mercari.com/"),
        ("Mercari Shops",         "https://mercari-shops.com/"),
    ],
}

# ============ スクリプト登録 ============
SCRIPTS = [
    {
        "label": "Tシャツ (UNIQLO UT)",
        "verified": True,  # 2026-04-19 ユーザーチェック合格
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "tshirt_listing.py"],
        "params": [{"name": "--limit", "label": "件数", "default": "5"}],
        "desc": "スプシのItemIDブランク行から N件をeBay CSV化",
        "trend_key": "tshirt",
        "keyword_pdf": KEYWORD_PDF["clothing"],
        "flow": """【商品選定】ユーザー、抽出はトラバホ

【スプシ】TSHIRT_SHEET_ID = "1QI0-L1A1DfTEi8Hl1-EFuRl9oTw9QPFe3X85stnaOD4" (gid 851100680)
  - 列: A=URL / B=ItemID / C=JPタイトル / D=Sold / E=状態 / F=価格 / G=写真URL / N=仕入価格(優先)
  - 処理対象: ItemID空 & Sold空 の行
  - スルー: ItemIDに値あり（出品済 or 「9999」見送り済）/ Sold

【スプシ書込】
  - GU商品 / 乖離超ALERT見送り → 「9999」をitemID列に自動書込
  - 永久ループ防止（次回以降スルーされる）
  - 復活させたい場合は手動で「9999」削除

【パイソン処理】
  1. 【個別】メルカリ/ラクマ写真URLの先頭1枚をBase64化
  2. 【個別】Claude API(sonnet-4) → 英タイトル / コラボ名 / Item Specifics
  3. 【個別】UNIQLO公式API → 公式画像URL（任意）
  4. 【個別】eBay TOPセラー検索 → 中央値・参考Item Specifics取得
  5. 【共通】価格決定: pricing_engine.compute_listing_price
       - PROFIT_CATEGORY = "Tシャツ(UT)" (FVF 15.3%, 送料 ¥2,000)
       - コストプラス + 価格帯別利益率上限 + 乖離率TBL判定
       - ALERT時: itemID列に「9999」セット → CSV除外
  6. 【個別】ストアカテゴリ = コラボ名で自動マッチ(34種登録、PDF最新版同期済)
  7. 【個別】SKU = メルカリ商品ID(m...) / ラクマは末尾8桁
  8. 【共通】listing_validator.py で禁止語/必須項目チェック (3AI議論方式)
  9. 【個別】GU(ジーユー)商品は自動スキップ→「9999」マーク
  10. 【個別】Country/Region = "Does not apply" 固定 (海外製造のため)
  11. 【個別】タイトルに型番(MPN)を含めない (Item Specs Modelには記入)
  12. 【個別】Location = "Japan, Osaka"

【出力CSV】iMakHQ/csv_output/tshirt_upload_YYYYMMDD_HHMMSS.csv
【eBay取込】手動 FileExchange アップロード
【売れたら】SKUからメルカリ商品IDで仕入元即特定
""",
    },
    {
        "label": "Montbell",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "montbell_listing.py"],
        "params": [],
        "desc": "Montbellスプシから全件CSV化",
        "trend_key": "montbell",
        "keyword_pdf": KEYWORD_PDF["clothing"],
        "flow": """【商品選定】ユーザー、抽出はトラバホ

【スプシ】MONTBELL_SHEET_ID
  - 処理対象: ItemID空 & Sold空 の行
  - スルー: ItemIDに値あり（出品済 or 「9999」見送り済）

【スプシ書込】
  - 乖離超ALERT見送り → 「9999」をitemID列に自動書込
  - 永久ループ防止（次回以降スルー）
  - 復活させたい場合は手動で「9999」削除

【パイソン処理】
  1. 【個別】メルカリ写真DL + montbell公式画像取得(型番から)
  2. 【個別】Claude API → 英タイトル / Item Specifics
  3. 【個別】eBay TOPセラー参照（中央値取得）
  4. 【共通】価格決定: pricing_engine.compute_listing_price
       - コストプラス + 価格帯別利益率上限 + 乖離率TBL判定
       - ALERT時: itemID列に「9999」セット → CSV除外
  5. 【個別】SKU = メルカリ商品ID
  6. 【個別】ストアカテゴリ: Outdoor Jackets (41828939010)
  7. 【共通】listing_validator.py

【出力CSV】iMakHQ/csv_output/montbell_*.csv
【テンプレ】USED.txt(中古)
【ConditionID】3000 (Pre-owned)
""",
    },
    {
        "label": "Porter",
        "verified": True,  # 2026-04-19 ユーザーチェック合格
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_to_ebay_csv.py", "--sheet", "porter"],
        "params": [],
        "desc": "Porter専用スプシから直読 → eBayアップロード可能なCSV生成",
        "trend_key": "porter",
        "keyword_pdf": KEYWORD_PDF["clothing"],
        "flow": """【商品選定】ユーザー、抽出はトラバホ

【スプシ】1ZbgF5cT-S726DKPI7iMsnX2PPxMjLh3w7GzsDf8OWEk (gid=0)
  - 列: A=URL / B=ItemID / C=タイトル / D=Sold / E=状態 / F=価格(仕入) / G=写真URL / H=説明
  - 処理対象: ItemID空 & Sold空 の行
  - スルー: ItemIDに値あり（出品済 or 「9999」見送り済）

【パイソン処理】
  1. 【共通】メルカリ写真DL + Claude API解析（英タイトル/Item Specifics/Condition Description）
  2. 【共通】価格決定: pricing_engine.compute_listing_price
       - PROFIT_CATEGORY = "Porter" (FVF 15.3%, 送料 ¥2,500)
       - コストプラス + 価格帯別利益率上限
       - 中央値取得なし → NO_MEDIAN (乖離判定スキップ)
  3. 【個別】SKU = メルカリ商品ID(m...) / shopsはハッシュ末尾12桁
  4. 【個別】Description = USED.txt テンプレ + Item Specs挿入
  5. 【個別】eBay リーフカテゴリ = 52357 (過去成功実績、Type必須なし)
  6. 【個別】Store カテゴリ = 41828940010 (Backpacks & Bags)
  7. 【個別】ConditionID = 3000 (Used)
  8. 【個別】Location = "Japan, Osaka"
  9. 【個別】Country of Origin = Japan (Made in Japan確定)

【出力CSV】iMakHQ/csv_output/mercari_upload_YYYYMMDD_HHMMSS.csv
【eBay取込】手動 FileExchange アップロード可能な完全形式
【売れたら】SKUからメルカリ商品IDで仕入元即特定
""",
    },
    {
        "label": "Tomica",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_to_ebay_csv.py", "--sheet", "tomica"],
        "params": [],
        "desc": "Tomica専用スプシから直読 → CSV化",
        "trend_key": "tomica",
        "keyword_pdf": KEYWORD_PDF["toys"],
        "flow": """【商品選定】ユーザー、抽出はトラバホ

【スプシ】1DVTQlpK5cemEbZ_NNDkwXZDWslNb7T4veNIuMH1_9Nc (gid=851100680)
  - 列構成同上（Tshirt/Montbellと同じ）
  - 処理対象: ItemID空 & Sold空 の行
  - スルー: ItemIDに値あり（出品済 or 「9999」見送り済）
  - カテゴリ強制: Tomica（Claude判定スキップ）

【スプシ書込】スキップ時に自動「9999」マーク
  - 画像取得失敗 / Claude API失敗 / validator失敗 → 9999
  - 一時エラーで再試行したい場合は手動で9999削除

【パイソン処理】
  1. 【共通】メルカリ写真DL + Claude API解析
  2. 【共通】価格決定: pricing_engine.compute_listing_price
       - 中央値取得なし → 乖離判定スキップ
  3. 【個別】Tomica固有のItem Specifics生成
  4. 【共通】listing_validator.py

【出力CSV】iMakHQ/csv_output/mercari_generic_*.csv
""",
    },
    {
        "label": "その他混在シート (CSV運用)",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_to_ebay_csv.py"],
        "params": [],
        "desc": "Vintage/Fishing/Other 等を商品管理シート.csv から処理",
        "trend_key": "tomica",  # とりあえずtomica系を暫定適用（Vintage/Collectibles系）
        "flow": """【入力】商品管理シート.csv (ローカル)
  - 専用スプシがないカテゴリ用（Vintage/Fishing/Other）
  - 共有シートをCSVエクスポートして配置

【パイソン処理】
  1. 【個別】メルカリ写真DL + Claude APIでカテゴリ判定
  2. 【個別】カテゴリ別の処理分岐
  3. 【共通】価格決定: pricing_engine.compute_listing_price
  4. 【共通】listing_validator.py

【出力CSV】iMakHQ/csv_output/mercari_generic_*.csv
※ 共有シートのSheet ID提供で gspread直読化可能
""",
    },
    {
        "label": "G-SHOCK",
        "cwd": f"{WORKSPACE}/iMakG-shock",
        "cmd": ["python", "gshock_to_csv.py"],
        "urls_file": f"{WORKSPACE}/iMakG-shock/gshock_urls.txt",
        "params": [],
        "desc": "URLs.txtからCSV生成",
        "trend_key": "gshock",
        "keyword_pdf": KEYWORD_PDF["watches"],
        "flow": """【入力】gshock_urls.txt (1行1URL) もしくはスプシGSHOCK_SHEET_ID

【パイソン処理】
  1. 【個別】Casio公式から型番でスペック取得(Selenium)
  2. 【個別】公式画像 + g-central + casiofanmag 参照
  3. 【個別】Claude API + キーワードPDF参照でタイトル生成
  4. 【共通】価格決定: pricing_engine.compute_listing_price
       - コストプラス + 価格帯別利益率上限
       - 中央値取得なし → 乖離判定スキップ（NO_MEDIAN）
  5. 【共通】listing_validator.py

【出力CSV】iMakHQ/csv_output/gshock_*.csv
【ConditionID】1000 (新品)
※ 中央値取得追加で乖離判定も発動可能
""",
    },
    {
        "label": "PSA TCG (One Piece / Dragon Ball)",
        "verified": True,  # 2026-04-24 及第点到達（スプシ駆動、Claude推測全廃、Bandai辞書/fetch_card/Gundam補正、プロモ二重国籍許容、pipeline 二重基準解消、eBay入稿8件実績）
        "double_check": True,  # 2026-04-26 入稿前の人手ダブルチェック必須 (3AI 非決定論性 / Bandai 名前検索の誤マッチ / Energy Marker Color 補完)
        "cwd": f"{WORKSPACE}/iMakTCG",
        "cmd": ["python", "psa_to_csv.py"],
        "urls_file": f"{WORKSPACE}/iMakTCG/certs.txt",
        "params": [],
        "desc": "スプシ駆動（I列=cert#, B列itemID空が処理対象）→CSV生成→check_csv自動連鎖→【入稿前ダブルチェック必須】",
        "trend_key": "tcg",
        "keyword_pdf": KEYWORD_PDF["toys"],
        "flow": """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📥  INPUT  ｜  入力ソース
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ▸ 共通スプシ  Hight: 19kj8…  /  Low: 1jF9…  ( gid=851100680 )
      • I列 = PSA cert#
      • B列 = itemID  ( 空が処理対象 )
      • 仕入値 = N列優先  +  F列 "¥XXX,XXX" パース fallback
  ✗ certs.txt 駆動は廃止  ( 2026-04-24 追補3 )

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⚙️   PIPELINE  ｜  パイソン処理
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ① 🔍 PSA cert# → psacard.com Selenium → Brand / Subject / CardNumber

  ② 📚 公式DB lookup  ( フランチャイズ別 )
      ├─ One Piece                bandai_jp.py        ( Selenium + 名前検索フォールバック )
      ├─ Dragon Ball Fusion World bandai_tcg_plus.py  ( game="dragonball" )
      │     └─ Energy Marker E01-XX  →  ENERGY_MARKER_DB  ( ハードコード )
      ├─ Gundam                   bandai_tcg_plus.py  ( game="gundam" )
      └─ Pokemon                  pokemon_card_jp.py

  ③ 🤖 Claude API + キーワードPDF参照でタイトル生成
      └─ card# 短縮 / Subject 改変を検出  →  ルールベース自動切替

  ④ 🛡️  Item Specifics 全6フィールド  ( rarity / card_type / cost / power / attribute / finish )
      └─ 公式DB由来のみ採用、Claude fallback 物理除去  ( 2026-04-24 追補6 )

  ⑤ 🔧 AUTO-FIX Canonical Map  ( eBay フィルタ正規値へ無言整形 )
      ├─ Card Type    "Character Card" → "Character" / "Leader Card" → "Leader"
      ├─ Rarity OP    SEC→Secret Rare, SR→Super Rare, R→Rare, C→Common, L→Leader …
      ├─ Rarity DB    SR→Super Rare, UC→Uncommon, PR★→Promo …  ( 2026-04-26 )
      ├─ Set OP       "OP-01"→"Romance Dawn" 等 23セット網羅
      ├─ Set DB       "BOOSTER PACK -AWAKENED PULSE- [FB01]"→"Awakened Pulse" …  ( 2026-04-26 )
      ├─ Leader Cost  強制空欄化  ( Leader はコスト持たない仕様 )
      └─ Features     "Alternate Art" → "Alternative Art"

  ⑥ 🚫 Finish欄は常に空欄  ( 確証なき推測禁止、SNAD クレーム回避 )

  ⑦ 🏷️  SKU = メルカリ商品ID

  ⑧ 🧹 同一カード番号の重複は最安1件のみ採用

  ⑨ 🤝 listing_validator.py  +  3AI 合議  ( Claude / Gemini / Groq )
      ├─ プロモ二重国籍ケース  ( PSA封入セット ≠ Bandai 元セット ) の許容パターン搭載
      └─ 不一致時はラウンド最大4回まで議論

  ⑩ 💰 価格決定  ( 内蔵 TIER_PARAMS + DDP反復計算 )
      ├─ 設計思想は共通エンジン  ( コストプラス + ティア利益率 + 乖離判定 )
      ├─ GO 時のみ「中央値 × 0.95」で市場連動価格に切替  ( 2026-04-23 Phase 3 ⑤ )
      └─ 物理ゲート: ALERT 行は CSV 物理除外  +  csv_hold_queue.jsonl 隔離

  ⑪ 🧬 SSOT  ｜  tier_params は  profit_params.get_tier_params  ( yaml SSOT ) 経由  ( 2026-04-25 Step 7 )

  ⑫ 📝 記録  ｜  decision_log に config_version + 使用値を刻印  ( Step 8 )

  ⑬ 📤 スプシ追記  ｜  cert / title / price / cost / GATE 等を結果スプシに自動記録

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🔄  AUTO CHAIN  ｜  check_csv 自動連鎖
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  psa_to_csv 完了直後に check_csv.py が自動実行され以下を再検証:
      ▸ 市場中央値・乖離率・利益率の再計算  ( psa_to_csv と SSOT 共有 )
      ▸ Item Specs  ( TOPセラーとの差分 ) ハイライト
      ▸ GATE 判定の最終確認  +  AI 総合レビュー  ( Claude )

╔═══════════════════════════════════════════════════════════════════╗
║  🛑  ダブルチェック  ｜  入稿前  ［人手必須］                        ║
╚═══════════════════════════════════════════════════════════════════╝
  3AI 判定の非決定論性  ／  Bandai 名前検索の誤マッチ  ／  薄商いカードの価格暴走
  に対する最後の防衛線。CSV を eBay 入稿する前に必ず以下を目視確認:

  ☐  💴  価格妥当性  ｜  TOPセラー価格を超えていないか
                       出品N件未満の薄商いで強気価格になっていないか
  ☐  🆔  PSA Brand prefix と Card Number 一致
            └─ Luffy ST16 / PRB02 事故  ( cert #143570665 系 ) の物理確認
  ☐  🎯  Bandai 名前検索フォールバックで  「同名キャラの別カード」  誤マッチ無し
  ☐  🌈  Energy Marker  ( E01-XX )  は Color を物理カード確認後に手動補完
  ☐  ✨  Finish は確証あるカードのみ手動補完  ( 空欄が原則、Holo 推測禁止 )
  ☐  🔁  Title 内の重複語  ( 'frieza' 等 ) を check_csv 警告でチェック

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📤  OUTPUT  ｜  出力
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📁  CSV         iMakHQ/csv_output/tcg_upload_<timestamp>.csv
  📁  サイドカー   *_cost.json  ( 仕入値、check_csv が参照 )
  📄  テンプレ     PSA10.txt    ( Description HTML、全カード共通 )

  🔢  ConditionID    2750  ( Graded - Gem Mint )
  🔄  ReturnPolicy   No return
""",
    },
    {
        "label": "リール",
        "verified": True,  # 2026-04-24 実戦検証合格（市場連動ゲート稼働、4件中1件GO出力/3件ALERT隔離）
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_to_ebay_csv.py", "--sheet", "reel"],
        "params": [],
        "desc": "統合Low(R=リール,ItemID空) → Claude → eBay CSV (Bait/Spinning自動判定)",
        "trend_key": "reel",
        "keyword_pdf": KEYWORD_PDF["sports"],
        "flow": """【リール出品】

  ▶実行: 統合Low (R=リール, B=ItemID空, D=売り切れ空) を読込
    → Mercariスクレイプ + Claude API
    → reel_type 判定 (bait/spinning)
       - bait → eBayカテゴリ 32885 (Bait Casting Reels)
       - spinning → eBayカテゴリ 36147 (Spinning Reels)
    → pricing_engine(リール: FVF 13.3%, 送料¥3,000)
    → eBay CSV 出力

【設定】
  - StoreCategoryID 41828943010 (Fishing Gear)
  - ConditionID 2750 (Used)
  - Description テンプレ: USED.txt + Mercari商品説明差込
  - 出品完了後、統合Low B列に ItemID 入力で「処理済」化
""",
    },
    {
        "label": "一番くじ",
        "cwd": f"{WORKSPACE}/iMak_ichibankuji",
        "cmd": ["python", "ichibankuji_to_csv.py"],
        "verified": True,
        "params": [],
        "desc": "1kuji→中間CSV→eBay CSV+統合Hight転記",
        "trend_key": "kuji",
        "keyword_pdf": KEYWORD_PDF["collect"],
        "urls_file": f"{WORKSPACE}/iMak_ichibankuji/kuji_urls.txt",
        "custom_buttons": "ichibankuji",
        "flow": """▶実行ボタン押すとウィザードが起動。Step 1〜4 を順に案内。

  Step 1/4: 1kuji.com URL を貼り付け（既存kuji_urls.txt自動読込）
  Step 2/4: Phase1 実行（1kuji スクレイプ→中間CSV生成）
  Step 3/4: 中間CSVを Excel で編集（mercari_url / cost_jpy 手入力）→ 編集完了ボタン
  Step 4/4: Phase2(統合Hight転記) + Phase3(Claude→eBay CSV) を自動連続実行

【ItemID ベースの再処理】
  統合Hight B列に ItemID 入 = 処理済、空 = 次回再処理対象。
  出品完了後、B列に ItemID を手入力して「処理済」化してください。

【統合Hight 列マッピング】
  A=URL  B=itemID  C=タイトル  D=売り切れ  E=状態  F=価格
  G=写真URL  H=商品説明  R=カテゴリ
  U=kuji_url  V=series_name  W=prize_code  X=prize_title
  Y=release_year  Z=kuji_price_jpy

【出力CSV】iMakHQ/csv_output/ichibankuji_upload_*.csv

【設定】
  - PROFIT_CATEGORY = "一番くじ" (FVF 13.25%, 送料 ¥2,500)
  - eBayカテゴリ 261055 / ConditionID 1000 (New) / Location "Osaka"
""",
    },
    {
        "label": "🏔 モンベル公式アウトレット 巡回",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "montbell_outlet_scraper.py"],
        "params": [
            {"name": "--categories", "label": "カテゴリID(カンマ区切り)", "default": ""},
            {"name": "--limit", "label": "各cat件数上限", "default": ""},
        ],
        "desc": "モンベル公式アウトレット巡回→管理シート更新（在庫監視）",
        "trend_key": "montbell",
    },
    {
        "label": "🔚 モンベル 取下げCSV生成",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "montbell_end_items.py"],
        "params": [],
        "desc": "管理シートから売切れ/取下げ推奨の行を抽出→EndItem CSV生成",
    },
    {
        "label": "Mercari スカウト",
        "cwd": f"{WORKSPACE}/iMakMercari",
        "cmd": ["python", "mercari_scout.py"],
        "params": [],
        "desc": "保存検索URLを巡回 → GO/HOLD/NOGO判定",
        "urls_file": f"{WORKSPACE}/iMakMercari/search_urls.txt",
        "trend_key": "scout",
        "flow": """【入力】search_urls.txt
  ファイル: c:/dev/iMak/iMakMercari/search_urls.txt
  → 「📄 URLファイル開く」ボタンで編集可

【現在スカウト対象カテゴリ】
  ✅ PSA10 TCG (category_id=10861)
      - 価格帯 ¥1,000〜¥50,000
      - 送料込み・販売中・新着順
      - PSA関連フィルタ（grade=10 etc.）
  ❌ その他（UT, Montbell, Porter, G-SHOCK, 一番くじ等）は対象外
      → 追加したい場合、search_urls.txtに行追加

【パイソン処理】
  1. 【個別】メルカリ検索結果を巡回（Selenium）
  2. 【個別】各商品の利益試算: 仕入¥ + 送料 vs eBay中央値
  3. 【個別→共通同等】価格決定: 内蔵 TIER_PARAMS + GO/HOLD/NOGO判定
       - 設計思想は共通エンジン(pricing_engine)と一致
       - スカウトはHOLD(保留)の3段階分類が必要 → 共通エンジン2段階(GO/ALERT)と差異
  4. 【個別】GO候補のみ出力

【出力】GOリスト（仕入候補、コンソール表示）
""",
    },
    {
        "label": "利益計算シート クリア",
        "cwd": f"{WORKSPACE}/iMakHQ/sheets",
        "cmd": ["python", "clear_calc_inputs.py"],
        "params": [],
        "desc": "利益計算v2の入力欄をクリアして再オープン",
        "flow": """【対象】iMakHQ/sheets/【NEW】利益計算シート_v2.xlsx
【処理】
  - US計算/UK計算/AU計算 シートの F1, C4, E4, F4, H4 をクリア
  - ファイル開いてたら閉じるまで待機(最大2分)
  - クリア後、自動で再オープン
""",
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
            if added.startswith(month_yyyymm):
                result[cat]['monthly'] += 1

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


def _decorate_flow(text):
    """既存の flow テキストを自動装飾 (TCG パターンに統一).

    既装飾 (━ 罫線あり) のテキストはそのまま返す (二重装飾防止)。
    未装飾なら以下を施す:
      - 行頭インデントなしの【見出し】 → 罫線囲み + 📌 アイコン
        (インデント付きの【個別】【共通】等のインラインラベルは触らない)
      - 数字リスト 1. 2. ... → 丸囲み数字 ①②③ (最大⑳)
    """
    import re as _re
    if "━━━━" in text or "╔═" in text:
        return text  # 既装飾
    bar = "━" * 64
    def _repl_heading(m):
        title = m.group(1).strip()
        rest = m.group(2).strip()
        if rest:
            return f"\n{bar}\n  📌  {title}  ｜  {rest}\n{bar}"
        return f"\n{bar}\n  📌  {title}\n{bar}"
    # ^ 直後 (インデントなし) に【】がある行のみ見出し扱い
    text = _re.sub(r"^【([^】]+)】(.*)$", _repl_heading, text, flags=_re.MULTILINE)
    # 数字リスト → 丸囲み数字
    circles = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    def _repl_num(m):
        n = int(m.group(2))
        if 1 <= n <= 20:
            return f"{m.group(1)}{circles[n-1]}  "
        return m.group(0)
    text = _re.sub(r"^(\s*)(\d+)\.\s", _repl_num, text, flags=_re.MULTILINE)
    return text


class FlowDialog(tk.Toplevel):
    def __init__(self, parent, label, flow_text, trend_key="", keyword_pdf="", urls_file=""):
        super().__init__(parent)
        self.title(f"フロー: {label}")
        self.geometry("880x720")

        # タブ構成
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        # ===== タブ1: 処理フロー =====
        tab_flow = ttk.Frame(nb)
        nb.add(tab_flow, text="📋 処理フロー")

        if urls_file:
            urlf = ttk.Frame(tab_flow)
            urlf.pack(fill="x", padx=6, pady=6)
            ttk.Label(urlf, text=f"📄 URLファイル: {os.path.basename(urls_file)}", foreground="#0066cc").pack(side="left")
            ttk.Button(urlf, text="開く",
                       command=lambda: self._open_file(urls_file)).pack(side="right")

        txt = scrolledtext.ScrolledText(tab_flow, wrap="word", font=("Yu Gothic UI", 10))
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        txt.insert("1.0", _decorate_flow(flow_text))
        txt.config(state="disabled")

        # ===== タブ2: トレンド/相場リサーチ =====
        tab_trend = ttk.Frame(nb)
        nb.add(tab_trend, text="🔥 トレンド/相場調査")

        # スクロール可能フレーム
        canvas = tk.Canvas(tab_trend)
        sb = ttk.Scrollbar(tab_trend, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas)
        content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # eBayキーワードPDF
        if keyword_pdf:
            pdf_frame = ttk.LabelFrame(content, text="📊 eBayキーワードPDF（四半期更新）", padding=6)
            pdf_frame.pack(fill="x", padx=6, pady=(6, 2))
            inner = ttk.Frame(pdf_frame)
            inner.pack(fill="x")
            ttk.Label(inner, text=os.path.basename(keyword_pdf), foreground="#0066cc").pack(side="left")
            ttk.Button(inner, text="開く",
                       command=lambda: self._open_file(keyword_pdf)).pack(side="right")

        # カテゴリ別トレンドリンク
        if trend_key and trend_key in TREND_LINKS:
            cat_frame = ttk.LabelFrame(content, text=f"🎯 {label} 専用リサーチ（メルカリ人気順/SOLD/専門サイト）", padding=6)
            cat_frame.pack(fill="x", padx=6, pady=2)
            for name, url in TREND_LINKS[trend_key]:
                row = ttk.Frame(cat_frame)
                row.pack(fill="x", pady=1)
                ttk.Label(row, text=f"• {name}", width=30).pack(side="left")
                ttk.Button(row, text="🔗 開く", width=10,
                           command=lambda u=url: self._open_url(u)).pack(side="right")

        # 共通リサーチリンク
        common_frame = ttk.LabelFrame(content, text="🌐 共通リサーチ（全カテゴリで使える）", padding=6)
        common_frame.pack(fill="x", padx=6, pady=2)
        for name, url in COMMON_TREND_LINKS:
            row = ttk.Frame(common_frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=f"• {name}", width=30).pack(side="left")
            ttk.Button(row, text="🔗 開く", width=10,
                       command=lambda u=url: self._open_url(u)).pack(side="right")

        ttk.Button(self, text="閉じる", command=self.destroy).pack(pady=6)

    def _open_file(self, path):
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("エラー", f"ファイル開けませんでした: {e}")

    def _open_url(self, url):
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("エラー", f"URL開けませんでした: {e}")


class URLInputDialog(tk.Toplevel):
    """PSA TCG の URL 入力 GUI。
    paste box 形式で複数URL一括登録、説明書き付き。
    （一番くじは『一番くじ』枠内の専用ボタンに移設済み）"""

    PSA_FILE = r"c:\dev\iMak\iMakTCG\certs.txt"
    PSA_SCRIPT = r"c:\dev\iMak\iMakTCG\psa_to_csv.py"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("📥 URL入力 - PSA TCG")
        self.geometry("780x680")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # ===== PSA TCGタブ =====
        psa_tab = ttk.Frame(nb)
        nb.add(psa_tab, text="🃏 PSA TCG")
        self._build_psa_tab(psa_tab)

        ttk.Button(self, text="閉じる", command=self.destroy).pack(pady=4)

    def _build_psa_tab(self, parent):
        info = (
            "【PSA TCG URL入力】\n"
            "・1行に1件、以下の形式で入力（カンマ区切り）:\n"
            "    PSA証明番号,仕入価格(円),メルカリURL,メルカリタイトル\n"
            "・例: 148226751,23200,https://jp.mercari.com/item/m12345,Luffy 2nd Anniv\n"
            "・最小入力: PSA証明番号 のみ（仕入値・URL・タイトルは省略可）\n"
            "・「ファイルに追記」で certs.txt に保存\n"
            "・「処理開始」で psa_to_csv.py を起動 → eBay CSV生成\n"
            "・既にスプシに登録済みのURLを持つ証明番号は自動スキップ\n"
            "・3AI議論方式（Claude/Gemini/Groq）でタイトル整合性検証"
        )
        info_frame = ttk.LabelFrame(parent, text="📖 説明書き", padding=6)
        info_frame.pack(fill="x", padx=4, pady=4)
        ttk.Label(info_frame, text=info, justify="left", foreground="#0066cc",
                  font=("Yu Gothic UI", 9)).pack(anchor="w")

        input_frame = ttk.LabelFrame(parent,
                                      text="📝 cert,cost,url,title（カンマ区切り、1行1件）",
                                      padding=6)
        input_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.psa_text = scrolledtext.ScrolledText(input_frame, wrap="word", height=12,
                                                   font=("Consolas", 10))
        self.psa_text.pack(fill="both", expand=True)

        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", padx=4, pady=6)
        ttk.Button(btn_frame, text=f"📂 既存ファイルを開く ({os.path.basename(self.PSA_FILE)})",
                   command=lambda: self._open_file(self.PSA_FILE)).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="💾 ファイルに追記",
                   command=self._psa_save).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="▶ 処理開始（CSV生成）",
                   command=self._psa_run).pack(side="right", padx=2)

    def _psa_save(self):
        text = self.psa_text.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("入力なし", "データを貼り付けてください")
            return
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        # 最低限cert番号が含まれてる行だけ
        valid = [ln for ln in lines if ln.split(",")[0].strip().isdigit()]
        if not valid:
            messagebox.showwarning("無効", "1列目がPSA証明番号(数字)の行が見つかりません")
            return
        try:
            with open(self.PSA_FILE, "a", encoding="utf-8") as f:
                f.write("\n" + "\n".join(valid) + "\n")
            messagebox.showinfo("追記完了", f"{len(valid)}件 を {self.PSA_FILE} に追記しました")
            self.psa_text.delete("1.0", "end")
        except Exception as e:
            messagebox.showerror("エラー", f"ファイル書込失敗: {e}")

    def _psa_run(self):
        if not os.path.exists(self.PSA_SCRIPT):
            messagebox.showerror("エラー", f"スクリプトなし: {self.PSA_SCRIPT}")
            return
        try:
            subprocess.Popen(["python", self.PSA_SCRIPT],
                              cwd=os.path.dirname(self.PSA_SCRIPT),
                              creationflags=subprocess.CREATE_NEW_CONSOLE)
            messagebox.showinfo("起動", "psa_to_csv.py を起動しました（別コンソール）")
        except Exception as e:
            messagebox.showerror("エラー", f"起動失敗: {e}")

    def _open_file(self, path):
        try:
            if not os.path.exists(path):
                # ファイルなければ空ファイル作成
                open(path, "a", encoding="utf-8").close()
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("エラー", f"ファイル開けませんでした: {e}")


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
        pending_count, _ = _read_pending_tasks()
        task_label = f"📝 宿題 ({pending_count}件)" if pending_count else "📝 宿題"
        ttk.Button(nav, text="📜 リスティングスクリプト一覧", command=self.open_listing).pack(side="right", padx=2)
        ttk.Button(nav, text="📥 URL入力", command=self.open_url_input).pack(side="right", padx=2)
        self.tasks_btn = ttk.Button(nav, text=task_label, command=self.open_tasks)
        self.tasks_btn.pack(side="right", padx=2)
        ttk.Button(nav, text="🔄 更新", command=self.refresh_dashboard).pack(side="right", padx=2)

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

        # === 総合進捗テーブル ===
        dash_frame = ttk.LabelFrame(root, text="📊 総合進捗（カテゴリ別アクティブ出品数 vs 目標）", padding=6)
        dash_frame.pack(fill="x", padx=10, pady=(6, 4))

        cols = ("カテゴリ", "目標", "現在", "不足", "進捗", "優先度")
        self.tree = ttk.Treeview(dash_frame, columns=cols, show="headings", height=8)
        widths = (200, 60, 60, 60, 360, 80)
        for c, w in zip(cols, widths):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w" if c in ("カテゴリ", "進捗") else "center")
        self.tree.pack(fill="x")
        # 進捗率による色分け（背景＋フォアグラウンド）
        self.tree.tag_configure("done",  background="#d4ffd4", foreground="#006600")  # 100% 緑
        self.tree.tag_configure("blue",  background="#d4e6ff", foreground="#003366")  # >66% 青
        self.tree.tag_configure("yel",   background="#fff4c4", foreground="#806600")  # 33-66% 黄
        self.tree.tag_configure("red",   background="#ffd4d4", foreground="#800000")  # <33% 赤
        self.tree.tag_configure("total", background="#e0e0ff", foreground="#000066", font=("", 10, "bold"))

        # === 月次進捗テーブル ===
        month_frame = ttk.LabelFrame(root, text="📅 今月の出品進捗（月次目標に対して）", padding=6)
        month_frame.pack(fill="x", padx=10, pady=4)

        mcols = ("カテゴリ", "目標", "現在", "不足", "進捗")
        self.month_tree = ttk.Treeview(month_frame, columns=mcols, show="headings", height=8)
        mwidths = (200, 80, 80, 60, 400)
        for c, w in zip(mcols, mwidths):
            self.month_tree.heading(c, text=c)
            self.month_tree.column(c, width=w, anchor="w" if c in ("カテゴリ", "進捗") else "center")
        self.month_tree.pack(fill="x")
        self.month_tree.tag_configure("done",  background="#d4ffd4", foreground="#006600")
        self.month_tree.tag_configure("blue",  background="#d4e6ff", foreground="#003366")
        self.month_tree.tag_configure("yel",   background="#fff4c4", foreground="#806600")
        self.month_tree.tag_configure("red",   background="#ffd4d4", foreground="#800000")
        self.month_tree.tag_configure("total", background="#e0e0ff", foreground="#000066", font=("", 10, "bold"))

        # 推奨メッセージ (スクロール対応 ScrolledText)
        reco_frame = ttk.LabelFrame(root, text="💡 推奨アクション", padding=6)
        reco_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.reco_text = scrolledtext.ScrolledText(
            reco_frame, height=6, wrap="word",
            font=("Yu Gothic UI", 10, "bold"),
            fg="#cc5500", relief="flat", borderwidth=0,
        )
        self.reco_text.pack(fill="both", expand=True)
        self.reco_text.config(state="disabled")

        self.listing_window = None  # リスティング画面（別ウィンドウ、遅延生成）
        self.root.after(300, self.refresh_dashboard)

    def _on_close(self):
        _save_geometry("home", self.root.geometry())
        self.root.destroy()

    def _set_reco(self, text, fg="#cc5500"):
        """推奨アクション欄に文字列をセット (Text widget なので state 切替必要)。"""
        self.reco_text.config(state="normal", fg=fg)
        self.reco_text.delete("1.0", "end")
        self.reco_text.insert("1.0", text)
        self.reco_text.config(state="disabled")

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

    def open_url_input(self):
        URLInputDialog(self.root)

    def open_listing(self):
        """リスティングスクリプト一覧を別ウィンドウで開く（既にあれば前面表示）。"""
        if self.listing_window is not None and tk.Toplevel.winfo_exists(self.listing_window):
            self.listing_window.lift()
            self.listing_window.focus_force()
            return
        self.listing_window = tk.Toplevel(self.root)
        self.listing_window.title("📜 リスティングスクリプト一覧")
        self.listing_window.geometry(_load_geometry("listing", "1100x780"))
        self.listing_window.protocol("WM_DELETE_WINDOW", self._on_close_listing)
        ListingPanel(self.listing_window)

    def _on_close_listing(self):
        _save_geometry("listing", self.listing_window.geometry())
        self.listing_window.destroy()
        self.listing_window = None

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


class ListingPanel:
    """従来の ControlPanel 相当（スクリプト一覧）。HomePanel から呼び出される。"""
    def __init__(self, root):
        self.root = root

        top_frame = ttk.LabelFrame(root, text="スクリプト一覧", padding=8)
        top_frame.pack(fill="x", padx=8, pady=(8, 4))

        canvas = tk.Canvas(top_frame, height=320)
        scrollbar = ttk.Scrollbar(top_frame, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.param_entries = {}
        for i, script in enumerate(SCRIPTS):
            row = ttk.Frame(scroll_frame, padding=4, relief="ridge")
            row.pack(fill="x", pady=2)
            # ユーザーチェック合格スクリプトは青色表示
            # double_check=True は入稿前に人手ダブルチェック必須のカテゴリ (✓ を2つ表示)
            verified = script.get("verified", False)
            double_check = script.get("double_check", False)
            prefix = "✓✓ " if double_check else ("✓ " if verified else "")
            label_text = prefix + script["label"]
            label_color = "#0066cc" if verified else "black"
            tk.Label(row, text=label_text, width=32, font=("", 10, "bold"),
                     fg=label_color, anchor="w").pack(side="left")
            ttk.Label(row, text=script.get("desc", ""), foreground="gray", width=42).pack(side="left", padx=4)

            self.param_entries[i] = {}
            for p in script.get("params", []):
                ttk.Label(row, text=p["label"]).pack(side="left", padx=(8, 2))
                entry = ttk.Entry(row, width=6)
                entry.insert(0, p.get("default", ""))
                entry.pack(side="left")
                self.param_entries[i][p["name"]] = entry

            ttk.Button(row, text="ℹ️ フロー", width=10,
                       command=lambda idx=i: self.show_flow(idx)).pack(side="right", padx=2)
            ttk.Button(row, text="🛑", width=4, command=self.stop_script).pack(side="right", padx=2)
            ttk.Button(row, text="▶ 実行", width=8,
                       command=lambda idx=i: self.run_script(idx)).pack(side="right", padx=2)

            # 一番くじ: ▶実行 のみ（ウィザード式に集約済）

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

    def show_flow(self, idx):
        script = SCRIPTS[idx]
        FlowDialog(
            self.root,
            script["label"],
            script.get("flow", "(フロー情報未登録)"),
            trend_key=script.get("trend_key", ""),
            keyword_pdf=script.get("keyword_pdf", ""),
            urls_file=script.get("urls_file", ""),
        )

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
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("実行中", "他のスクリプトが実行中です。停止してから実行してください。")
            return
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
        try:
            # Windows: コンソール窓を出さない
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW
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
        self.queue.put(("__done__", self.proc.returncode))

    def _run_rarara_after(self):
        """ListingPanel: rarara helper 呼出 (互換ラッパ)."""
        _run_rarara_for_latest_csv(self.append_log)

    def poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "__done__":
                    self.append_log(f"\n--- 終了 (returncode={item[1]}) ---\n")
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
                    self._run_rarara_after()
                    self.status_var.set("待機中")
                    self.now_processing.set("")
                else:
                    self.append_log(item)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def stop_script(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.append_log("\n🛑 停止要求送信\n")
            self.status_var.set("停止処理中")
        else:
            self.append_log("実行中のスクリプトはありません\n")


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
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
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
        try:
            self.proc.wait(timeout=10)  # stdout閉じた後、プロセス終了を待つ（returncode確定）
        except subprocess.TimeoutExpired:
            pass
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
                    _run_rarara_for_latest_csv(self._append_log)
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

    def _cancel_proc(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._append_log("\n🛑 中止要求送信\n")


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
