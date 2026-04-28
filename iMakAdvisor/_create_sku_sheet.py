import gspread
from google.oauth2.service_account import Credentials

creds = Credentials.from_service_account_file(
    r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
gc = gspread.authorize(creds)
sh = gc.open_by_key("101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0")

# 既に「SKU詳細」がある場合は削除して作り直し
for ws in sh.worksheets():
    if ws.title == "SKU詳細":
        sh.del_worksheet(ws)
        break

ws = sh.add_worksheet(title="SKU詳細", rows=100, cols=12)

headers = [
    "対処要", "対処済", "対処日", "listing ID", "title",
    "eBay SKU ID", "サイズ", "色", "仕入元在庫", "仕入元価格",
    "eBay 現Qty", "自動CHK日"
]

mens_str = "Men" + chr(39) + "s"  # シングルクォート回避

sample_rows = [
    [False, False, "", "357401200653", "マンガキュレーション UT/ベルセルク", "MK-UT-S-Black",  "S",  "Black", "◎", 1500, 1, "2026/04/27 10:00"],
    [False, False, "", "357401200653", "マンガキュレーション UT/ベルセルク", "MK-UT-M-Black",  "M",  "Black", "◎", 1500, 1, "2026/04/27 10:00"],
    [True,  False, "", "357401200653", "マンガキュレーション UT/ベルセルク", "MK-UT-L-Black",  "L",  "Black", "✕", 1500, 1, "2026/04/27 10:00"],
    [True,  False, "", "357401200653", "マンガキュレーション UT/ベルセルク", "MK-UT-XL-Black", "XL", "Black", "✕", 1500, 1, "2026/04/27 10:00"],

    [False, False, "", "358205313998", "ワンピース UT",  "OP-UT-S-Red",  "S",  "Red", "◎", 1500, 1, "2026/04/27 10:00"],
    [False, False, "", "358205313998", "ワンピース UT",  "OP-UT-M-Red",  "M",  "Red", "◎", 1500, 1, "2026/04/27 10:00"],
    [False, False, "", "358205313998", "ワンピース UT",  "OP-UT-L-Red",  "L",  "Red", "◎", 1500, 1, "2026/04/27 10:00"],
    [False, False, "", "358205313998", "ワンピース UT",  "OP-UT-XL-Red", "XL", "Red", "◎", 1500, 1, "2026/04/27 10:00"],

    [False, False, "", "357448285020", "ポケモン UT", "PK-UT-S-Black",  "S",  "Black", "◎", 1500, 1, "2026/04/27 10:00"],
    [True,  False, "", "357448285020", "ポケモン UT", "PK-UT-M-Black",  "M",  "Black", "✕", 1500, 1, "2026/04/27 10:00"],
    [False, False, "", "357448285020", "ポケモン UT", "PK-UT-L-Black",  "L",  "Black", "◎", 1500, 1, "2026/04/27 10:00"],
    [False, False, "", "357448285020", "ポケモン UT", "PK-UT-XL-Black", "XL", "Black", "◎", 1500, 1, "2026/04/27 10:00"],

    [False, False, "", "358275199203", f"ウインドブラスト パーカ {mens_str}", "WB-PRK-S-DBL",  "S",  "DkBlue", "◎", 8800, 1, "2026/04/27 10:00"],
    [False, False, "", "358275199203", f"ウインドブラスト パーカ {mens_str}", "WB-PRK-M-DBL",  "M",  "DkBlue", "◎", 8800, 1, "2026/04/27 10:00"],
    [False, False, "", "358275199203", f"ウインドブラスト パーカ {mens_str}", "WB-PRK-L-DBL",  "L",  "DkBlue", "◎", 8800, 1, "2026/04/27 10:00"],
    [True,  True,  "2026/04/26", "358275199203", f"ウインドブラスト パーカ {mens_str}", "WB-PRK-XL-DBL", "XL", "DkBlue", "✕", 8800, 0, "2026/04/27 10:00"],

    [True, False, "", "357100759244", f"サンダーパス ジャケット {mens_str} RED", "TP-JKT-S-Red",  "S",  "Red", "✕", 0, 1, "2026/04/27 10:00"],
    [True, False, "", "357100759244", f"サンダーパス ジャケット {mens_str} RED", "TP-JKT-M-Red",  "M",  "Red", "✕", 0, 1, "2026/04/27 10:00"],
    [True, False, "", "357100759244", f"サンダーパス ジャケット {mens_str} RED", "TP-JKT-L-Red",  "L",  "Red", "✕", 0, 1, "2026/04/27 10:00"],
    [True, False, "", "357100759244", f"サンダーパス ジャケット {mens_str} RED", "TP-JKT-XL-Red", "XL", "Red", "✕", 0, 1, "2026/04/27 10:00"],
]

ws.update("A1:L1", [headers])
end_row = 1 + len(sample_rows)
ws.update(f"A2:L{end_row}", sample_rows)

worksheet_id = ws.id
sh.batch_update({
    "requests": [
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 0,  "endIndex": 1},  "properties": {"pixelSize": 60},  "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 1,  "endIndex": 2},  "properties": {"pixelSize": 60},  "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 2,  "endIndex": 3},  "properties": {"pixelSize": 90},  "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 3,  "endIndex": 4},  "properties": {"pixelSize": 110}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 4,  "endIndex": 5},  "properties": {"pixelSize": 280}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 5,  "endIndex": 6},  "properties": {"pixelSize": 130}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 6,  "endIndex": 7},  "properties": {"pixelSize": 50},  "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 7,  "endIndex": 8},  "properties": {"pixelSize": 70},  "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 8,  "endIndex": 9},  "properties": {"pixelSize": 80},  "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 9,  "endIndex": 10}, "properties": {"pixelSize": 90},  "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 10, "endIndex": 11}, "properties": {"pixelSize": 80},  "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": worksheet_id, "dimension": "COLUMNS", "startIndex": 11, "endIndex": 12}, "properties": {"pixelSize": 130}, "fields": "pixelSize"}},

        {"repeatCell": {
            "range": {"sheetId": worksheet_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}, "horizontalAlignment": "CENTER"}},
            "fields": "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment)"
        }},

        {"updateSheetProperties": {
            "properties": {"sheetId": worksheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount"
        }},

        {"addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": worksheet_id, "startRowIndex": 1, "endRowIndex": 100, "startColumnIndex": 0, "endColumnIndex": 12}],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=AND($A2=TRUE, $B2=FALSE)"}]},
                    "format": {"backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.85}}
                }
            },
            "index": 0
        }},

        {"addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": worksheet_id, "startRowIndex": 1, "endRowIndex": 100, "startColumnIndex": 0, "endColumnIndex": 12}],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": "=$B2=TRUE"}]},
                    "format": {"backgroundColor": {"red": 0.85, "green": 1.0, "blue": 0.85}}
                }
            },
            "index": 1
        }},

        {"setDataValidation": {
            "range": {"sheetId": worksheet_id, "startRowIndex": 1, "endRowIndex": 100, "startColumnIndex": 0, "endColumnIndex": 1},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
        }},
        {"setDataValidation": {
            "range": {"sheetId": worksheet_id, "startRowIndex": 1, "endRowIndex": 100, "startColumnIndex": 1, "endColumnIndex": 2},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
        }},
    ]
})

print(f"OK SKU詳細シート作成完了: {len(sample_rows)} 行のサンプル")
print(f"URL: https://docs.google.com/spreadsheets/d/101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0/edit#gid={worksheet_id}")
