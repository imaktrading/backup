"""Pokemon Mega系 set_name_ebay 誤マッピング根本修正 (HQ裁定 2026-06-07).

依頼: requests/2026-06-07_pokemon_mega_set_name_ebay_fix.md (buyer SNAD 指摘が発端)

真因: migrations/2026-05-30_pokemon_set_name_ebay_jp_mapping.py の JP_TO_EN dict が、
  英語版の存在しない新弾JP set を無関係な旧ENセットに手動割当てしていた:
    インフェルノX → Sun & Moon—Burning Shadows  (M2)
    ムニキスゼロ  → Sun & Moon—Ultra Prism       (M3)  ← buyer指摘の元
    ニンジャスピナー → XY—Steam Siege            (M4)
  = Step B 自動fetch失敗後、空欄を避けて旧EN名を流用した fail-closed 違反。

HQ裁定 (2026-06-07, web実証):
  軸1 スコープ = Mega系のみ今すぐ (SV/S/SM系7,960件は別プロジェクト)
  軸2 値 = 確定値を適用 (JPセット名。英語合本名 Perfect Order 等は使わない)。確定値なしは空欄。

確定値 (HQ web確定):
  M2  -> Inferno X
  M2a -> MEGA Dream ex
  M3  -> Nihil Zero   (旧 yaml "Munigus Zero" も誤り。yaml も訂正済)
  M4  -> Ninja Spinner

監査発見 (HQ未確定・本migrationでは触らない):
  M1L "Scarlet & Violet—Mega Brave" / M1S "Scarlet & Violet—Mega Symphonia"
    = 旧EN流用ではなく正しいJP名+SV接頭辞。SNAD型でないため HQ 確認事項として保留。
  M5 = 既に空欄 (確定値なし) → 維持。

根本対策 (HQ承認): yaml(ebay_filter_map/pokemon.yaml) を SSOT 化、
  2026-05-30 hardcode/jp_mapping migration は DEPRECATED (再実行禁止)。

実行:
  python iMakCatalog/migrations/2026-06-07_pokemon_mega_set_name_ebay_fix.py          # dry-run
  python iMakCatalog/migrations/2026-06-07_pokemon_mega_set_name_ebay_fix.py --commit # backup+投入
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = Path(api._DB_PATH)
CATEGORY = "pokemon_tcg"
NOW = datetime.now().isoformat()

# 確定値 (HQ web確定 2026-06-07). prefix(= product_id の '-' 前) -> eBay Set 値
CONFIRMED = {
    "M2": "Inferno X",
    "M2a": "MEGA Dream ex",
    "M3": "Nihil Zero",
    "M4": "Ninja Spinner",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="DB投入 (無印=dry-run)")
    args = ap.parse_args()

    print(f"=== Pokemon Mega set_name_ebay fix {'(COMMIT)' if args.commit else '(DRY-RUN)'} ===")
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute(
        "SELECT id, product_id, specs FROM products WHERE category=?", (CATEGORY,)
    ).fetchall()

    targets = []  # (id, pid, before, after)
    for r in rows:
        pre = (r["product_id"] or "").split("-")[0]
        if pre not in CONFIRMED:
            continue
        try:
            d = json.loads(r["specs"]) if r["specs"] else {}
        except Exception:
            d = {}
        before = d.get("set_name_ebay")
        after = CONFIRMED[pre]
        if before != after:
            targets.append((r["id"], r["product_id"], before, after, d))

    # サマリ
    from collections import Counter
    bypre = Counter((t[1].split("-")[0]) for t in targets)
    print(f"  対象 (変更要): {len(targets)} 件  内訳={dict(bypre)}")
    for pid, before, after in sorted({(t[1].split('-')[0], t[2], t[3]) for t in targets}):
        print(f"    {pid:5} {before!r} -> {after!r}")
    # M3-097 サンプル
    samp = [t for t in targets if t[1] == "M3-097"]
    if samp:
        print(f"  sample M3-097: {samp[0][2]!r} -> {samp[0][3]!r}")

    if not args.commit:
        print("\n  (DRY-RUN: DB 無変更。確認後 --commit)")
        con.close()
        return

    bak = DB_PATH.with_name(DB_PATH.name + ".pre_pokemon_mega_set_ebay_"
                            + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB_PATH, bak)
    print(f"  ✅ backup: {bak}")

    n = 0
    for _id, pid, before, after, d in targets:
        d["set_name_ebay"] = after
        d["set_name_ebay_source"] = "hq_confirmed_20260607"
        cur.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                    (json.dumps(d, ensure_ascii=False), NOW, _id))
        n += 1
    con.commit()
    print(f"  ✅ 投入: {n} 件")

    # verify
    for pre, exp in CONFIRMED.items():
        bad = 0
        for r in cur.execute("SELECT product_id, specs FROM products WHERE category=?", (CATEGORY,)):
            if (r[0] or "").split("-")[0] != pre:
                continue
            try:
                dd = json.loads(r[1]) if r[1] else {}
            except Exception:
                dd = {}
            if dd.get("set_name_ebay") != exp:
                bad += 1
        print(f"  verify {pre:5} -> {exp!r}: 不一致 {bad} 件")
    con.close()


if __name__ == "__main__":
    main()
