# -*- coding: utf-8 -*-
"""既存 VLOOKUP / 直接セル参照を 名前付き範囲 経由に一括書換
- '設定'!$A$11:$C$44 → CATEGORY_TBL
- '設定'!$A$36:$E$44 → COUNTRY_TAX_TBL
- '設定'!$A$48:$B$52 → GSHOCK_FVF_TBL
- '設定'!$B$2 → FX_USD ('設定'!$F$2 → FX_EUR 等)
- '設定'!$B$3 → PROMO_RATE
- '設定'!$B$4 → PAYO_RATE
- '設定'!$B$5 → TARGET_PROFIT
"""
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path
from datetime import datetime
import re

CREDS = Path(r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
SHEET_ID = "1WNCTZcwAVjeGIElMyjrUSPhfVU3PnPHMH4tCpeC8kQs"

gc = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES))
sh = gc.open_by_key(SHEET_ID)

# 置換ルール (元 → 名前付き範囲)
REPLACEMENTS = [
    # カテゴリ表
    (r"'設定'!\$A\$11:\$D\$44",  "CATEGORY_TBL"),
    (r"'設定'!\$A\$11:\$D\$28",  "CATEGORY_TBL"),
    (r"'設定'!\$A\$11:\$C\$44",  "CATEGORY_TBL"),
    (r"'設定'!\$A\$11:\$C\$28",  "CATEGORY_TBL"),
    (r"'設定'!\$A\$11:\$B\$44",  "CATEGORY_TBL"),
    (r"'設定'!\$A\$11:\$B\$28",  "CATEGORY_TBL"),
    # 国別税率
    (r"'設定'!\$A\$36:\$E\$44",  "COUNTRY_TAX_TBL"),
    (r"'設定'!\$A\$36:\$E\$43",  "COUNTRY_TAX_TBL"),
    # G-SHOCK FVF
    (r"'設定'!\$A\$48:\$B\$52",  "GSHOCK_FVF_TBL"),
    # 単一セル
    (r"'設定'!\$B\$2",           "FX_USD"),
    (r"'設定'!\$F\$2",           "FX_EUR"),
    (r"'設定'!\$H\$2",           "FX_GBP"),
    (r"'設定'!\$J\$2",           "FX_AUD"),
    (r"'設定'!\$B\$3",           "PROMO_RATE"),
    (r"'設定'!\$B\$4",           "PAYO_RATE"),
    (r"'設定'!\$B\$5",           "TARGET_PROFIT"),
]

def replace_formula(f):
    """式中の '設定'!範囲 を 名前付き範囲に置換"""
    if not isinstance(f, str) or not f.startswith("="):
        return f, False
    new_f = f
    for pattern, name in REPLACEMENTS:
        new_f = re.sub(pattern, name, new_f)
    return new_f, new_f != f

# ===== Step 1: バックアップ =====
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
target_tabs = ["US計算", "UK計算", "DE計算", "AU計算", "仕入GATE"]
for tab in target_tabs:
    try:
        ws = sh.worksheet(tab)
        bk_name = f"bk_{tab}_namedrange_{ts}"
        ws.duplicate(new_sheet_name=bk_name)
        print(f"[backup] {bk_name}")
    except gspread.WorksheetNotFound:
        print(f"[skip] {tab} not found")

# ===== Step 2: 各タブの数式を取得・置換・書戻 =====
total_changes = 0
for tab in target_tabs:
    try:
        ws = sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        continue

    formulas = ws.get_values(value_render_option="FORMULA")
    updates = []
    tab_changes = 0
    for r, row in enumerate(formulas, 1):
        for c, val in enumerate(row, 1):
            new_val, changed = replace_formula(val)
            if changed:
                # A1 形式
                col_letter = ""
                col = c
                while col > 0:
                    col, rem = divmod(col - 1, 26)
                    col_letter = chr(65 + rem) + col_letter
                updates.append({
                    "range": f"{col_letter}{r}",
                    "values": [[new_val]]
                })
                tab_changes += 1

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        print(f"[rewrite] {tab}: {tab_changes} セル 置換")
        total_changes += tab_changes
    else:
        print(f"[skip] {tab}: 置換対象なし")

print()
print(f"完了: 計 {total_changes} セル を 名前付き範囲 参照に置換")
print(f"URL: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")
