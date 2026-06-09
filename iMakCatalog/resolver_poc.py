"""KEY再設計 Step1 POC (go/no-go 実証用・throwaway). 本番 facade は Step3 で resolver.py に。

仕様: iMak_data/KEY_REDESIGN_SPEC.md / greenlight: requests/2026-06-09_key_redesign_BUILD_greenlight_phase1.md
目的の最小実証:
  - 固有KEY: variant signal(brand+subject) → 正しい1個の固有 product_id に当たる
  - bare の誤除外が起きない: signal無しの bare 番号 → base product_id (在れば)
  - 判別不能 → "" (fail-closed、推測で固有id当てない)

実行: python iMakCatalog/resolver_poc.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import api  # noqa: E402
import psa_to_csv as P  # noqa: E402
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def resolve_poc(category: str, *, brand: str = "", subject: str = "",
                card_no: str = "") -> tuple[str, str]:
    """最小 resolver (one_piece のみ). Returns (product_id | "", reason)."""
    if category != "one_piece_tcg":
        return ("", "POC未対応category")
    num = card_no.split("-")[-1] if "-" in card_no else card_no
    # 1) variant signal あり → promo/variant 解決 (既存 promo-scoring 流用)
    if subject.strip():
        r = P._search_one_piece_promo_by_number(num, subject, brand=brand, verbose=False)
        if r:
            return (r["product_id"], "variant via promo-search")
    # 2) signal完全に無い bare → base が一意に在れば base (誤除外なし)
    if not subject.strip() and not brand.strip() and "-" in card_no:
        base = api.lookup(category=category, product_id=card_no)
        if base:
            return (base["product_id"], "bare→base (誤除外なし)")
    # 3) それ以外(signalあるが特定不能 / base無し) → fail-closed
    return ("", "判別不能 → fail-closed")


CASES = [
    ("① Sabo (Best Selection vol.4)", dict(
        brand="ONE PIECE JAPANESE PREMIUM CARD COLLECTION -BEST SELECTION VOL.4-",
        subject="SABO", card_no="OP10-049"), "OP10-049_p1"),
    ("② bare OP10-049 (signal無し)", dict(card_no="OP10-049"), "OP10-049"),
    ("③ brand のみ subject無し", dict(brand="SOME BRAND", card_no="OP10-049"), ""),
    ("④ 未対応 signal (3周年 treasure=_p2 未到達)", dict(
        brand="3RD ANNIVERSARY TREASURE", subject="SABO", card_no="OP10-049"), ""),
]


def main():
    print("=== KEY再設計 Step1 POC (one_piece) ===")
    allok = True
    for label, kw, expect in CASES:
        pid, why = resolve_poc("one_piece_tcg", **kw)
        ok = pid == expect
        allok &= ok
        print(f"  {'OK ' if ok else 'NG '} {label}: -> {pid!r} (期待{expect!r}) [{why}]")
    print("\n  POC:", "GO ✅" if allok else "要確認")


if __name__ == "__main__":
    main()
