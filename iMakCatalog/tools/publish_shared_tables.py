# -*- coding: utf-8 -*-
"""カタログの表を共有領域に写す (2026-09-27).

HQ は決まりでカタログの作業フォルダ (`C:/dev/iMak_catalog/`) を読めない。
出品くんが読む表は **共有領域に置いた写しが正**。

    ebay_filter_map/psa_brand_set_code.yaml -> C:/dev/iMak_data/catalog/psa_brand_set_code.yaml

依頼: `requests/2026-09-27_psa_brand_set_code_yaml_to_shared.md`
★表を直したらこれを走らせること (毎日の監査でも走るので、直後でなくても翌朝には揃う)。
"""
from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED = Path("C:/dev/iMak_data/catalog")
TABLES = {"ebay_filter_map/psa_brand_set_code.yaml": "psa_brand_set_code.yaml"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main() -> int:
    changed = 0
    for src_rel, dst_name in TABLES.items():
        src, dst = ROOT / src_rel, SHARED / dst_name
        if not src.exists():
            print(f"  ✗ 元が無い: {src}")
            continue
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            print(f"  = {dst_name} (同じ)")
            continue
        shutil.copy2(src, dst)
        changed += 1
        print(f"  + {dst_name} を更新 ({dst})")
    print(f"{changed}件 更新")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
