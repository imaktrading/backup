# -*- coding: utf-8 -*-
"""V6 完全実装 (Gemini 案A 連続関数化 + 目標利益率組込み)
1. mst_DDP に DDP_FIXED, DDP_VAR 復活
2. Named Range DDP_FIXED, DDP_VAR 追加
3. US/UK/DE/AU 計算 R/S/N 列を連続関数に
4. G9 を V6 closed-form (連続関数 + 目標利益率) に
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

ts = datetime.now().strftime("%Y%m%d_%H%M%S")

# ===== Step 1: mst_DDP に DDP_FIXED ($12), DDP_VAR (10%) 追加 =====
mst = sh.worksheet("mst_DDP")
mst.update(
    range_name="I1:J4",
    values=[
        ["DDP パラメータ (V6 連続関数)", ""],
        ["DDP_FIXED (USD)", 12],
        ["DDP_VAR (= 売価×%)", 0.10],
        ["備考", "Gemini案A 初期値、CPaSS実績で要再キャリブレ"],
    ],
    value_input_option="USER_ENTERED"
)
mst.format("I1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.91, "green": 0.94, "blue": 0.99}})
print("[mst_DDP] DDP_FIXED ($12), DDP_VAR (10%) 追加")

# ===== Step 2: Named Range DDP_FIXED, DDP_VAR 追加 =====
sheet_id_mst = mst.id

def a1_to_grid(ref, sheet_id):
    m = re.match(r"^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$", ref)
    def col(letters):
        n = 0
        for c in letters:
            n = n * 26 + (ord(c) - ord("A") + 1)
        return n - 1
    c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    return {
        "sheetId": sheet_id, "startRowIndex": r1 - 1,
        "endRowIndex": (int(r2) if r2 else r1),
        "startColumnIndex": col(c1),
        "endColumnIndex": (col(c2) if c2 else col(c1)) + 1,
    }

ranges = [("DDP_FIXED", sheet_id_mst, "J2"), ("DDP_VAR", sheet_id_mst, "J3")]
existing = sh.fetch_sheet_metadata().get("namedRanges", [])
del_req = [{"deleteNamedRange": {"namedRangeId": nr["namedRangeId"]}}
           for nr in existing if nr["name"] in [r[0] for r in ranges]]
if del_req:
    sh.batch_update({"requests": del_req})
add_req = [{"addNamedRange": {"namedRange": {"name": name, "range": a1_to_grid(ref, sid)}}}
           for name, sid, ref in ranges]
sh.batch_update({"requests": add_req})
print(f"[named range] DDP_FIXED, DDP_VAR 追加 (計 {len(add_req)} 件)")

# ===== Step 3: 各計算タブの書換 =====
# 各タブで処理: バックアップ → R/S/N 更新 → G9 closed-form
tabs_config = [
    ("US計算", "FX_USD"),  # US は FX_USD
    ("UK計算", "FX_GBP"),
    ("DE計算", "FX_EUR"),
    ("AU計算", "FX_AUD"),
]

for tab_name, fx_name in tabs_config:
    try:
        ws = sh.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        print(f"[skip] {tab_name} not found")
        continue

    # バックアップ
    ws.duplicate(new_sheet_name=f"bk_{tab_name}_v6final_{ts}")
    print(f"[backup] bk_{tab_name}_v6final_{ts}")

    # R5/S5 ヘッダ
    updates = [
        {"range": "R5", "values": [["DDP_A (連続: 10%+$12)"]]},
        {"range": "S5", "values": [["DDP_B (HTS補正)"]]},
    ]

    # 行 6-12: R/S/N
    for r in range(6, 13):
        updates.append({"range": f"R{r}", "values": [[f"=(F{r}*DDP_VAR + DDP_FIXED) * {fx_name}"]]})
        updates.append({"range": f"S{r}", "values": [[f"=F{r} * (VLOOKUP($F$3, HTS_RATE, 2, FALSE) - HTS_BASE) * {fx_name}"]]})
        updates.append({"range": f"N{r}", "values": [[f"=R{r}+S{r}"]]})

    # 行 9 G9 V6 closed-form (連続関数 + 仕入¥別 P9 組込み)
    # G9 = (H-I+J+0.4×FX + DDP_FIXED×FX + P9) / (1 - FVF - ad - payo - DDP_VAR - (HTS - HTS_BASE))
    new_g9 = (
        f"=(H9-I9+J9+0.4*{fx_name}+DDP_FIXED*{fx_name}+P9)/"
        f"(1-G3-D3-E3-DDP_VAR-(VLOOKUP($F$3,HTS_RATE,2,FALSE)-HTS_BASE))"
    )
    updates.append({"range": "G9", "values": [[new_g9]]})

    # P9 (V5 仕入¥別 IFS) はそのまま維持 (= H × 仕入¥利益率)
    p9_formula = (
        "=H9*IFS(H9<2000,0.6,H9<3500,0.5,H9<6000,0.4,H9<10000,0.32,"
        "H9<15000,0.27,H9<20000,0.25,H9<25000,0.22,H9<30000,0.2,"
        "H9<35000,0.18,H9<40000,0.17,H9<45000,0.15,H9<50000,0.14,"
        "H9<55000,0.13,H9<60000,0.12,H9>=60000,0.09)"
    )
    updates.append({"range": "P9", "values": [[p9_formula]]})

    # O9 = H-I+J+K+L+M+N9 (循環解消: N9 参照、P9 参照しない)
    updates.append({"range": "O9", "values": [["=H9-I9+J9+K9+L9+M9+N9"]]})

    # N9 = R9 + S9 (V6 連続関数 DDP)
    updates.append({"range": "N9", "values": [["=R9+S9"]]})

    # Q9 (利益率) は行 6-12 と同じ式 = P9/G9 ← ただし P9 は目標利益、Q9 は P9/G9 で目標利益率
    # 実利益率 = (G9 - O9) / G9 が知りたい → これは別セルで
    # 元の Q9 = P/G なのでこの構造維持
    # P9 が「目標利益」、Q9 が「目標利益率」、実利益は G-O で別途
    # 列追加 (T までしかないので 検証列を T 範囲内で完結 or 列追加)
    if ws.col_count < 24:
        ws.add_cols(24 - ws.col_count)
    updates.append({"range": "T9", "values": [["✓ V6 完全実装"]]})
    updates.append({"range": "U5", "values": [["実利益¥ (検証)"]]})
    updates.append({"range": "U9", "values": [["=G9-O9"]]})
    updates.append({"range": "V5", "values": [["実利益率 (検証)"]]})
    updates.append({"range": "V9", "values": [["=U9/G9"]]})

    ws.batch_update(updates, value_input_option="USER_ENTERED")
    print(f"[{tab_name}] V6 完全実装 ({len(updates)} セル)")

print()
print("=" * 60)
print("V6 完全実装 (Gemini 案A + 目標利益率組込み) 完了")
print("=" * 60)
print(f"  US/UK/DE/AU 計算 全タブで:")
print(f"  - R 列: 連続関数 (10%+$12)")
print(f"  - S 列: HTS 補正")
print(f"  - N 列: R + S")
print(f"  - G9: V6 closed-form (1行式、目標利益率 P9 を分子に組込)")
print(f"  - P9: V5 仕入¥別 IFS (目標利益額)")
print(f"  - O9: 循環解消")
print(f"  - V9 (実利益¥), X9 (実利益率): 検証列追加")
print(f"  - バックアップ: bk_*_v6final_{ts}")
print()
print(f"URL: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit")
