#!/usr/bin/env python3
"""gshock cron 追加 2 model を公式裏取りで catalog 投入 (2026-06-15).

元: 2026-06-14_auto_catalog_add_gshock.md (auto-add, 合意済・確認不要)。
標準 scraper 経路 (g-central slug / 公式 Casio) が使えないため (LOV/DWE-5600 は slug 未定義 +
公式 Akamai block + shockbase WebFetch 拒否)、正規店 sakurawatches + 公式 Casio listing で
裏取りした確定値のみ投入。確認できない field は空欄 (fail-closed)。

canonical product_id = region suffix(JR) 剥がし形 (DB 慣習・lookup_gshock _split_region 準拠):
  LOV-25A-7AJR  → LOV-25A-7A
  DWE-5600PR-2JR → DWE-5600PR-2

裏取り source (2026-06-15):
  DWE-5600PR-2 : sakurawatches 仕様表 (band=Multicolor/White, dial=Digital LCD(色名なし→空),
                 Carbon/Resin, Quartz cal.3229, 200m, Mineral, ¥23,100, Over Print box set)
                 + casio.com/intl product.DWE-5600PR-2
  LOV-25A-7A   : 公式 Casio (gshock.casio.com lovers-2025 / casio.com product.LOV-25A-7A) +
                 g-central: White band/dial/bezel, analog-digital Quartz, 200m, 2025,
                 G Presents Lover's Collection 2025 (GA-2100+GMA-P2100 pair box set, limited)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # iMakCatalog/
import api  # noqa: E402

CATEGORY = "gshock"

RECORDS = [
    {
        "product_id": "DWE-5600PR-2",
        "name": "Casio G-SHOCK DWE-5600PR-2",
        "source": "sakurawatches+casio_official_20260615",
        "source_url": "https://www.casio.com/intl/watches/gshock/product.DWE-5600PR-2/",
        "specs": {
            "series": "DWE-5600",
            "case_material": "Carbon, Resin",
            "case_shape": "Rectangle",
            "case_size": "43.8mm",
            "case_thickness": "13.7mm",
            "band_material": "Resin",
            "band_color": "Multicolor",          # box set: blue skeleton + white の複数バンド
            "bezel_material": "Resin",
            "bezel_color": "Multicolor",
            # dial_color: digital LCD・公式に色名表記なし → 空欄 (fail-closed)
            "crystal": "Mineral",
            "movement": "Quartz",
            "module": "3229",
            "water_resistance": "200m",
            "year": "2025",
            "is_limited": True,
            "special_edition": "Over Print box set",
            "price_jpy_msrp": 23100,
            "band_color_source": "sakurawatches_official_20260615",
            "movement_source": "deterministic_all_gshock_quartz_20260615",
            "official_spec_source": "sakurawatches+casio_official_20260615",
        },
    },
    {
        "product_id": "LOV-25A-7A",
        "name": "Casio G-SHOCK LOV-25A-7A",
        "source": "casio_official+websearch_20260615",
        "source_url": "https://www.casio.com/intl/watches/casio/product.LOV-25A-7A/",
        "specs": {
            "series": "LOV",
            "band_material": "Resin",
            "band_color": "White",
            "dial_color": "White",
            "bezel_color": "White",
            "display": "Analog-Digital",
            "movement": "Quartz",
            "water_resistance": "200m",
            "year": "2025",
            "is_limited": True,
            "is_collab": True,
            "special_edition": "G Presents Lover's Collection 2025 (GA-2100 + GMA-P2100 pair box set)",
            "band_color_source": "casio_official_websearch_20260615",
            "movement_source": "deterministic_all_gshock_quartz_20260615",
            "official_spec_source": "casio_official_websearch_20260615",
        },
    },
]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--apply" not in sys.argv
    for rec in RECORDS:
        existing = api.lookup(CATEGORY, rec["product_id"])
        print(f"{rec['product_id']}: {'既存(skip)' if existing else '新規'}"
              f" band={rec['specs'].get('band_color')!r} dial={rec['specs'].get('dial_color')!r}"
              f" year={rec['specs'].get('year')}")
        if existing:
            continue
        if not dry:
            rid = api.upsert(
                category=CATEGORY, product_id=rec["product_id"], name=rec["name"],
                specs=rec["specs"], images=[], source=rec["source"],
                source_url=rec["source_url"],
            )
            print(f"   → upserted id={rid}")
    if dry:
        print("\n[DRY-RUN] DB 未変更。投入は --apply。")


if __name__ == "__main__":
    main()
