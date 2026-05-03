"""Montbell カテゴリ専用 whitelist + validator (2026-05-03 専門化)

設計思想:
  共有 whitelist_registry.py から Montbell を切出し、完全独立。
  - 商品を極めるには専門化が必要 (memory: category_specialization_principle)
  - 共有は心理的ブレーキ + 構造の不自由を生む
  - 修正連鎖を物理的にゼロにする (memory: no_modification_chain)

依存:
  外部依存ゼロ (re のみ)。共通モジュール whitelist_registry にも依存しない。

将来:
  iMakCatalog/scrapers/montbell.py (公式DB) 完成時、本ファイルは廃止して
  api.lookup("montbell", model_number) 経由に切替。

eBay 公式フィルタ値の根拠:
  2026-04-23 ユーザーが共有した Montbell カテゴリのフィルタ画面コピー全 13 枚に
  基づき whitelist を構築。Not Specified は eBay 公式の正規ドロップダウン値。
"""
import re


# ============================================================================
# Montbell whitelist (eBay 公式フィルタ値 + Not Specified)
# ============================================================================
MONTBELL_WHITELIST = {
    "Brand": {
        "values": ["montbell", "Mont-Bell", "Mont-bell"],
        "strict": True,
        "normalize": {"MONTBELL": "montbell", "Montbell": "montbell", "Mont Bell": "montbell"},
    },
    "Type": {
        "values": ["Cape", "Coat", "Coatigan", "Jacket", "Vest"],
        "strict": True,
        "normalize": {"Parka": "Jacket", "Hoodie": "Jacket", "Pullover": "Jacket"},
    },
    "Style": {
        "values": [
            "3-in-1 Jacket", "Anorak", "Biker", "Bomber Jacket", "Military Jacket",
            "Motorcycle Jacket", "Overcoat", "Parka", "Puffer Jacket", "Quilted",
            "Rain Coat", "Trench Coat", "Varsity Jacket", "Windbreaker",
            "Not Specified",
        ],
        "strict": True,
        "normalize": {
            "Shell": "Windbreaker",
            "Shell Jacket": "Windbreaker",
            "Soft Shell": "Windbreaker",
            "Hard Shell": "Rain Coat",
            "Down Jacket": "Puffer Jacket",
            "Down": "Puffer Jacket",
            "Insulated Jacket": "Puffer Jacket",
            "Hooded": "Parka",
            "Wind Jacket": "Windbreaker",
            "Cycling Jacket": "Windbreaker",
            "Light Shell": "Windbreaker",
        },
    },
    "Outer Shell Material": {
        "values": ["Cotton", "Cotton Blend", "Nylon", "Polyamide", "Polyester", "Tweed", "Viscose", "Wool", "Not Specified"],
        "strict": True,
        "normalize": {"Nylon Ripstop": "Nylon", "Polyester Blend": "Polyester", "Does not apply": "Not Specified"},
    },
    "Lining Material": {
        "values": ["Acetate", "Cotton", "Nylon", "Polyamide", "Polyester", "Wool", "Not Specified"],
        "strict": True,
        "normalize": {"Does not apply": "Not Specified"},
    },
    "Insulation Material": {
        "values": ["Down", "Polyester", "Synthetic", "Wool", "Not Specified"],
        "strict": True,
        "normalize": {"Goose Down": "Down", "Duck Down": "Down", "Synthetic Down": "Synthetic", "PrimaLoft": "Synthetic", "Does not apply": "Not Specified"},
    },
    "Fabric Type": {
        "values": ["Canvas", "Denim", "Flannel", "Fleece", "Knit", "Microfiber", "Softshell", "Tweed", "Not Specified"],
        "strict": True,
        "normalize": {"Soft Shell": "Softshell", "Soft-Shell": "Softshell", "Nylon": "Not Specified", "Polyester": "Not Specified", "Does not apply": "Not Specified"},
    },
    "Closure": {
        "values": ["Button", "Drawstring", "Hook & Eye", "Hook & Loop", "Lace Up", "Snap", "Zip"],
        "strict": True,
        "normalize": {
            "Full Zip": "Zip",
            "Half Zip": "Zip",
            "1/4 Zip": "Zip",
            "1/2 Zip": "Zip",
            "Zipper": "Zip",
            "Pullover": "",  # Jacket Closure には無効値なので削除
            "Velcro": "Hook & Loop",
        },
    },
    "Performance/Activity": {
        "values": [
            "CrossFit", "Cross Training", "Cycling", "Golf", "Gym & Training",
            "Hiking", "Hockey", "Hunting", "Racing", "Riding", "Running & Jogging",
            "Skateboarding", "Skiing", "Soccer", "Track & Field", "Walking",
            "Wrestling", "Not Specified",
        ],
        "strict": True,
        "multi": True,
        "normalize": {
            "Outdoor": "Hiking",  # "Outdoor" は eBay 非フィルタ値、Hiking に正規化
            "Camping": "Hiking",
            "Trail": "Hiking",
            "Trekking": "Hiking",
            "Bike": "Cycling",
            "Run": "Running & Jogging",
            "Walk": "Walking",
            "Ski": "Skiing",
            "Snowboard": "Skiing",
            "Training": "Gym & Training",
            "Does not apply": "Not Specified",
        },
    },
    "Pattern": {
        "values": ["Camouflage", "Geometric", "Solid", "Not Specified"],
        "strict": True,
        "normalize": {
            "Colorblock": "Geometric",
            "Color Block": "Geometric",
            "Plain": "Solid",
            "Camo": "Camouflage",
            "Does not apply": "Not Specified",
        },
    },
    "Department": {
        "values": ["Men", "Women", "Unisex Adults", "Boys", "Girls", "Not Specified"],
        "strict": True,
        "normalize": {"Does not apply": "Not Specified"},
    },
    "Size Type": {
        "values": ["Regular", "Big & Tall", "Not Specified"],
        "strict": True,
        "normalize": {"Does not apply": "Not Specified"},
    },
    "Size": {
        "values": ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "One Size"],
        "strict": True,
        "normalize": {"XXL": "2XL", "XXXL": "3XL", "Small": "S", "Medium": "M", "Large": "L"},
    },
    "Color": {
        "values": ["Beige", "Black", "Blue", "Brown", "Clear", "Gold", "Gray", "Green", "Ivory", "Multicolor", "Orange", "Pink", "Purple", "Red", "Silver", "White", "Yellow", "Not Specified"],
        "strict": True,
        "normalize": {"Olive": "Green", "Khaki": "Green", "Navy": "Blue", "Cream": "Ivory", "Tan": "Beige", "Charcoal": "Gray", "Does not apply": "Not Specified"},
    },
    "Theme": {
        "values": ["80s", "90s", "Anime", "Army", "Art", "Aztec", "Beach", "Biker", "City", "Classic", "College", "Colorful", "Countries", "Cowboy", "Designer", "Hippie", "Hipster", "Italian", "Korean", "Metal", "Motorcycle", "Nature", "Nautical", "Outdoor", "Preppy", "Punk", "Retro", "Rock", "Shell", "Ski", "Southwestern", "Sports", "Tribal", "USA", "Western", "Wedding"],
        "strict": True,
        "multi": True,
    },
    "Occasion": {
        "values": ["Business", "Casual", "Formal", "Party/Cocktail", "Travel", "Workwear", "Not Specified"],
        "strict": True,
        "normalize": {"Does not apply": "Not Specified"},
    },
    "Features": {
        "values": [
            "1/4 Zip", "All Seasons", "Belted", "Bodywarmer", "Breathable",
            "Collared", "Collarless", "Elastic Waist", "Full Zip", "Hooded",
            "Insulated", "Lightweight", "Limited Edition", "Lined",
            "Moisture Wicking", "Packable", "Padded", "Pockets", "Quick Dry",
            "Reflective", "Removable Hood", "Removable Lining", "Reversible",
            "Single-Breasted", "Soft Shell", "Stretch", "Taped Seams", "Thermal",
            "Transparent", "Waterproof", "Water Resistant", "Waxed", "Weathergear",
            "Windproof", "Wind-Resistant", "Zipped Pockets",
        ],
        "strict": True,
        "multi": True,
    },
    "Fit": {
        "values": ["Athletic", "Classic", "Regular", "Relaxed", "Slim"],
        "strict": True,
    },
    "Accents": {
        "values": ["Button", "Embroidered", "Fur Trim", "Glitter", "Logo", "Quilted", "Zipper", "Not Specified"],
        "strict": True,
        "multi": True,
        "normalize": {"Does not apply": "Not Specified"},
    },
    "Country/Region of Manufacture": {
        "values": [
            "Bangladesh", "Canada", "China", "Finland", "France", "Hong Kong",
            "Indonesia", "Japan", "Myanmar / Burma", "South Korea (Republic of Korea)",
            "Thailand", "Ukraine", "United Kingdom", "United States", "Vietnam",
            "Not Specified",
        ],
        "strict": True,
        "normalize": {"USA": "United States", "UK": "United Kingdom", "South Korea": "South Korea (Republic of Korea)", "Korea": "South Korea (Republic of Korea)", "Does not apply": "Not Specified"},
    },
    "Jacket/Coat Length": {
        "values": ["Short", "Mid-Length", "Long", "Not Specified"],
        "strict": True,
        "normalize": {"Does not apply": "Not Specified"},
    },
    "Garment Care": {
        "values": ["Dry Clean Only", "Hand Wash Only", "Machine Washable", "Not Specified"],
        "strict": True,
        "normalize": {"Does not apply": "Not Specified"},
    },
    "Vintage": {"values": ["Yes", "No"], "strict": True},
    "Handmade": {"values": ["Yes", "No", "Not Specified"], "strict": True, "normalize": {"Does not apply": "Not Specified"}},
}


# ============================================================================
# 正規化ヘルパー (whitelist_registry.py から物理コピー、独立性のため)
# ============================================================================
def _extract_integer(val: str) -> str:
    """'6+1' → '6' のような整数抽出"""
    m = re.match(r'^(\d+)', str(val).strip())
    return m.group(1) if m else ""


def _extract_year(val: str) -> str:
    """'1977' / '1977年' / 'c.1977' から 4桁西暦抽出"""
    m = re.search(r'(19[5-9]\d|20[0-2]\d)', str(val))
    return m.group(1) if m else ""


_NORMALIZE_FUNCS = {
    "extract_integer": _extract_integer,
    "extract_year": _extract_year,
}


# ============================================================================
# Montbell 専用 validator (whitelist_registry.py:996-1137 から物理コピー、
# WHITELISTS[category] 参照を MONTBELL_WHITELIST 直参照に書換)
# ============================================================================
def validate_and_normalize(specs: dict) -> tuple:
    """Montbell の item_specifics を検証・正規化.

    Args:
        specs: {field: value} の dict

    Returns:
        (normalized_specs, violations)
        violations: [(field, original_value, expected, reason), ...]

    Note:
        共通モジュール (whitelist_registry) には依存しない. MONTBELL_WHITELIST のみ参照.
    """
    rules = MONTBELL_WHITELIST
    normalized = dict(specs)
    violations = []

    for field, rule in rules.items():
        if field not in specs:
            continue
        val = specs[field]
        if not val or val == "":
            continue
        val_str = str(val).strip()

        # 0. max_length チェック (eBay 各フィールド文字数制限)
        max_len = rule.get("max_length")

        # 1. regex ルール (Montbell では未使用だが構造保全のため残す)
        if "regex" in rule:
            if "normalize_func" in rule:
                func = _NORMALIZE_FUNCS.get(rule["normalize_func"])
                if func:
                    normalized_val = func(val_str)
                    if normalized_val and normalized_val != val_str:
                        normalized[field] = normalized_val
                        val_str = normalized_val
            if not re.match(rule["regex"], val_str):
                violations.append((field, val, rule["regex"], "regex_mismatch"))
                continue
            continue

        # 2. multi=True → カンマ区切り分解検証
        if rule.get("multi"):
            parts = [p.strip() for p in val_str.split(",")]
            normalize_map = rule.get("normalize", {})
            accepted, rejected = [], []
            for p in parts:
                if not p:
                    continue
                normalized_p = normalize_map.get(p, p)
                if not normalized_p:
                    continue
                if "values" in rule:
                    if normalized_p in rule["values"]:
                        if normalized_p not in accepted:
                            accepted.append(normalized_p)
                    else:
                        rejected.append(p)
                        if not rule.get("strict"):
                            accepted.append(p)
                else:
                    accepted.append(normalized_p)
            joined = ", ".join(accepted)
            if max_len and len(joined) > max_len:
                trimmed = []
                for item in accepted:
                    candidate = ", ".join(trimmed + [item])
                    if len(candidate) <= max_len:
                        trimmed.append(item)
                joined = ", ".join(trimmed)
                violations.append((
                    field, val,
                    f"max_length={max_len}文字以内",
                    f"{len(', '.join(accepted))}文字超過 → '{joined}' に短縮",
                ))
            normalized[field] = joined
            if rejected and rule.get("strict"):
                violations.append((
                    field, val,
                    f"有効値: {rule['values']}",
                    f"無効な値含む: {rejected}",
                ))
            continue

        # 3. 単一値
        normalize_map = rule.get("normalize", {})
        normalized_val = normalize_map.get(val_str, val_str)
        if "values" in rule:
            if normalized_val not in rule["values"]:
                if rule.get("strict"):
                    violations.append((
                        field, val,
                        f"有効値: {rule['values']}",
                        "not_in_whitelist",
                    ))
                normalized[field] = normalized_val  # 正規化は試みる
            else:
                normalized[field] = normalized_val
        else:
            normalized[field] = normalized_val

        # max_length チェック (単一値・values 無し系も対象)
        if max_len and len(str(normalized.get(field, ""))) > max_len:
            current = str(normalized.get(field, ""))
            violations.append((
                field, val,
                f"max_length={max_len}文字以内",
                f"{len(current)}文字超過",
            ))

    return normalized, violations


# ============================================================================
# Claude API 再リクエスト用フィードバック生成 (whitelist_registry.py から物理コピー)
# ============================================================================
def build_retry_feedback(violations: list) -> str:
    """違反リストから Claude 向け再指示テキストを生成"""
    if not violations:
        return ""
    lines = [
        "前回の出力に以下の Item Specifics 違反がありました。eBay 公式フィルタ値に修正して再出力してください:",
        "",
    ]
    for field, orig, expected, reason in violations:
        lines.append(f"【{field}】")
        lines.append(f"  ❌ 出力値: \"{orig}\"")
        lines.append(f"  ✅ {expected}")
        lines.append(f"  理由: {reason}")
        lines.append("")
    lines.append("上記を修正し、他のフィールドはそのまま維持して JSON 形式で再出力してください。")
    return "\n".join(lines)


# ============================================================================
# スタンドアロン動作確認
# ============================================================================
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # テスト 1: 全部正規値
    test_ok = {
        "Brand": "montbell",
        "Outer Shell Material": "Nylon",
        "Insulation Material": "Not Specified",
        "Fabric Type": "Softshell",
    }
    norm, viol = validate_and_normalize(test_ok)
    print("=== test_ok ===")
    print("violations:", viol)
    assert viol == [], "全正規値は violations=[] であるべき"

    # テスト 2: Does not apply → Not Specified に正規化
    test_normalize = {
        "Insulation Material": "Does not apply",
        "Fabric Type": "Nylon",  # → Not Specified に正規化
    }
    norm, viol = validate_and_normalize(test_normalize)
    print("\n=== test_normalize ===")
    print("normalized:", norm)
    print("violations:", viol)
    assert norm["Insulation Material"] == "Not Specified"
    assert norm["Fabric Type"] == "Not Specified"

    # テスト 3: whitelist 違反
    test_violation = {
        "Brand": "Patagonia",  # whitelist 外
    }
    norm, viol = validate_and_normalize(test_violation)
    print("\n=== test_violation ===")
    print("violations:", viol)
    assert len(viol) == 1, "Patagonia は違反検出されるべき"

    print("\n✅ All standalone tests passed.")
