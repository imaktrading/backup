#!/usr/bin/env python3
import csv
import json
import re
import time
from datetime import datetime, timedelta

# API key読み込み
try:
    with open("API key.txt", "r", encoding="utf-8") as f:
        ANTHROPIC_API_KEY = f.read().strip()
except FileNotFoundError:
    ANTHROPIC_API_KEY = None
    print("WARNING: API key.txt not found. ConditionDescription will use existing values.")

SHEET_CSV = "商品管理シート.csv"

items = [
    {
        "CustomLabel": "MB-MOUNTAIN-PARKA-001",
        "Category": "57988",
        "Title": "montbell Nylon Mountain Parka Gray Black US M (JP L) Pre-owned Japan",
        "ConditionID": "3000",
        # Required
        "Brand": "montbell",
        "Type": "Jacket",
        "Size": "M",
        "Size Type": "Regular",
        "Color": "Gray",
        "Department": "Men",
        "Outer Shell Material": "Nylon",
        "Style": "Parka",
        # Additional (by search volume)
        "Lining Material": "Nylon",
        "Insulation Material": "Does not apply",
        "Theme": "Outdoor",
        "Features": "Hooded, Lightweight, Drawstring, Pockets",
        "Fabric Type": "Nylon",
        "Pattern": "Colorblock",
        "Accents": "Logo",
        "Model": "",
        "Product Line": "",
        "Closure": "Full Zip",
        "Performance/Activity": "Hiking, Outdoor",
        "Season": "Spring, Fall",
        "Occasion": "Casual, Outdoor",
        "Fit": "Regular",
        "Collar Style": "Hooded",
        "Vintage": "No",
        "Handmade": "No",
        "MPN": "",
        "UPC": "Does not apply",
        # CSV settings
        "ShippingProfileName": "100-200",
        "ConditionDescription": "No prominent scratches, stains, or damage. Minor storage wrinkles only. Please review all photos carefully before purchasing. Sold as-is.",
        "OfficialPicURL": "",
        "MercariPicURLs": "|".join([
            f"https://static.mercdn.net/item/detail/orig/photos/m53050750195_{i}.jpg?1764822465"
            for i in range(1, 12)
        ]),
        "MercariURL": "https://jp.mercari.com/item/m53050750195",
        "Measurements": "Length: 28.3 in (72 cm) / Width: 23.6 in (60 cm)",
    },
    {
        "CustomLabel": "MB-OD-ANORAK-001",
        "Category": "57988",
        "Title": "montbell O.D. Anorak Parka Khaki Green US L (JP XL) Pre-owned Japan",
        "ConditionID": "3000",
        "Brand": "montbell",
        "Type": "Jacket",
        "Size": "L",
        "Size Type": "Regular",
        "Color": "Green",
        "Department": "Men",
        "Outer Shell Material": "Nylon",
        "Style": "Anorak",
        "Lining Material": "Nylon",
        "Insulation Material": "Does not apply",
        "Theme": "Outdoor",
        "Features": "Hooded, Lightweight, Kangaroo Pocket, Drawstring, Pockets",
        "Fabric Type": "Nylon",
        "Pattern": "Solid",
        "Accents": "Logo",
        "Model": "O.D. Anorak",
        "Product Line": "O.D.",
        "Closure": "Half Zip",
        "Performance/Activity": "Hiking, Outdoor",
        "Season": "Spring, Fall",
        "Occasion": "Casual, Outdoor",
        "Fit": "Regular",
        "Collar Style": "Hooded",
        "Vintage": "No",
        "Handmade": "No",
        "MPN": "",
        "UPC": "Does not apply",
        "ShippingProfileName": "100-200",
        "ConditionDescription": "Worn 2-3 times. No prominent scratches, stains, or damage. Please review all photos carefully before purchasing. Sold as-is.",
        "OfficialPicURL": "https://raw.githubusercontent.com/imaktrading/ebay-images/main/montbell/mb_item2_official.jpg",
        "MercariPicURLs": "|".join([
            f"https://static.mercdn.net/item/detail/orig/photos/m74315748882_{i}.jpg?1775385045"
            for i in range(1, 4)
        ]),
        "MercariURL": "https://jp.mercari.com/item/m74315748882",
        "Measurements": "Shoulder: 20.5 in (52 cm) / Width: 25.2 in (64 cm) / Sleeve: 26.8 in (68 cm) / Length: 28.7 in (73 cm)",
    },
    {
        "CustomLabel": "MB-SHELL-JACKET-001",
        "Category": "57988",
        "Title": "montbell Nylon Shell Jacket Blue Green US M (JP L) Pre-owned Japan",
        "ConditionID": "3000",
        "Brand": "montbell",
        "Type": "Jacket",
        "Size": "M",
        "Size Type": "Regular",
        "Color": "Blue, Green",
        "Department": "Men",
        "Outer Shell Material": "Nylon",
        "Style": "Windbreaker",
        "Lining Material": "Nylon",
        "Insulation Material": "Does not apply",
        "Theme": "Outdoor",
        "Features": "Hooded, Lightweight, Packable, Drawstring, Pockets",
        "Fabric Type": "Nylon",
        "Pattern": "Colorblock",
        "Accents": "Logo",
        "Model": "",
        "Product Line": "",
        "Closure": "Full Zip",
        "Performance/Activity": "Hiking, Outdoor",
        "Season": "Spring, Fall",
        "Occasion": "Casual, Outdoor",
        "Fit": "Regular",
        "Collar Style": "Hooded",
        "Vintage": "No",
        "Handmade": "No",
        "MPN": "",
        "UPC": "Does not apply",
        "ShippingProfileName": "100-200",
        "ConditionDescription": "Worn twice. Seam tape shows deterioration and may need replacement or removal. No prominent stains or damage on exterior surface. Includes original stuff sack. Please review all photos carefully before purchasing. Sold as-is.",
        "OfficialPicURL": "",
        "MercariPicURLs": "|".join([
            f"https://static.mercdn.net/item/detail/orig/photos/m24583495329_{i}.jpg?1774628312"
            for i in range(1, 3)
        ] + [
            f"https://static.mercdn.net/item/detail/orig/photos/m24583495329_{i}.jpg?1773849541"
            for i in range(3, 14)
        ]),
        "MercariURL": "https://jp.mercari.com/item/m24583495329",
        "Measurements": "Raglan Sleeve: 33.5 in (85 cm) / Width: 22.4 in (57 cm) / Length: 26.8 in (68 cm)",
    },
    {
        "CustomLabel": "MB-WINDBLAST-001",
        "Category": "57988",
        "Title": "montbell Wind Blast Parka Navy Blue US L (JP XL) Pre-owned Japan",
        "ConditionID": "3000",
        "Brand": "montbell",
        "Type": "Jacket",
        "Size": "L",
        "Size Type": "Regular",
        "Color": "Blue",
        "Department": "Men",
        "Outer Shell Material": "Nylon",
        "Style": "Parka",
        "Lining Material": "Nylon",
        "Insulation Material": "Does not apply",
        "Theme": "Outdoor",
        "Features": "Hooded, Lightweight, Drawstring, Pockets",
        "Fabric Type": "Nylon",
        "Pattern": "Solid",
        "Accents": "Logo",
        "Model": "Wind Blast Parka",
        "Product Line": "Wind Blast",
        "Closure": "Full Zip",
        "Performance/Activity": "Hiking, Outdoor",
        "Season": "Spring, Fall",
        "Occasion": "Casual, Outdoor",
        "Fit": "Regular",
        "Collar Style": "Hooded",
        "Vintage": "No",
        "Handmade": "No",
        "MPN": "1103242",
        "UPC": "Does not apply",
        "ShippingProfileName": "60-100",
        "ConditionDescription": "Used sparingly with minimal wear. No prominent scratches, stains, or damage. Please review all photos carefully before purchasing. Sold as-is.",
        "OfficialPicURL": "https://raw.githubusercontent.com/imaktrading/ebay-images/main/montbell/mb_item4_official.jpg",
        "MercariPicURLs": "|".join([
            f"https://static.mercdn.net/item/detail/orig/photos/m48607877109_{i}.jpg?1775395558"
            for i in range(1, 12)
        ]),
        "MercariURL": "https://jp.mercari.com/item/m48607877109",
        "Measurements": "Width: 24.4 in (62 cm) / Length: 28.0 in (71 cm) / Raglan Sleeve: 35.4 in (90 cm)",
    },
    {
        "CustomLabel": "MB-LIGHTSHELL-001",
        "Category": "57988",
        "Title": "montbell Light Shell Parka Blue Nylon US L (JP XL) Pre-owned Japan",
        "ConditionID": "3000",
        "Brand": "montbell",
        "Type": "Jacket",
        "Size": "L",
        "Size Type": "Regular",
        "Color": "Blue",
        "Department": "Men",
        "Outer Shell Material": "Nylon",
        "Style": "Windbreaker",
        "Lining Material": "Mesh",
        "Insulation Material": "Does not apply",
        "Theme": "Outdoor",
        "Features": "Hooded, Lightweight, Mesh Lining, Drawstring, Pockets",
        "Fabric Type": "Nylon",
        "Pattern": "Solid",
        "Accents": "Logo",
        "Model": "",
        "Product Line": "",
        "Closure": "Full Zip",
        "Performance/Activity": "Hiking, Outdoor",
        "Season": "Spring, Fall",
        "Occasion": "Casual, Outdoor",
        "Fit": "Regular",
        "Collar Style": "Hooded",
        "Vintage": "No",
        "Handmade": "No",
        "MPN": "1128291",
        "UPC": "Does not apply",
        "ShippingProfileName": "60-100",
        "ConditionDescription": "Shows signs of wear but no prominent stains or scratches on exterior. Seam tape has deteriorated and may need replacement or removal. Please review all photos carefully before purchasing. Sold as-is.",
        "OfficialPicURL": "https://raw.githubusercontent.com/imaktrading/ebay-images/main/montbell/mb_item5_official.jpg",
        "MercariPicURLs": "|".join([
            f"https://static.mercdn.net/item/detail/orig/photos/m78541679394_{i}.jpg?1769224689"
            for i in range(1, 10)
        ]),
        "MercariURL": "https://jp.mercari.com/item/m78541679394",
        "Measurements": "Length: 26.0 in (66 cm) / Width: 23.2 in (59 cm) / Sleeve: 31.5 in (80 cm)",
    },
]

fieldnames = [
    # === Listing basics ===
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "CustomLabel",
    "*Category",
    "*Title",
    "*ConditionID",
    "*Format",
    "*Duration",
    "*Quantity",
    "*Location",
    "StoreCategoryID",
    "BestOfferEnabled",
    "ShippingProfileName",
    "ReturnProfileName",
    "PaymentProfileName",
    "PayPalAccepted",
    "*StartPrice",
    "ScheduleTime",
    # === Required Item Specifics ===
    "C:Brand",
    "C:Type",
    "C:Size",
    "C:Size Type",
    "C:Color",
    "C:Department",
    "C:Outer Shell Material",
    "C:Style",
    # === Additional Item Specifics (by search volume) ===
    "C:Lining Material",           # ~915K
    "C:Insulation Material",       # ~561K
    "C:Theme",                     # ~481K
    "C:Features",                  # ~451K
    "C:Fabric Type",               # ~449K
    "C:Pattern",                   # ~324K
    "C:Accents",                   # ~320K
    "C:Model",                     # ~197K
    "C:Product Line",              # ~144K
    "C:Closure",                   # ~123K
    "C:Performance/Activity",      # ~115K
    "C:Season",                    # ~67K
    "C:Occasion",                  # ~28K
    "C:Fit",                       # ~24K
    "C:Vintage",                   # ~15K
    "C:Collar Style",              # ~7K
    "C:Handmade",                  # ~4K
    "C:Country of Origin",
    "C:MPN",
    "C:UPC",
    # === Other ===
    "ConditionDescription",
    "*Description",
    "PicURL",
]

SCHEDULE_TIME = (datetime.utcnow() + timedelta(weeks=2)).strftime("%Y-%m-%d %H:%M:%S")
DESCRIPTION_FILE = "USED.txt"


def load_mercari_sheet():
    """商品管理シートからURL→(状態, 商品説明)のマップを作成"""
    try:
        with open(SHEET_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            jotai_key = headers[4]
            shohin_key = headers[7]
            result = {}
            for row in reader:
                url = row["URL"]
                result[url] = {
                    "jotai": row[jotai_key],
                    "shohin": row[shohin_key],
                }
            return result
    except Exception as e:
        print(f"WARNING: {SHEET_CSV} read error: {e}")
        return {}


def generate_condition_description(jotai, shohin):
    """Claude APIで状態・商品説明から英語ConditionDescriptionを生成"""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            system="You extract condition-related information from Japanese Mercari listings and translate to concise English for eBay. Return ONLY the condition description text, no JSON, no quotes, no explanation.",
            messages=[{"role": "user", "content": f"""Extract condition-related descriptions from this Mercari listing and translate to English.
Focus ONLY on: scratches, stains, wear, damage, missing parts, discoloration, odor, functionality issues.
Ignore: dimensions, brand info, shipping info, seller greetings.
Keep it concise (2-5 sentences).
End with: Please review all photos carefully before purchasing. Sold as-is.

Mercari condition label: {jotai}

Seller description:
{shohin[:1000]}"""}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"    API error: {e}")
        return None


def load_base_description():
    """USED.txtを読み込む"""
    try:
        with open(DESCRIPTION_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def build_specs_html(item):
    """Specificationsブロック生成（衣類用）"""
    specs = []
    specs.append(f"<li><b>Brand:</b> {item['Brand']}</li>")
    specs.append(f"<li><b>Type:</b> {item['Style']}</li>")
    specs.append(f"<li><b>Material:</b> {item['Outer Shell Material']}</li>")
    specs.append(f"<li><b>Lining:</b> {item['Lining Material']}</li>")
    specs.append(f"<li><b>Color:</b> {item['Color']}</li>")
    specs.append(f"<li><b>Size:</b> US {item['Size']} (JP size)</li>")
    if item.get("Measurements"):
        specs.append(f"<li><b>Measurements:</b> {item['Measurements']}</li>")
    if item.get("Closure"):
        specs.append(f"<li><b>Closure:</b> {item['Closure']}</li>")
    if item.get("Features"):
        specs.append(f"<li><b>Features:</b> {item['Features']}</li>")
    if item.get("Model"):
        specs.append(f"<li><b>Model:</b> {item['Model']}</li>")

    return f"""<p><span style="text-decoration: underline;"><strong><span style="vertical-align: inherit;"><span style="vertical-align: inherit;">Specifications</span></span></strong></span></p>
<ul>
{chr(10).join(specs)}
</ul>"""


def build_description(item, base_html):
    """USED.txtにSpecificationsブロックを挿入"""
    specs_html = build_specs_html(item)
    if not base_html:
        return f"""<html><body><p><b>We handle genuine Japanese products.</b></p>
{specs_html}
<p>Thank you for your understanding and cooperation.</p>
</body></html>"""
    marker = '<p><span style="text-decoration: underline;"><strong>Shipping'
    if marker in base_html:
        return base_html.replace(marker, specs_html + '\n' + marker, 1)
    return base_html


# サイズチャート画像（衣類リスティング用）
# TODO: GitHubにアップロード後、URLを更新する
SIZE_CHART_URL = "https://raw.githubusercontent.com/imaktrading/ebay-images/main/common/size_chart_tshirt.png"


def build_pic_url(item):
    """公式画像（あれば先頭）+ メルカリ全画像 + サイズチャート（衣類の場合）をパイプ区切りで結合"""
    urls = []
    official = item.get("OfficialPicURL", "")
    if official:
        urls.append(official)
    mercari = item.get("MercariPicURLs", "")
    if mercari:
        urls.extend(mercari.split("|"))
    # 衣類カテゴリ（57988=ジャケット, 11450=Tシャツ等）にはサイズチャートを必ず添付
    category = str(item.get("Category", ""))
    clothing_categories = {"57988", "11450", "15687", "11484", "11483"}
    if category in clothing_categories and SIZE_CHART_URL:
        urls.append(SIZE_CHART_URL)
    return "|".join(urls)


def build_row(item, base_desc):
    """1商品 → CSVの1行（リスト）を生成"""
    return [
        # Listing basics
        "Add",
        item["CustomLabel"],
        item["Category"],
        item["Title"],
        item["ConditionID"],
        "FixedPrice",
        "GTC",
        1,
        "Japan",
        41828939010,                     # StoreCategoryID (Outdoor Jackets)
        1,
        item.get("ShippingProfileName", "60-100"),
        "customer1",
        "SALE",
        1,
        100,
        SCHEDULE_TIME,
        # Required Item Specifics
        item.get("Brand", ""),
        item.get("Type", ""),
        item.get("Size", ""),
        item.get("Size Type", ""),
        item.get("Color", ""),
        item.get("Department", ""),
        item.get("Outer Shell Material", ""),
        item.get("Style", ""),
        # Additional Item Specifics (by search volume)
        item.get("Lining Material", ""),
        item.get("Insulation Material", ""),
        item.get("Theme", ""),
        item.get("Features", ""),
        item.get("Fabric Type", ""),
        item.get("Pattern", ""),
        item.get("Accents", ""),
        item.get("Model", ""),
        item.get("Product Line", ""),
        item.get("Closure", ""),
        item.get("Performance/Activity", ""),
        item.get("Season", ""),
        item.get("Occasion", ""),
        item.get("Fit", ""),
        item.get("Vintage", ""),
        item.get("Collar Style", ""),
        item.get("Handmade", ""),
        item.get("Country of Origin", "Does not apply"),
        item.get("MPN", ""),
        item.get("UPC", ""),
        # Other
        item.get("ConditionDescription", ""),
        build_description(item, base_desc),
        build_pic_url(item),
    ]


# USED.txt読み込み＋確認
base_desc = load_base_description()
if base_desc:
    has_shipping = '<strong>Shipping' in base_desc
    has_html = '<html' in base_desc
    print(f"USED.txt: loaded OK ({len(base_desc)} chars, html={has_html}, shipping_marker={has_shipping})")
else:
    print("WARNING: USED.txt not found or empty. Using fallback HTML.")

# 商品管理シートから状態情報を読み込み → ConditionDescription生成
sheet_data = load_mercari_sheet()
print(f"Sheet: {len(sheet_data)} items loaded")

for item in items:
    mercari_url = item.get("MercariURL", "")
    if mercari_url in sheet_data and ANTHROPIC_API_KEY:
        sd = sheet_data[mercari_url]
        print(f"  Generating ConditionDescription for {item['CustomLabel']}...")
        cd = generate_condition_description(sd["jotai"], sd["shohin"])
        if cd:
            item["ConditionDescription"] = cd
            print(f"    OK: {cd[:80]}...")
        else:
            print(f"    Failed, using existing value")
        time.sleep(1)
    elif not item.get("ConditionDescription"):
        item["ConditionDescription"] = "Pre-owned item from Japan. Please review all photos carefully before purchasing. Sold as-is."

output_file = f"ebay_fileexchange_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
rows = [fieldnames]
for item in items:
    rows.append(build_row(item, base_desc))

with open(output_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
    writer.writerows(rows)

print(f"\nDone: {output_file} ({len(items)} items)")
