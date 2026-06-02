#!/usr/bin/env python3
"""
iMak Trading Japan - Free Shipping 統合 post-processor

## 目的
各 listing script (psa_to_csv.py / gshock_to_csv.py / ichibankuji_to_csv.py /
mercari系/workman_listing.py) の出力 CSV を、Free Shipping 用に変換する。

## 設計原則 (memory: no_modification_chain)
- 既存 listing scripts は **改造しない** (= 修正連鎖の起点回避)
- post-processor 1 ファイルで全 6 商材を統一処理
- 不具合発覚時 = post-processor disable で旧 pipeline に即戻し可能

## 変換ルール
- 各 row の StartPrice を `INT(old + DDP) + 0.98` に置換 (DDP は価格帯逆引き)
- 各 row の ShippingProfileName を "Free" (= global.yaml `free_shipping_profile`) に置換
- 既に Free Shipping (= ShippingProfile が "Free" 等) の row は skip (= idempotent)

## 使い方

### CLI
    python freeshipping_postprocess.py input.csv [output.csv]
    # output 省略時は input_free.csv

### スクリプト内で呼出し (各 listing script の末尾に 1 行追加)
    from freeshipping_postprocess import transform_csv_to_freeshipping
    transform_csv_to_freeshipping(output_csv_path)
"""
import csv
import sys
from pathlib import Path

# 同 dir の listing_common を参照
sys.path.insert(0, str(Path(__file__).resolve().parent))
from listing_common import (
    compute_free_shipping_price,
    get_free_shipping_profile_name,
    is_free_shipping_mode,
)


# eBay CSV の price/shipping カラム名は script により asterisk 有無 が異なるため両方サポート
PRICE_KEYS = ("*StartPrice", "StartPrice")
SHIP_KEYS = ("ShippingProfileName", "*ShippingProfileName")
LOCATION_KEYS = ("*Location", "Location")
LOCATION_VALUE = "Osaka"  # eBay UI は Country を自動付加するので City のみ (2026-05-18 重複回避)
# Variation listing 判定 (Relationship 列があれば variation)
VARIATION_KEYS = ("Relationship",)


def _find_key(row: dict, candidates: tuple) -> str:
    """row dict から候補キーのうち最初に存在するものを返す。なければ空文字。"""
    for k in candidates:
        if k in row:
            return k
    return ""


def transform_row(row: dict, free_profile: str) -> tuple:
    """1 row を Free Shipping 用に変換。
    Returns: (modified_row, changed: bool, reason: str)
    """
    price_key = _find_key(row, PRICE_KEYS)
    ship_key = _find_key(row, SHIP_KEYS)
    if not price_key:
        return row, False, "no_price_key"

    # 既に Free profile なら skip (idempotent)
    if ship_key and row.get(ship_key, "").strip().lower() == free_profile.lower():
        return row, False, "already_free"

    # price 取得
    try:
        old_price = float(row[price_key])
    except (ValueError, TypeError):
        return row, False, "invalid_price"
    if old_price <= 0:
        # Variation sub-row (master のみ price あり) は skip
        return row, False, "zero_price"

    # 2026-05-18 根本修正後: pricing_engine が既に bundled price (= item + DDP) を出力するため、
    # post-processor は price を触らない (= 二重加算回避)。
    # ShippingProfileName と Location のみ統一。
    if ship_key:
        row[ship_key] = free_profile
    loc_key = _find_key(row, LOCATION_KEYS)
    if loc_key:
        row[loc_key] = LOCATION_VALUE
    return row, True, "ship+loc only"


def transform_csv_to_freeshipping(input_path, output_path=None) -> str:
    """CSV を Free Shipping 用に変換して書き出す。

    Args:
      input_path: 入力 CSV path
      output_path: 出力 path (省略時 input_free.csv)

    Returns:
      output_path (str)
    """
    # V6 mode は Policy 名 (DDP-X-PYY) を保持するため post-process 不要
    import config_loader as _cfg
    if _cfg.is_v6_pricing_enabled():
        print("[INFO] v6_pricing.enabled=True → Free 強制置換 skip (Policy 名保持)")
        return str(input_path)
    if not is_free_shipping_mode():
        print("[INFO] free_shipping_mode=False、変換 skip")
        return str(input_path)

    in_p = Path(input_path)
    if output_path is None:
        output_path = in_p.with_name(in_p.stem + "_free.csv")
    out_p = Path(output_path)

    free_profile = get_free_shipping_profile_name()

    rows = []
    with in_p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            print(f"[ERROR] 入力 CSV にヘッダなし: {input_path}")
            return str(input_path)
        for row in reader:
            rows.append(row)

    n_changed = 0
    n_skipped = 0
    n_already = 0
    for row in rows:
        _, changed, reason = transform_row(row, free_profile)
        if changed:
            n_changed += 1
        elif reason == "already_free":
            n_already += 1
        else:
            n_skipped += 1

    # 書き出し (eBay 規約: csv.QUOTE_NONNUMERIC + utf-8 no BOM)
    with out_p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC,
                                 extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"[OK] {in_p.name} -> {out_p.name}: "
          f"変換 {n_changed} / 既Free {n_already} / skip {n_skipped} / 計 {len(rows)}")
    return str(out_p)


# ===================================================================
# Smoke tests
# ===================================================================
def _smoke():
    import tempfile, io
    print("Smoke testing freeshipping_postprocess...")

    # 1. transform_row: 根本修正後 (= pricing_engine が bundled price 出力するので post-processor は price 触らず)
    free_profile = "Free"
    row = {"*StartPrice": "152.98", "ShippingProfileName": "DDP-100-200", "*Location": "Japan", "Other": "x"}
    new_row, changed, reason = transform_row(row.copy(), free_profile)
    assert changed
    assert new_row["*StartPrice"] == "152.98", f"price 不変期待: {new_row['*StartPrice']}"  # 根本修正後: price 触らず
    assert new_row["ShippingProfileName"] == "Free"
    assert new_row["*Location"] == "Osaka, Japan", new_row["*Location"]
    print(f"  [OK] price 据置 (${new_row['*StartPrice']}), Ship→Free, Location→{new_row['*Location']}")

    # 2. 既に Free なら skip
    row2 = {"*StartPrice": "65.98", "ShippingProfileName": "Free"}
    new_row2, changed2, reason2 = transform_row(row2.copy(), free_profile)
    assert not changed2, f"Should skip Free, but changed={changed2}, reason={reason2}"
    print(f"  [OK] already Free → skip ({reason2})")

    # 3. zero price (variation sub-row) skip
    row3 = {"*StartPrice": "0", "ShippingProfileName": "DDP-40-60"}
    new_row3, changed3, reason3 = transform_row(row3.copy(), free_profile)
    assert not changed3
    print(f"  [OK] zero price → skip ({reason3})")

    # 4. 根本修正後: price は触らない (= pricing_engine が bundled 出力)
    for base in [38, 45, 80, 150, 250, 350]:
        r = {"*StartPrice": str(base), "ShippingProfileName": "DDP-x"}
        nr, c, _ = transform_row(r.copy(), free_profile)
        assert nr["*StartPrice"] == str(base), f"price 不変期待: {nr['*StartPrice']}"
    print(f"  [OK] price 据置 (= pricing_engine が bundled 出力する前提)")

    # 5. CSV 一括変換 e2e (price 据置 + Ship/Loc 変換)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False,
                                       encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ItemID", "*StartPrice", "ShippingProfileName", "*Location"],
                           quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        w.writerow({"ItemID": "X1", "*StartPrice": "152.98", "ShippingProfileName": "100-200", "*Location": "Japan"})
        w.writerow({"ItemID": "X2", "*StartPrice": "203.98", "ShippingProfileName": "200-300", "*Location": "Japan"})
        in_path = f.name
    out_path = transform_csv_to_freeshipping(in_path)
    with open(out_path, "r", encoding="utf-8") as f:
        out_rows = list(csv.DictReader(f))
    assert out_rows[0]["*StartPrice"] == "152.98"   # 据置
    assert out_rows[0]["ShippingProfileName"] == "Free"
    assert out_rows[0]["*Location"] == "Osaka, Japan"
    assert out_rows[1]["*StartPrice"] == "203.98"   # 据置
    assert out_rows[1]["ShippingProfileName"] == "Free"
    print(f"  [OK] e2e: price 据置 + Ship→Free + Location→Osaka,Japan")
    Path(in_path).unlink()
    Path(out_path).unlink()

    print("✅ All smoke tests passed.")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--smoke":
        _smoke()
    elif len(sys.argv) >= 2:
        in_path = sys.argv[1]
        out_path = sys.argv[2] if len(sys.argv) > 2 else None
        transform_csv_to_freeshipping(in_path, out_path)
    else:
        print("Usage: python freeshipping_postprocess.py input.csv [output.csv]")
        print("       python freeshipping_postprocess.py --smoke")
        sys.exit(1)
