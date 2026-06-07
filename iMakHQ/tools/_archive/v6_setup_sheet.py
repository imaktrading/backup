# -*- coding: utf-8 -*-
"""V6 スプシ 構造改善 一括セットアップ
- mst_DDP タブ新規追加 (V3 ブラッシュ IFS tier + HTS マスタ + HTS_BASE_RATE)
- 名前付き範囲 13 個 を一括定義
- 既存タブ (設定 / US計算 等) は触らない
"""
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path

CREDS = Path(r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
SHEET_ID = "1WNCTZcwAVjeGIElMyjrUSPhfVU3PnPHMH4tCpeC8kQs"

gc = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES))
sh = gc.open_by_key(SHEET_ID)

# ===== Step 1: mst_DDP タブ作成 (既存ならリセット) =====
try:
    old = sh.worksheet("mst_DDP")
    sh.del_worksheet(old)
    print("[reset] 既存 mst_DDP 削除")
except gspread.WorksheetNotFound:
    pass

mst = sh.add_worksheet(title="mst_DDP", rows=30, cols=10)
print("[create] mst_DDP タブ新規作成")

# ヘッダ
header = [
    ["# DDP 計算マスタ", "", "", "", "", "", "", ""],
    ["更新日: 2026-05-20", "", "", "", "", "", "", ""],
    ["出典: V3 実績IFS (Gemini ブラッシュ案①) + USITC HTS Schedule 2025", "", "", "", "", "", "", ""],
    ["注意: B セル補正は HTS_BASE_RATE (V3 暗黙想定率) からの差分で計算", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "", ""],
    ["min_USD", "ddp_USD", "", "カテゴリ", "HTS率", "", "HTS_BASE_RATE", ""],
]

# IFS tier 値 (A7-B16) - VLOOKUP互換のため min_USD ベース
# F (商品価格 USD) >= min_USD の最大行の ddp_USD を返す
ifs_tiers = [
    [0,     15],
    [40,    20],
    [60,    35],
    [100,   50],
    [200,   70],
    [300,   90],
    [400,  110],
    [500,  140],
    [600,  180],
    [800,  250],
]

# HTS マスタ (D7-E24)
hts_rates = [
    ["TCG(PSA10)",          0],
    ["G-SHOCK",             0.035],
    ["Tシャツ(UT)",         0.27],
    ["Montbell(軽)",        0.27],
    ["Montbell(重)",        0.27],
    ["一番くじ",            0],
    ["フィギュア",          0],
    ["ユニクロ(非UT)",      0.27],
    ["サンリオ文具",        0],
    ["ヴィンテージ玩具",    0],
    ["トミカ",              0],
    ["POPMart",             0],
    ["ガシャポン",          0],
    ["ダイソー",            0],
    ["バッグ(アネロ)",      0.07],
    ["サンリオぬいぐるみ",  0],
    ["Porter",              0.07],
    ["リール",              0],
]

# HTS_BASE_RATE 関連 (G1-G4)
hts_base = [
    ["HTS_BASE_RATE"],
    [0.20],
    ["= V3 IFS が暗黙に想定する HTS 率"],
    ["B セル補正 = HTS率 - HTS_BASE_RATE"],
]

# 一括書き込み
updates = [
    {"range": "A1:H6",   "values": header},
    {"range": "A7:B16",  "values": ifs_tiers},
    {"range": "D7:E24",  "values": hts_rates},
    {"range": "G1:G4",   "values": hts_base},
]
mst.batch_update(updates, value_input_option="USER_ENTERED")
print(f"[write] mst_DDP に IFS tier ({len(ifs_tiers)}行) + HTS マスタ ({len(hts_rates)}カテゴリ) + HTS_BASE_RATE 投入")

mst.format("A1", {"textFormat": {"bold": True}})
mst.format("A6:B6", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.91, "green": 0.94, "blue": 0.99}})
mst.format("D6:E6", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.91, "green": 0.94, "blue": 0.99}})
mst.format("G1",    {"textFormat": {"bold": True}, "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.80}})

# ===== Step 2: 名前付き範囲 一括定義 =====
sheet_id_setup = sh.worksheet("設定").id
sheet_id_mst   = mst.id

ranges = [
    ("FX_USD",          sheet_id_setup, "B2"),
    ("FX_EUR",          sheet_id_setup, "F2"),
    ("FX_GBP",          sheet_id_setup, "H2"),
    ("FX_AUD",          sheet_id_setup, "J2"),
    ("PROMO_RATE",      sheet_id_setup, "B3"),
    ("PAYO_RATE",       sheet_id_setup, "B4"),
    ("TARGET_PROFIT",   sheet_id_setup, "B5"),
    ("CATEGORY_TBL",    sheet_id_setup, "A11:D28"),
    ("COUNTRY_TAX_TBL", sheet_id_setup, "A36:E43"),
    ("GSHOCK_FVF_TBL",  sheet_id_setup, "A48:B52"),
    ("DDP_IFS",         sheet_id_mst,   "A7:B16"),
    ("HTS_RATE",        sheet_id_mst,   "D7:E24"),
    ("HTS_BASE",        sheet_id_mst,   "G2"),
]

existing_meta = sh.fetch_sheet_metadata().get("namedRanges", [])
del_requests = []
for nr in existing_meta:
    if nr["name"] in [r[0] for r in ranges]:
        del_requests.append({"deleteNamedRange": {"namedRangeId": nr["namedRangeId"]}})
if del_requests:
    sh.batch_update({"requests": del_requests})
    print(f"[reset] 既存 named range {len(del_requests)} 件 削除")

# 全 named ranges を削除 (DDP_IFS_TBL 等が孤立して残ってる可能性)
import time
time.sleep(1)
existing_meta = sh.fetch_sheet_metadata().get("namedRanges", [])
del_requests = []
for nr in existing_meta:
    if nr["name"] in [r[0] for r in ranges]:
        del_requests.append({"deleteNamedRange": {"namedRangeId": nr["namedRangeId"]}})
if del_requests:
    sh.batch_update({"requests": del_requests})
    print(f"[reset 2nd pass] 残存 named range {len(del_requests)} 件 削除")

def a1_to_grid(ref, sheet_id):
    import re
    m = re.match(r"^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$", ref)
    if not m:
        raise ValueError(f"Invalid A1: {ref}")
    def col(letters):
        n = 0
        for c in letters:
            n = n * 26 + (ord(c) - ord("A") + 1)
        return n - 1
    c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    grid = {
        "sheetId": sheet_id,
        "startRowIndex": r1 - 1,
        "endRowIndex": (int(r2) if r2 else r1),
        "startColumnIndex": col(c1),
        "endColumnIndex": (col(c2) if c2 else col(c1)) + 1,
    }
    return grid

add_requests = [
    {"addNamedRange": {"namedRange": {"name": name, "range": a1_to_grid(ref, sid)}}}
    for name, sid, ref in ranges
]
sh.batch_update({"requests": add_requests})
print(f"[create] 名前付き範囲 {len(add_requests)} 件 定義")

print()
print("V6 setup 完了")
print(f"URL: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")
