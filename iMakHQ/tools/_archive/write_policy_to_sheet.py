# -*- coding: utf-8 -*-
"""93 Policy 一覧を「DDP対応sippingポリシー」スプシに新規シート追加で書込
URL: https://docs.google.com/spreadsheets/d/10ey-ACBlbIBR5QbnWTjnwaltjINPOd6cUN-4N5xSUIo/
"""
import sys
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path

# yaml SSOT 参照 (V8 FIX 2026-05-24: split 直書き廃止)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "iMakeBayAPI"))
import config_loader

CREDS = Path(r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
SHEET_ID = "10ey-ACBlbIBR5QbnWTjnwaltjINPOd6cUN-4N5xSUIo"

gc = gspread.authorize(Credentials.from_service_account_file(str(CREDS), scopes=SCOPES))
sh = gc.open_by_key(SHEET_ID)

# 段階ピッチ価格帯
bins = [
    (10, "<$10"), (20, "$10-20"), (30, "$20-30"), (40, "$30-40"), (50, "$40-50"),
    (60, "$50-60"), (70, "$60-70"), (80, "$70-80"), (90, "$80-90"), (100, "$90-100"),
    (120, "$100-120"), (140, "$120-140"), (160, "$140-160"), (180, "$160-180"), (200, "$180-200"),
    (220, "$200-220"), (240, "$220-240"), (260, "$240-260"), (280, "$260-280"), (300, "$280-300"),
    (350, "$300-350"), (400, "$350-400"), (450, "$400-450"), (500, "$450-500"),
    (550, "$500-550"), (600, "$550-600"),
    (700, "$600-700"), (800, "$700-800"), (900, "$800-900"), (1000, "$900-1000"),
    (1500, "$1000-1500"),
]

# yaml から split / rate を取得 (= SSOT 統一、 直書き廃止)
_v6 = config_loader.get_v6_pricing()
_yaml_groups = _v6.get("groups", {})

def _design_label(split: float) -> str:
    if split >= 1.0:
        return "案A 全DDP送料"
    return f"案B DDP{int(split*100)}%送料+{int((1-split)*100)}%商品"

# カテゴリ表示用 (= yaml の category_to_group から逆引き)
_cat_by_group = {}
for cat, gid in _v6.get("category_to_group", {}).items():
    _cat_by_group.setdefault(gid, []).append(cat)

groups = {
    gid: {
        "rate": float(g["hts_rate"]),
        "split": float(g["split"]),
        "name": {"A": "低関税", "B": "中関税", "C": "高関税"}.get(gid, gid),
        "design": _design_label(float(g["split"])),
        "categories": " / ".join(_cat_by_group.get(gid, [])),
    }
    for gid, g in _yaml_groups.items()
}

# 既存シート確認
from datetime import datetime
sheet_name = f"V6_Policy_93個_{datetime.now().strftime('%Y%m%d')}"
try:
    existing = sh.worksheet(sheet_name)
    sh.del_worksheet(existing)
    print(f"[reset] 既存 {sheet_name} 削除")
except gspread.WorksheetNotFound:
    pass

ws = sh.add_worksheet(title=sheet_name, rows=120, cols=10)
print(f"[create] {sheet_name} タブ追加")

# データ生成
rows = []
# ヘッダ + 概要
rows.append(["V6 DDP対応 eBay Shipping Policy 一覧 (93個)", "", "", "", "", "", ""])
rows.append(["生成日", datetime.now().strftime("%Y-%m-%d"), "", "", "", "", ""])
rows.append(["", "", "", "", "", "", ""])
rows.append(["グループ", "対象カテゴリ", "hts_rate", "設計", "送料計算", "", ""])
for gid, g in groups.items():
    formula = f"F × {g['rate']:.2f} × 1.021"
    if g['split'] < 1.0:
        formula += f" × {g['split']:.1f}"
    formula += " + $1.5"
    rows.append([f"グループ {gid}", g['categories'], g['rate'], g['design'], formula, "", ""])
rows.append(["", "", "", "", "", "", ""])

# 全 Policy 表
rows.append(["Policy ID", "グループ", "価格帯", "上限$", "rate", "送料$", "送料率% (上限基準)"])
for gid, g in groups.items():
    for i, (upper, label) in enumerate(bins, 1):
        cost = upper * g['rate'] * 1.021 * g['split'] + 1.5
        rate_pct = (cost / upper * 100) if upper > 0 else 0
        rows.append([
            f"DDP-{gid}-P{i:02d}",
            gid,
            label,
            upper,
            g['rate'],
            round(cost, 2),
            f"{rate_pct:.1f}%",
        ])

# 一括書込
ws.update(range_name=f"A1:G{len(rows)}", values=rows, value_input_option='USER_ENTERED')
print(f"[write] {len(rows)} 行書込")

# 装飾
ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
ws.format("A4:E4", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.86, "green": 0.90, "blue": 0.95}})
ws.format(f"A{len(rows)-93}:G{len(rows)-93}", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.86, "green": 0.90, "blue": 0.95}})

# 列幅 (gspread はsheets API直叩きで設定)
print(f"\nURL: https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid={ws.id}")
