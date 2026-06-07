# -*- coding: utf-8 -*-
"""US計算 N列 (DDP コスト) を 3 セル分離に書換
- R 列 (新規): N_A = V3 IFS lookup × FX_USD
- S 列 (新規): N_B = 価格 × (HTS率 - HTS_BASE) × FX_USD
- N 列 (既存): = R + S (新ロジック合計)

行 9 (V5 base) の G9 closed-form (1.35 markup) はそのまま維持。
N9 だけ新ロジックに書換 → V5 価格で売った時の新 DDP での利益が見える。

事前にバックアップタブを作る。
"""
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path
from datetime import datetime

CREDS = Path(r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
SHEET_ID = "1WNCTZcwAVjeGIElMyjrUSPhfVU3PnPHMH4tCpeC8kQs"

gc = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES))
sh = gc.open_by_key(SHEET_ID)
us = sh.worksheet("US計算")

# ===== Step 1: バックアップタブ作成 =====
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
bk_name = f"bk_US計算_{ts}"
us.duplicate(new_sheet_name=bk_name)
print(f"[backup] {bk_name} 作成")

# ===== Step 2: R/S 列にヘッダ追加 =====
us.update("R5", [["DDP_A (V3 IFS)"]], value_input_option="USER_ENTERED")
us.update("S5", [["DDP_B (HTS補正)"]], value_input_option="USER_ENTERED")
print("[header] R5, S5 ヘッダ追加")

# ===== Step 3: 行 6-12 で R/S/N の式を書換 =====
# 行 9 は V5 base (G9 closed-form), 他は ±15% ラダー
# R列: V3 IFS lookup (USD) × FX (JPY)
# S列: F × (HTS率 - HTS_BASE) × FX (JPY)
# N列: R + S (新ロジック合計)
#
# DDP_IFS は min_USD 順、VLOOKUP TRUE で F 以下の最大 min_USD 行を取得
# HTS_RATE は カテゴリ→HTS率、F3 (商品カテゴリ) で lookup
updates = []
for r in range(6, 13):  # 行 6-12
    updates.append({"range": f"R{r}", "values": [[f"=VLOOKUP(F{r}, DDP_IFS, 2, TRUE) * FX_USD"]]})
    updates.append({"range": f"S{r}", "values": [[f"=F{r} * (VLOOKUP($F$3, HTS_RATE, 2, FALSE) - HTS_BASE) * FX_USD"]]})
    updates.append({"range": f"N{r}", "values": [[f"=R{r}+S{r}"]]})

us.batch_update(updates, value_input_option="USER_ENTERED")
print(f"[rewrite] 行 6-12 の N/R/S 式書換 (計 {len(updates)} セル)")

# ===== Step 4: 行 9 (V5 base) の G9 closed-form について警告コメント追加 =====
us.update("T9", [["⚠ G9 は V5 (1.35 markup) closed-form のまま。V6 ロジックでの逆算は別途"]], value_input_option="USER_ENTERED")
print("[note] T9 に警告コメント追加")

print()
print("=" * 60)
print("US計算 N列 3 セル分離 完了")
print("=" * 60)
print(f"  - R 列: V3 IFS DDP (JPY)")
print(f"  - S 列: HTS 補正 (JPY)")
print(f"  - N 列: R + S (新ロジック合計)")
print(f"  - 行 9 G9 (closed-form) はそのまま維持")
print(f"  - バックアップ: タブ「{bk_name}」")
print()
print(f"URL: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")
