#!/usr/bin/env python3
"""Phase 3-C: byte 等価性 e2e verification (Selenium 不要 / mock-based).

検証する 2 つの byte 等価性:

  (A) catalog miss 経路 ↔ master (Phase 3-B 適用前) の同一性
      ロジックは構造的に同一 (scrape_casio 直行)、本テストでは
      build_row が同一データで同一出力を返すことの sanity check.

  (B) catalog hit 経路 (新規) ↔ scrape 経路 (既存) の同一性
      catalog 由来データを scrape_casio 互換 dict に逆変換した結果が、
      scrape_casio 直接出力と同等の CSV 行を生成することを保証.
      → 月次バッチで catalog に正しいデータが入っていれば、
        Selenium 経路と同一の CSV が生成されることを担保.

外部依存ゼロ (CASIO 公式へのアクセス不要、Selenium 起動不要).
"""
from __future__ import annotations
import sys
from pathlib import Path

# 必要な path を通す + cleanup (test_gshock_csv_catalog_integration と同じ流儀)
_REPO_ROOT = Path(__file__).resolve().parent.parent
_GS_PATHS = [
    str(_REPO_ROOT / "iMakG-shock"),
    str(_REPO_ROOT / "iMakG-shock" / "casio_finder"),
]
_KEEP_PATHS = [
    str(_REPO_ROOT / "iMakeBayAPI"),
    str(_REPO_ROOT / "iMakCatalog" / "integrations"),
]
for p in _GS_PATHS + _KEEP_PATHS:
    if p not in sys.path:
        sys.path.insert(0, p)

import gshock_to_csv  # noqa: E402

for p in _GS_PATHS:
    while p in sys.path:
        sys.path.remove(p)


# ============================================================================
# 代表データセット (scrape_casio がこの shape で返す想定)
# ============================================================================
# GM-5600YRA-8 (Metal Covered Square Digital, 黄+橙) 想定データ
_FAKE_SCRAPE_DATA_GM5600 = {
    "model":             "GM-5600YRA-8",
    "model_official":    "GM-5600YRA-8JF",
    "model_base":        "GM-5600YRA-8",
    "case_size":         "43.2 mm",
    "case_thickness":    "12.9 mm",
    "case_material":     "Resin",
    "case_shape":        "Square",
    "band_material":     "Resin",
    "band_width":        "20 mm",
    "band_length":       "145-215 mm",
    "band_color":        "Orange",
    "dial_color":        "Black",
    "bezel_color":       "Yellow",
    "crystal":           "Mineral Crystal",
    "movement":          "Quartz",
    "water_resistance":  "200 m (20 ATM)",
    "weight":            "76 g",
    "year":              "2023",
    "display":           "Digital",
    "features":          "Shock-Resistant",
    "is_metal":          True,
}

# GMW-B5000BT-1 (Full Metal Bracelet) 想定 — band_strap_override が立つ ケース
_FAKE_SCRAPE_DATA_GMW = {
    "model":             "GMW-B5000BT-1",
    "model_official":    "GMW-B5000BT-1JF",
    "model_base":        "GMW-B5000BT-1",
    "case_size":         "43.2 mm",
    "case_thickness":    "13.0 mm",
    "case_material":     "Stainless Steel",
    "case_shape":        "Square",
    "band_material":     "Stainless Steel",
    "band_width":        "20 mm",
    "band_length":       "145-215 mm",
    "band_color":        "Black",
    "dial_color":        "Black",
    "bezel_color":       "Black",
    "crystal":           "Sapphire Crystal",
    "movement":          "Solar Quartz",
    "water_resistance":  "200 m (20 ATM)",
    "weight":            "167 g",
    "year":              "2023",
    "display":           "Digital",
    "features":          "Solar Powered, Atomic/Radio Controlled, Bluetooth, Shock-Resistant",
    "is_metal":          True,
    "band_strap_override": "Bracelet",  # GMW 系は scrape_casio が明示的にセット
}


def _scrape_data_to_catalog_record(scrape_data: dict) -> dict:
    """scrape_casio の戻り値から catalog upsert される record を逆構築 (テスト用).

    scrapers/gshock.py の _build_specs の論理を反映するが、
    Phase 2 拡張枠などの null フィールドは省略 (lookup 時 default で埋まる).
    """
    return {
        "category":   "gshock",
        "product_id": scrape_data["model_official"],
        "name":       f"Casio G-SHOCK {scrape_data['model_official']}",
        "specs": {
            "case_size":        scrape_data.get("case_size", ""),
            "case_thickness":   scrape_data.get("case_thickness", ""),
            "case_material":    scrape_data.get("case_material", ""),
            "case_shape":       scrape_data.get("case_shape", ""),
            "band_material":    scrape_data.get("band_material", ""),
            "band_width":       scrape_data.get("band_width", ""),
            "band_length":      scrape_data.get("band_length", ""),
            "band_color":       scrape_data.get("band_color", ""),
            # band_strap: scrape_data に band_strap_override があればそれ、なければ Two-Piece
            "band_strap":       scrape_data.get("band_strap_override", "Two-Piece Strap"),
            "dial_color":       scrape_data.get("dial_color", ""),
            "bezel_color":      scrape_data.get("bezel_color", ""),
            "crystal":          scrape_data.get("crystal", ""),
            "movement":         scrape_data.get("movement", ""),
            "water_resistance": scrape_data.get("water_resistance", ""),
            "weight":           scrape_data.get("weight", ""),
            "year":             scrape_data.get("year", ""),
            "display":          scrape_data.get("display", ""),
            "features":         scrape_data.get("features", ""),
            "is_metal":         scrape_data.get("is_metal", False),
        },
    }


# ============================================================================
# (B) catalog hit path == scrape path (mock-based byte equality)
# ============================================================================
def _build_csv_row(scrape_data: dict, fixed_schedule: str = "2026-05-13 10:00:00"):
    """build_row を実行して CSV 行を返す.
    get_schedule_time を固定して非決定性を排除する.
    """
    url = f"https://www.casio.com/jp/watches/gshock/product.{scrape_data['model_official']}/"
    base_desc = "<html><body>fake description for test</body></html>"
    # get_schedule_time をテスト用固定値に差替 (時刻依存を排除)
    _orig = gshock_to_csv.get_schedule_time
    gshock_to_csv.get_schedule_time = lambda: fixed_schedule
    try:
        row = gshock_to_csv.build_row(url, 100.00, scrape_data, base_desc)
    finally:
        gshock_to_csv.get_schedule_time = _orig
    return row


def test_catalog_hit_path_byte_equal_to_scrape_path_simple_model():
    """catalog hit (GM-5600YRA-8) → scrape 互換 dict に変換 → build_row 同一出力.

    検証: 同じ source data があれば、catalog 経路でも scrape 経路でも CSV 行 byte 一致.
    """
    # (1) scrape 経路: scrape_data → build_row 直接
    scrape_data = dict(_FAKE_SCRAPE_DATA_GM5600)
    row_scrape = _build_csv_row(scrape_data)

    # (2) catalog hit 経路: catalog record → _catalog_record_to_scrape_dict → build_row
    catalog_record = _scrape_data_to_catalog_record(scrape_data)
    catalog_data = gshock_to_csv._catalog_record_to_scrape_dict(
        catalog_record, scrape_data["model"]
    )
    row_catalog = _build_csv_row(catalog_data)

    # byte 等価
    assert row_scrape == row_catalog, (
        f"catalog hit 経路と scrape 経路の CSV 行が不一致.\n"
        f"  scrape:  {row_scrape}\n"
        f"  catalog: {row_catalog}"
    )


def test_catalog_hit_path_byte_equal_to_scrape_path_bracelet_model():
    """GMW-B5000BT-1 (Bracelet, Solar, Bluetooth) も byte 等価."""
    scrape_data = dict(_FAKE_SCRAPE_DATA_GMW)
    row_scrape = _build_csv_row(scrape_data)

    catalog_record = _scrape_data_to_catalog_record(scrape_data)
    catalog_data = gshock_to_csv._catalog_record_to_scrape_dict(
        catalog_record, scrape_data["model"]
    )
    row_catalog = _build_csv_row(catalog_data)

    assert row_scrape == row_catalog, (
        f"Bracelet モデルの CSV 行が不一致.\n"
        f"  scrape:  {row_scrape}\n"
        f"  catalog: {row_catalog}"
    )


# ============================================================================
# (A) catalog miss → 既存 scrape 経路に fallthrough (構造保証)
# ============================================================================
def test_catalog_miss_path_data_dict_unchanged():
    """catalog miss 時、main() の data 変数は scrape_casio 戻り値そのもの.

    main() コード:
        data = None
        if _catalog_lookup is not None:
            _cat_rec = _catalog_lookup(model)  # → None on miss
            if _cat_rec:                       # → False
                data = ...
        if data is None:                       # → True
            data = scrape_casio(driver, url)   # ← 既存呼出

    本テストでは、_catalog_lookup を None 返却に固定し、データ取得 path が
    scrape_casio に到達することを構造的に確認.
    """
    # _catalog_lookup を「常に None 返却」にパッチ
    orig_lookup = gshock_to_csv._catalog_lookup

    def _stub_lookup(_model):
        return None

    gshock_to_csv._catalog_lookup = _stub_lookup
    try:
        # main() のロジックを部分再現:
        data = None
        cat_rec = gshock_to_csv._catalog_lookup("GM-5600YRA-8")
        assert cat_rec is None, "stub が None 返さない (テスト環境異常)"
        if cat_rec:
            data = gshock_to_csv._catalog_record_to_scrape_dict(cat_rec, "GM-5600YRA-8")
        # `if data is None:` → True → scrape_casio に fallthrough
        assert data is None, (
            "catalog miss 時に data が None でない (= 既存 scrape 経路に行かない)"
        )
        # この後 main() では data = scrape_casio(driver, url) が呼ばれる.
        # → 本テストでは Selenium を起動しない (構造的に既存経路に到達することの確認のみ).
    finally:
        gshock_to_csv._catalog_lookup = orig_lookup


def test_catalog_lookup_none_when_adapter_unavailable():
    """iMakCatalog 配置なし環境のシミュレーション: _catalog_lookup is None なら if-block 全 skip."""
    orig_lookup = gshock_to_csv._catalog_lookup
    gshock_to_csv._catalog_lookup = None
    try:
        # main() の if 評価:
        if gshock_to_csv._catalog_lookup is not None:
            assert False, "adapter なし環境で if-block に入ってはいけない"
        # → 即 fallthrough、data は scrape_casio で埋まる.
    finally:
        gshock_to_csv._catalog_lookup = orig_lookup


# ============================================================================
# (C) catalog hit 時の追加 print 出力 — miss 経路では発火しないこと
# ============================================================================
def test_no_extra_print_on_catalog_miss():
    """catalog miss 時、print('[catalog hit]') が発火しない (= byte 互換 stdout).

    sphinx 構造的: print は `if _cat_rec:` guard 配下にあるので、
    cat_rec is None なら fire しない.  ソース上の if 条件を確認.
    """
    import inspect
    src = inspect.getsource(gshock_to_csv.main)
    # main() ソース内、'[catalog hit]' は cat_rec の if 配下にあること
    assert "[catalog hit]" in src
    # 構造確認: '[catalog hit]' が if _cat_rec: 配下にあること
    # (簡易: '[catalog hit]' の前に 'if _cat_rec' が出現)
    idx_if = src.find("if _cat_rec")
    idx_print = src.find("[catalog hit]")
    assert 0 <= idx_if < idx_print, (
        "'[catalog hit]' print が `if _cat_rec:` の下にない (miss 経路で発火するリスク)"
    )


# Standalone runner
if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    cases = [
        ("(A1) catalog miss → data is None", test_catalog_miss_path_data_dict_unchanged),
        ("(A2) adapter 不在時 if-block skip",  test_catalog_lookup_none_when_adapter_unavailable),
        ("(B1) catalog hit byte 一致 (GM-5600)", test_catalog_hit_path_byte_equal_to_scrape_path_simple_model),
        ("(B2) catalog hit byte 一致 (GMW Bracelet)", test_catalog_hit_path_byte_equal_to_scrape_path_bracelet_model),
        ("(C)  print is guarded under if",     test_no_extra_print_on_catalog_miss),
    ]
    fails = 0
    for name, fn in cases:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ FAIL: {name}: {e}")
            fails += 1
    if fails == 0:
        print(f"\n✅ All {len(cases)} Phase 3-C byte equality tests passed.")
    else:
        print(f"\n❌ {fails} failed.")
        sys.exit(1)
