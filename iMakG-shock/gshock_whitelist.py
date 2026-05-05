"""G-shock カテゴリ専用 whitelist + validator (2026-05-05 専門化第 2 弾)

設計思想:
  共有 whitelist_registry.py から G-shock を切出し、完全独立。
  Montbell (2026-05-03) と同じカテゴリ専門化原則。
  - 商品を極めるには専門化が必要 (memory: category_specialization_principle)
  - 共有は心理的ブレーキ + 構造の不自由を生む
  - 修正連鎖を物理的にゼロにする (memory: no_modification_chain)

依存:
  外部依存ゼロ (re のみ)。共通モジュール whitelist_registry にも依存しない。

連携:
  iMakCatalog (gshock_lookup) で型番から公式 specs 取得 → 本 whitelist で eBay 公式値検証.
  catalog の specs は基本的に whitelist 適合済 (公式由来) だが、念のため最終ゲートとして使う.

eBay 公式フィルタ値の根拠:
  whitelist_registry.py から物理コピー (2026-05-05 切出時点の値). 22 フィールド.
"""
import re


# ============================================================================
# G-shock whitelist (eBay 公式フィルタ値、whitelist_registry.py から物理コピー)
# ============================================================================
GSHOCK_WHITELIST = {
    "Brand": {
        "values": ["Casio", "G-SHOCK", "Baby-G"],
        "strict": True,
    },
    "Type": {"values": ["Wristwatch", "Pocket Watch"], "strict": True},
    "Department": {
        "values": ["Men", "Women", "Unisex Adults", "Boys", "Girls", "Teens", "Unisex Kids"],
        "strict": True,
    },
    "Style": {
        "values": ["Casual", "Classic", "Diver", "Dress/Formal", "Luxury", "Military", "Pilot/Aviator", "Skeleton", "Sport"],
        "strict": True,
        "normalize": {"Sports": "Sport"},
    },
    "Display": {
        "values": ["Analog", "Digital", "Analog & Digital"],
        "strict": True,
    },
    "Bezel Type": {
        "values": [
            "12-Hour", "24-Hour", "Bidirectional Rotating", "Compass",
            "Countdown", "Count-Up/Dive", "Decimal", "Diamond",
            "Engine-Turned", "Fixed", "Fluted", "Gem-Set", "GMT/Dual Time",
            "Pulsometer", "Ring Command", "Slide Rule", "Smooth",
            "Tachymeter", "Telemeter", "Unidirectional Rotating",
        ],
        "strict": True,
    },
    "Dial Pattern": {
        "values": [
            "Animal Print", "Brick", "Bullseye", "Camouflage", "Celestial",
            "Checkered", "Concentric", "Crosshair", "Diamond Pattern",
            "Floral", "Geometric", "Graffiti", "Guilloche", "Hearts",
            "Honeycomb", "Logo", "Mosaic", "Mother of Pearl", "Ocean Wave",
            "Skeleton", "Sunburst", "Wood Grain",
        ],
        "strict": True,
    },
    "Band Material": {
        "values": [
            "Alloy", "Aluminum", "Aramid Fiber", "Brass", "Bronze", "Canvas",
            "Ceramic", "Denim", "Faux Leather", "Gold Filled", "Gold Plated",
            "Leather", "Metal", "Nylon", "Plastic", "Polyamide",
            "Polycarbonate", "Polyurethane", "PVC", "Resin", "Rose Gold",
            "Rubber", "Silicone", "Silver", "Stainless Steel",
            "Sterling Silver", "Titanium", "Wood",
        ],
        "strict": True,
        "normalize": {"Carbon Fiber, Resin": "Resin", "Carbon Fiber": "Resin", "Fabric": "Canvas"},
    },
    "Case Material": {
        "values": [
            "Aluminum", "Brass", "Bronze", "Carbon Fiber", "Ceramic",
            "Cobalt Alloy", "Crystal", "Gold Filled", "Gold Plated",
            "Plastic", "Platinum", "Polymer", "Resin", "Rose Gold",
            "Rubber", "Sapphire", "Silicone", "Silver", "Stainless Steel",
            "Sterling Silver", "Stone", "Tantalum", "Titanium", "White Gold",
            "Wood", "Yellow Gold",
        ],
        "strict": True,
    },
    "Features": {
        # multi=True. eBay 公式フィルタ値のうち主要なもの
        "values": [
            "12-Hour Dial", "24-Hour Dial", "Acrylic Crystal", "Alarm",
            "Altimeter", "Annual Calendar", "Atomic/Radio Controlled",
            "Backlight", "Bluetooth", "Calculator", "Chronograph",
            "Chronometer", "Date Indicator", "Day/Date", "Day Indicator",
            "Day/Night Indicator", "GPS", "Heart Rate Monitor", "LCD Display",
            "LED Display", "Limited Edition", "Luminous Dial", "Luminous Hands",
            "Magnetic-Resistant", "Mineral Crystal", "Moon Phase",
            "Multi-Dial", "Multifunction", "Sapphire Crystal",
            "Scratch-Resistant", "Shock-Resistant", "Solar Powered",
            "Splash Proof", "Stop-Seconds Function", "Thermometer", "Timer",
            "Water-Resistant", "World Time",
        ],
        "strict": True,
        "multi": True,
        "normalize": {
            "Shock Resist": "Shock-Resistant",
            "Tough Solar": "Solar Powered",
            "Multiband 6": "Atomic/Radio Controlled",
            "Magnetic Resist": "Magnetic-Resistant",
            "Stopwatch": "Chronograph",
            "Moon Data": "Moon Phase",
            "Carbon Core Guard": "",  # eBay 非フィルタ値、削除
            "Activity Tracker": "",
            "Compass": "",
            "Barometer": "",
            "Tide Graph": "",
            "Sunrise/Sunset": "",
            "Vibration Alert": "",
            "Flash Alert": "",
        },
    },
    "Movement": {
        "values": ["Mechanical (Automatic)", "Mechanical (Manual)", "Quartz"],
        "strict": True,
        "normalize": {
            "Solar Quartz": "Quartz",
            "Radio Controlled Quartz": "Quartz",
            "Auto": "Mechanical (Automatic)",
            "Manual": "Mechanical (Manual)",
        },
    },
    "Watch Shape": {
        "values": ["Asymmetrical", "Cushion", "Hexagon", "Octagon", "Oval", "Rectangle", "Round", "Square", "Tonneau/Barrel"],
        "strict": True,
    },
    "Case Shape": {
        "values": ["Asymmetrical", "Cushion", "Hexagon", "Octagon", "Oval", "Rectangle", "Round", "Square", "Tonneau/Barrel"],
        "strict": True,
    },
    "Band/Strap": {
        "values": ["Bangle", "Bracelet", "Bund Strap", "Milanese/Mesh Band", "NATO Strap", "One-Piece Strap", "Two-Piece Strap", "Wrap-Around Strap"],
        "strict": True,
    },
    "Closure": {
        "values": ["Buckle", "Butterfly Clasp", "Deployant", "Double-Locking Fold-Over Clasp", "Fold-Over Push-Button Deployant", "Hidden Fold Clasp", "Jewelry Clasp", "Push-Button Deployant", "Tri-Fold Clasp"],
        "strict": True,
    },
    "Caseback": {
        "values": ["Exhibition", "Screwback", "Snap", "Solid"],
        "strict": True,
    },
    "Indices": {
        "values": ["Arabic Numerals", "Arrow Markers", "Baton Indexes", "Breguet Numerals", "Dagger/Dauphine Indexes", "Diamond Markers", "No Hour Marks", "Roman Numerals", "Round Indexes", "Square Indexes", "Stick Indexes"],
        "strict": True,
    },
    "Customized": {"values": ["Yes", "No"], "strict": True},
    "Vintage": {"values": ["Yes", "No"], "strict": True},
    "Handmade": {"values": ["Yes", "No"], "strict": True},
    "With Original Box/Packaging": {"values": ["Yes", "No"], "strict": True},
    "With Papers": {"values": ["Yes", "No"], "strict": True},
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
# G-shock 専用 validator (whitelist_registry.py から物理コピー、
# WHITELISTS[category] 参照を GSHOCK_WHITELIST 直参照に書換)
# ============================================================================
def validate_and_normalize(specs: dict) -> tuple:
    """G-shock の item_specifics を検証・正規化.

    Args:
        specs: {field: value} の dict

    Returns:
        (normalized_specs, violations)
        violations: [(field, original_value, expected, reason), ...]

    Note:
        共通モジュール (whitelist_registry) には依存しない. GSHOCK_WHITELIST のみ参照.
    """
    rules = GSHOCK_WHITELIST
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

        # 1. regex ルール (G-shock では未使用だが構造保全のため残す)
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
                normalized[field] = normalized_val
            else:
                normalized[field] = normalized_val
        else:
            normalized[field] = normalized_val

        # max_length チェック
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
        "Brand": "Casio",
        "Type": "Wristwatch",
        "Department": "Men",
        "Movement": "Quartz",
        "Display": "Digital",
    }
    norm, viol = validate_and_normalize(test_ok)
    print("=== test_ok ===")
    print("violations:", viol)
    assert viol == [], "全正規値は violations=[] であるべき"

    # テスト 2: 正規化
    test_normalize = {
        "Movement": "Solar Quartz",   # → "Quartz"
        "Style":    "Sports",         # → "Sport"
        "Band Material": "Carbon Fiber",  # → "Resin"
    }
    norm, viol = validate_and_normalize(test_normalize)
    print("\n=== test_normalize ===")
    print("normalized:", norm)
    assert norm["Movement"] == "Quartz"
    assert norm["Style"] == "Sport"
    assert norm["Band Material"] == "Resin"

    # テスト 3: whitelist 違反
    test_violation = {
        "Brand": "Patagonia",  # whitelist 外
    }
    norm, viol = validate_and_normalize(test_violation)
    print("\n=== test_violation ===")
    print("violations:", viol)
    assert len(viol) == 1, "Patagonia は違反検出されるべき"

    print("\n✅ All standalone tests passed.")
