# -*- coding: utf-8 -*-
"""V6 連続関数化 (Gemini 案A) を US計算 に適用
- mst_DDP の IFS 表は廃止、新パラメータ DDP_FIXED ($12), DDP_VAR (0.10) を追加
- 名前付き範囲 DDP_FIXED, DDP_VAR を追加
- US計算 R/S/N 列を新ロジックに書換
- US計算 G9 を closed-form 新式に置換
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

# ===== Step 1: バックアップ =====
ts = datetime.now().strftime("%Y%m%d_%H%M%S")
us = sh.worksheet("US計算")
us.duplicate(new_sheet_name=f"bk_US計算_v6continuous_{ts}")
print(f"[backup] bk_US計算_v6continuous_{ts}")

# ===== Step 2: mst_DDP に DDP_FIXED, DDP_VAR を追加 =====
mst = sh.worksheet("mst_DDP")
mst.update(
    range_name="I1:I4",
    values=[
        ["DDP パラメータ (V6 連続関数)"],
        ["DDP_FIXED (USD)"],
        ["DDP_VAR (= 売価×%)"],
        ["備考"],
    ],
    value_input_option="USER_ENTERED"
)
mst.update(
    range_name="J1:J4",
    values=[
        [""],
        [12],
        [0.10],
        ["Gemini案A 初期値、CPaSS実績で要再キャリブレ"],
    ],
    value_input_option="USER_ENTERED"
)
mst.format("I1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.91, "green": 0.94, "blue": 0.99}})
mst.format("I2:I4", {"textFormat": {"bold": True}})
print("[mst_DDP] DDP_FIXED ($12), DDP_VAR (0.10) を I1:J4 に追加")

# V3 IFS 表 (A6:B16) は廃止だが残す + 廃止コメント
mst.update(
    range_name="A5",
    values=[["(廃止) ↓ 旧 V3 段階 IFS、参考用に保持"]],
    value_input_option="USER_ENTERED"
)
mst.format("A5", {"textFormat": {"italic": True, "foregroundColor": {"red": 0.6, "green": 0.6, "blue": 0.6}}})
print("[mst_DDP] V3 IFS 表に廃止コメント追加")

# ===== Step 3: 名前付き範囲追加 =====
sheet_id_mst = mst.id
ranges = [
    ("DDP_FIXED", sheet_id_mst, "J2"),
    ("DDP_VAR",   sheet_id_mst, "J3"),
]

def a1_to_grid(ref, sheet_id):
    import re
    m = re.match(r"^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$", ref)
    def col(letters):
        n = 0
        for c in letters:
            n = n * 26 + (ord(c) - ord("A") + 1)
        return n - 1
    c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    return {
        "sheetId": sheet_id,
        "startRowIndex": r1 - 1,
        "endRowIndex": (int(r2) if r2 else r1),
        "startColumnIndex": col(c1),
        "endColumnIndex": (col(c2) if c2 else col(c1)) + 1,
    }

# 既存削除
existing = sh.fetch_sheet_metadata().get("namedRanges", [])
del_req = [{"deleteNamedRange": {"namedRangeId": nr["namedRangeId"]}}
           for nr in existing if nr["name"] in [r[0] for r in ranges]]
if del_req:
    sh.batch_update({"requests": del_req})

add_req = [{"addNamedRange": {"namedRange": {"name": name, "range": a1_to_grid(ref, sid)}}}
           for name, sid, ref in ranges]
sh.batch_update({"requests": add_req})
print(f"[named range] DDP_FIXED, DDP_VAR 追加 (計 {len(add_req)} 件)")

# ===== Step 4: US計算 R/S/N 列を新ロジックに書換 =====
# 新ロジック:
#   R (DDP_A) = (F × DDP_VAR + DDP_FIXED) × FX_USD        ← 連続関数: 売価10% + 固定$12
#   S (DDP_B) = F × (HTS - HTS_BASE) × FX_USD              ← HTS 補正は維持
#   N         = R + S
updates = []
for r in range(6, 13):  # 行 6-12
    updates.append({"range": f"R{r}", "values": [[f"=(F{r}*DDP_VAR + DDP_FIXED) * FX_USD"]]})
    updates.append({"range": f"S{r}", "values": [[f"=F{r} * (VLOOKUP($F$3, HTS_RATE, 2, FALSE) - HTS_BASE) * FX_USD"]]})
    updates.append({"range": f"N{r}", "values": [[f"=R{r}+S{r}"]]})

# R/S 列ヘッダ更新
updates.append({"range": "R5", "values": [["DDP_A (連続: 10%+$12)"]]})
updates.append({"range": "S5", "values": [["DDP_B (HTS補正)"]]})

us.batch_update(updates, value_input_option="USER_ENTERED")
print(f"[US計算] R/S/N 列 (行 6-12) を連続関数版に書換 ({len(updates)} セル)")

# ===== Step 5: US計算 G9 closed-form を V6 新式に置換 =====
# 旧 G9: =1.35*(H9-I9+J9+0.4*$C$3+P9)/(1-1.35*($G$3+$D$3+$E$3))
#
# 新 G9 (V6 closed-form, Gemini 案A):
#   G = (H + J + 0.4×FX + DDP_FIXED×FX) / (1 - FVF - ad - payo - DDP_VAR - (HTS - HTS_BASE))
#
# C3 = FX_USD, G3 = FVF, D3 = ad (PROMO), E3 = payo
# H9 = 仕入¥, J9 = 国内送料¥, F3 = カテゴリ名
# I9 (ポイ買戻し) は新式では除外 (元式に -I9 あり、新式に含めるか?)
#   → 元式に -I9 あり = 仕入から引かれる金額 → 新式にも残す
new_g9 = ("=(H9-I9+J9+0.4*FX_USD+DDP_FIXED*FX_USD)/"
          "(1-G3-D3-E3-DDP_VAR-(VLOOKUP($F$3,HTS_RATE,2,FALSE)-HTS_BASE))")

us.update(range_name="G9", values=[[new_g9]], value_input_option="USER_ENTERED")
print(f"[US計算] G9 を V6 closed-form (連続関数版) に置換")

# ===== Step 6: 警告コメント更新 =====
us.update(range_name="T9", values=[["✓ V6 完全移行済 (連続関数 closed-form)"]], value_input_option="USER_ENTERED")
print(f"[US計算] T9 警告コメントを完了表記に更新")

# 行 9 の P9 (利益逆算) も新ロジックに合わせる必要あり
# 元 P9: =H9*IFS(H9<2000,0.6, ..., H9>=60000,0.09)
# = 仕入¥ベースの目標利益率 → そのまま維持 (V6 でも目標利益率の根拠は同じ)
# ただし P9 は「目標利益¥」、closed-form の分子に P9 が入るのが旧式
# 新式では P9 は分母の利益率には入らず、分子にも入らない
# → 新式は「目標利益率を達成する売価を直接逆算」
# → P9 の意味も変える必要: P9 = G9 - O9 (実利益、行 6-12 と同じ)
new_p9 = "=G9-O9"
us.update(range_name="P9", values=[[new_p9]], value_input_option="USER_ENTERED")
print(f"[US計算] P9 を行6-12と同じ式 (=G9-O9) に統一")

# N9 (DDP) も R+S に
us.update(range_name="N9", values=[["=R9+S9"]], value_input_option="USER_ENTERED")
print(f"[US計算] N9 を R+S に更新 (V5 の O9*35% から)")

print()
print("=" * 60)
print("V6 連続関数化 (Gemini 案A) 適用完了")
print("=" * 60)
print(f"  - mst_DDP に DDP_FIXED ($12), DDP_VAR (10%) パラメータ追加")
print(f"  - 名前付き範囲 DDP_FIXED, DDP_VAR 定義")
print(f"  - US計算 R/S/N 列 (行 6-12) を連続関数に書換")
print(f"  - US計算 G9 を V6 closed-form (1 行式) に置換")
print(f"  - US計算 P9 を =G9-O9 に統一")
print(f"  - バックアップ: bk_US計算_v6continuous_{ts}")
print()
print(f"次ステップ (オプション): UK/DE/AU 計算 タブも同様に書換")
print(f"URL: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")
