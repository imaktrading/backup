#!/usr/bin/env python3
"""
iMak Trading Japan - スモークテスト
SSOT化と共通基盤が壊れていないか軽く確認する非破壊テスト。
live API/Seleniumは触らない。importとロジックのみ検証。

使い方:
  cd iMakeBayAPI
  python smoke_test.py
"""
import sys, os, io

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

def test(name, fn):
    try:
        fn()
        print(f"  ✅ {name}")
        return True
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        return False


def test_profit_params():
    from profit_params import _load, get_category_params, compute_min_price_usd, get_net_ratio
    p = _load()
    # 想定ソース: gsheet / gsheet/cache / excel (fallbackは異常)
    src = p["source"]
    assert src.startswith(("gsheet", "excel")), f"パラメータ読込失敗 source={src}"
    assert len(p["categories"]) >= 10
    for cat in ["TCG(PSA10)", "G-SHOCK", "Tシャツ(UT)", "Montbell(ジャケット)", "一番くじ"]:
        params = get_category_params(cat)
        assert params is not None, f"カテゴリ不在: {cat}"
        assert 0 < params["fvf"] < 0.3, f"{cat} FVF異常: {params['fvf']}"
        assert 0 < params["shipping_jpy"] < 10000, f"{cat} 送料異常: {params['shipping_jpy']}"
        net = get_net_ratio(cat)
        assert 0.3 < net < 0.9, f"{cat} net異常: {net}"
        mp = compute_min_price_usd(5000, cat)
        assert 10 < mp < 500, f"{cat} min_price異常: {mp}"


def test_listing_core():
    from listing_core import get_csv_output_path, load_keyword_pdf, CSV_OUTPUT_DIR
    assert CSV_OUTPUT_DIR.exists()
    path = get_csv_output_path("smoke_test", "test")
    assert "csv_output" in path.replace("\\", "/")
    assert "smoke_test" in path
    # PDFは読めるか
    for proj in ["tcg", "gshock", "ichibankuji", "tshirt", "montbell", "porter", "tomica", "fishing"]:
        kws = load_keyword_pdf(proj, top_n=3)
        assert len(kws) > 0, f"{proj} PDF読込失敗"
        # rank 1 が重複しないか
        ranks = [k["rank"] for k in kws]
        assert len(set(ranks)) == len(ranks), f"{proj} rank重複: {ranks}"


def test_script_imports():
    """各listing script が import できるか"""
    sys.path.insert(0, HERE)
    projects = {
        "iMakTCG": ["psa_to_csv", "check_csv"],
        "iMakG-shock": ["gshock_to_csv", "check_csv"],
        "iMak_ichibankuji": ["ichibankuji_to_csv", "check_csv"],
        "iMakMercari": ["tshirt_listing", "montbell_listing", "mercari_to_ebay_csv", "mercari_scout", "check_csv"],
    }
    for folder, mods in projects.items():
        proj_dir = os.path.join(ROOT, folder)
        if proj_dir not in sys.path:
            sys.path.insert(0, proj_dir)
        for mod in mods:
            if mod in sys.modules:
                del sys.modules[mod]
            __import__(mod)


def main():
    print("=== iMak Trading Japan スモークテスト ===\n")
    results = []
    print("[1] profit_params SSOT")
    results.append(test("カテゴリ読込 + 価格計算", test_profit_params))
    print("\n[2] listing_core")
    results.append(test("CSV出力パス + PDFキーワード読込", test_listing_core))
    print("\n[3] 各プロジェクト script import")
    results.append(test("全12スクリプト import OK", test_script_imports))

    print(f"\n=== 結果: {sum(results)}/{len(results)} 成功 ===")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
