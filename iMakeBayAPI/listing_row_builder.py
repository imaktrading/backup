#!/usr/bin/env python3
"""iMak Trading Japan - Deterministic CSV row builder (Step 4 真の本番).

入力 (PSA + Bandai + 凍結 schedule + cost) から CSV 1 行を deterministic に生成。
外部 API には一切依存しない（呼出元が事前に解決済の JSON を渡す前提）。
これによりゴールデンテストで byte 一致検証が可能。

設計方針:
- 純関数。同じ入力 → 必ず同じ出力。
- 副作用なし（ログ書込・キャッシュなし）。
- yaml(SSOT) 経由で eBay 共通定数を参照。
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Any, Dict

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import config_loader  # noqa: E402


# 凍結 CSV 列順 (eBay File Exchange TCG)
COLUMN_ORDER = [
    "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)",
    "*Category",
    "*Title",
    "PicURL",
    "*StartPrice",
    "ConditionID",
    "CD:Professional Grader - (ID: 27501)",
    "CD:Grade - (ID: 27502)",
    "CDA:Certification Number - (ID: 27503)",
    "ScheduleTime",
    "CustomLabel",
    "*Format",
    "*Duration",
    "*Quantity",
    "*Location",
    "BestOfferEnabled",
    "ShippingProfileName",
    "ReturnProfileName",
    "PaymentProfileName",
    "C:Game",
    "C:Set",
    "C:Card Type",
    "C:Card Name",
    "C:Character",
    "C:Card Number",
    "C:Rarity",
    "C:Manufacturer",
    "C:Language",
    "C:Country of Origin",
    "C:Card Condition",
    "C:Grade",
    "C:Professional Grader",
    "StoreCategoryID",
]


def build_listing_row(input_data: Dict[str, Any]) -> Dict[str, str]:
    """凍結された入力から deterministic に CSV 1 行を生成.

    Args:
        input_data: golden_input_*.json shape の dict（psa_response / bandai_card / frozen_inputs）

    Returns:
        CSV 1 行を表す OrderedDict-like dict（COLUMN_ORDER 順）
    """
    psa = input_data["psa_response"]["PSACert"]
    bandai = input_data["bandai_card"]
    frozen = input_data["frozen_inputs"]

    ebay_const = config_loader.get_ebay_constants()

    # ReturnProfile はプロジェクトと無関係に TCG 用「No return」で固定（CLAUDE.md 規約）
    return_profile = config_loader.get_return_profile("iMakTCG") or "No return"

    cert_number = psa.get("CertNumber", "")
    grade = psa.get("Grade", "")

    row = {
        "*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)": "Add",
        "*Category": str(frozen.get("ebay_category", "")),
        "*Title": frozen.get("title_override", ""),
        "PicURL": frozen.get("pic_url", ""),
        "*StartPrice": str(frozen.get("start_price_usd", "")),
        "ConditionID": "2750",
        "CD:Professional Grader - (ID: 27501)": "275010",
        "CD:Grade - (ID: 27502)": "275020",
        "CDA:Certification Number - (ID: 27503)": cert_number,
        "ScheduleTime": frozen.get("schedule_time", ""),
        "CustomLabel": f"{psa.get('CardNumber', '')}-PSA{grade}",
        "*Format": ebay_const.get("format", "FixedPrice"),
        "*Duration": ebay_const.get("duration", "GTC"),
        "*Quantity": "1",
        "*Location": "Japan",
        "BestOfferEnabled": "0",
        "ShippingProfileName": frozen.get("shipping_profile_name", ""),
        "ReturnProfileName": return_profile,
        "PaymentProfileName": ebay_const.get("payment_profile_name", "SALE"),
        "C:Game": _infer_game(psa.get("Brand", "")),
        "C:Set": bandai.get("set_name", ""),
        "C:Card Type": bandai.get("card_type", ""),
        "C:Card Name": bandai.get("card_name", ""),
        "C:Character": psa.get("Subject", ""),
        "C:Card Number": bandai.get("card_number", ""),
        "C:Rarity": bandai.get("rarity", ""),
        "C:Manufacturer": "Bandai",
        "C:Language": "English",
        "C:Country of Origin": "Does not apply",
        "C:Card Condition": "Graded",
        "C:Grade": str(grade),
        "C:Professional Grader": "Professional Sports Authenticator (PSA)",
        "StoreCategoryID": str(frozen.get("store_category_id", "")),
    }
    return row


def _infer_game(psa_brand: str) -> str:
    """PSA brand から eBay Game フィールドを推定（決定論的）"""
    b = (psa_brand or "").upper()
    if "ONE PIECE" in b:
        return "One Piece TCG"
    if "GUNDAM" in b:
        return "Gundam Card Game"
    if "DRAGON BALL" in b or "FUSION WORLD" in b:
        return "Dragon Ball Super Card Game"
    return ""


def row_to_csv_string(row: Dict[str, str]) -> str:
    """row dict を CSV 文字列 (header + 1 data row, LF 終端) に変換.

    QUOTE_NONNUMERIC で eBay File Exchange 規約に準拠.
    """
    import csv
    import io
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_NONNUMERIC, lineterminator="\n")
    writer.writerow(COLUMN_ORDER)
    writer.writerow([row.get(col, "") for col in COLUMN_ORDER])
    return buf.getvalue()
