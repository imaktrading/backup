#!/usr/bin/env python3
"""G-Shock 4 model の band/dial(/bezel) color を公式裏取り値で投入 (2026-06-14 HQ greenlight).

元: 2026-06-14_gshock_color_4model_backfill_greenlight.md (真因B: catalog の色 gap 4 model)。
fail-closed: 公式 (Casio官方 / 正規ディーラー sakurawatches / Amazon公式) で確認できた色のみ投入。
型番末尾 color code や画像目視の推測はしない。確認できた field のみ入れる。

裏取り source (2026-06-14):
  GST-W310-1A    band=Black dial=Black           : sakurawatches(正規店) + g-central
  DW-5900-1      band=Black dial=Black           : sakurawatches + Amazon公式title"ブラック"
  MTG-B2000B-1A2 band=Black dial=Black bezel=Blue: sakurawatches(band/dial) + casio europe官方(bezel)
  MTG-B3000D-1A  band=Silver dial=Black          : sakurawatches(composite Silver) + g-central"Silver and Black"

specs 列のみ直接 UPDATE する (upsert は images/name を上書きするため使わない)。.bak 必須。
"""
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = "C:/dev/iMak_data/catalog/products.sqlite"
BAK_PATH = Path("C:/dev/iMak_data/catalog/_bak/gshock_color_4model_before_20260614.json")
CATEGORY = "gshock"

# 投入する確定値 (公式裏取り済のみ)。source は各 field 個別に記録。
SRC_CASIO = "casio_official_20260614"
SRC_AMAZON = "amazon_casio_official_20260614"

PLAN = {
    "GST-W310-1A": {
        "band_color": ("Black", SRC_CASIO),
        "dial_color": ("Black", SRC_CASIO),
    },
    "DW-5900-1": {
        "band_color": ("Black", SRC_AMAZON),
        "dial_color": ("Black", SRC_AMAZON),
    },
    "MTG-B2000B-1A2": {
        "band_color": ("Black", SRC_CASIO),
        "dial_color": ("Black", SRC_CASIO),
        "bezel_color": ("Blue", SRC_CASIO),
    },
    "MTG-B3000D-1A": {
        "band_color": ("Silver", SRC_CASIO),
        "dial_color": ("Black", SRC_CASIO),
    },
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--apply" not in sys.argv
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    bak = {}
    changes = []
    for pid, fields in PLAN.items():
        row = conn.execute(
            "SELECT specs FROM products WHERE category=? AND product_id=?",
            (CATEGORY, pid),
        ).fetchone()
        if not row:
            print(f"⚠️ NOT FOUND: {pid} (skip)")
            continue
        specs = json.loads(row["specs"])
        bak[pid] = json.loads(row["specs"])  # 旧 specs 全体を保存 (完全復元可)

        before = {f: specs.get(f) for f in fields}
        # fail-closed: 既に色が入っている field は上書きしない (gap のみ埋める)
        for f, (val, src) in fields.items():
            if specs.get(f):
                print(f"  {pid}.{f} 既存={specs[f]!r} → skip (上書きしない)")
                continue
            specs[f] = val
            specs[f.replace("_color", "_color_source")] = src
        after = {f: specs.get(f) for f in fields}
        changes.append((pid, before, after))

        if not dry:
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE products SET specs=?, updated_at=? "
                "WHERE category=? AND product_id=?",
                (json.dumps(specs, ensure_ascii=False), now, CATEGORY, pid),
            )

    print("\n=== 投入計画 (before → after) ===")
    for pid, before, after in changes:
        print(f"{pid}:")
        for f in after:
            print(f"   {f}: {before[f]!r} → {after[f]!r}")

    if dry:
        print("\n[DRY-RUN] DB 未変更。投入は --apply を付けて再実行。")
        conn.close()
        return

    BAK_PATH.parent.mkdir(parents=True, exist_ok=True)
    BAK_PATH.write_text(json.dumps(bak, ensure_ascii=False, indent=2), encoding="utf-8")
    conn.commit()
    conn.close()
    print(f"\n✅ 投入完了 ({len(changes)} model)。bak: {BAK_PATH}")


if __name__ == "__main__":
    main()
