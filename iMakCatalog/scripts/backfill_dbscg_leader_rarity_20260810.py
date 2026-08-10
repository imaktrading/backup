"""DBSCG LEADER (dbfw_official) rarity 欠損 14 件 backfill — 2026-08-10

依頼: requests/2026-08-09_audit_catalog_fix_tcg_response.md 窓口GO [IMPLEMENT-GO] §A。
  cert 158452540 = FB07-097_p1 SHENRON alt art の C:Rarity 空が発端。
  真因: dbfw 公式ページは LEADER に rarity 欄自体を出さない (仕様)。
        2026-07-21 L→'Leader' 決定後の再スイープが未実施で残置。
  対象: card_type='LEADER' かつ specs.rarity IS NULL の dbfw_official 15件 のうち **14件**。
        FP-030 のみ除外 (bandai 兄弟が L★ のみで base='L' の裏付けなし。fail-closed 維持)。

規則:
  - base LEADER 4件 (variant_type 無)     → rarity='L',  rarity_ebay='Leader'
  - alt-art LEADER 10件 (variant_type='alt_art') → rarity='L★', rarity_ebay='L★'
    (psa_to_csv._to_legacy_dict_dragonball の ★-strip 経路で SCR + Alt Art に落ちる)

安全機構:
  - 事前 backup: products.sqlite.pre_leader_rarity_backfill_YYYYMMDD_HHMMSS
  - before JSON dump: dbscg_leader_rarity_backfill_before_20260810.json
  - 対象 pid は明示リスト (14件)。件数不一致は abort (外部書換ガード)。
  - dry-run/apply 分離。--apply で初めて DB を書く。

実行:
  python migrations/scripts/backfill_dbscg_leader_rarity_20260810.py           # dry-run
  python migrations/scripts/backfill_dbscg_leader_rarity_20260810.py --apply   # 適用
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"
BEFORE_JSON = Path(
    "C:/dev/iMak_data/catalog/dbscg_leader_rarity_backfill_before_20260810.json"
)
CAT = "dragonball_scg"
SPEC_SOURCE = "dbscg_leader_rarity_backfill_20260810"

# 対象 14 件 (FP-030 除外)
BASE_TARGETS = [
    "FB07-025",
    "FB07-073",
    "FB07-097",
    "SB01-029",
]
ALT_ART_TARGETS = [
    "FB01-070_p1",
    "FB03-078_p1",
    "FB04-103_p1",
    "FB07-025_p1",
    "FB07-073_p1",
    "FB07-097_p1",
    "FB09-073_p1",
    "SB01-029_p1",
    "FB07-097_p2",
    "FB07-097_p3",
]
EXPECTED = len(BASE_TARGETS) + len(ALT_ART_TARGETS)  # 14


def derive_rarity(variant_type: str | None) -> tuple[str, str]:
    """(rarity, rarity_ebay) を返す. 依頼書の規則をそのまま実装."""
    if variant_type == "alt_art":
        return ("L★", "L★")
    return ("L", "Leader")


def _fetch_targets(conn: sqlite3.Connection) -> list[tuple]:
    """指定 14 pid を DB から取得. rarity が既に入っているものは対象外."""
    pids = BASE_TARGETS + ALT_ART_TARGETS
    ph = ",".join("?" * len(pids))
    rows = conn.execute(
        f"SELECT id, product_id, source, specs FROM products "
        f"WHERE category=? AND product_id IN ({ph}) "
        f"ORDER BY product_id",
        [CAT, *pids],
    ).fetchall()
    return rows


def main(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    rows = _fetch_targets(conn)

    print(f"=== DBSCG LEADER rarity backfill ({'APPLY' if apply else 'DRY-RUN'}) ===")
    print(f"対象: {len(rows)} 件 (期待 {EXPECTED} / FP-030 除外)")

    if len(rows) != EXPECTED:
        found = {r[1] for r in rows}
        missing = sorted(set(BASE_TARGETS + ALT_ART_TARGETS) - found)
        print(f"  ✗ ABORT: 件数 {len(rows)} != {EXPECTED}. missing={missing}")
        conn.close()
        sys.exit(2)

    plan: list[dict] = []
    for rid, pid, source, sp in rows:
        d = json.loads(sp) if sp else {}
        cur_rarity = d.get("rarity")
        cur_re = d.get("rarity_ebay")
        vt = d.get("variant_type")
        ct = d.get("card_type")
        if ct != "LEADER":
            print(f"  ✗ ABORT: {pid} card_type={ct!r} != LEADER. Aborting.")
            conn.close()
            sys.exit(2)
        if cur_rarity or cur_re:
            print(f"  ✗ ABORT: {pid} 既に rarity={cur_rarity!r} / rarity_ebay={cur_re!r} が入っている.")
            conn.close()
            sys.exit(2)
        new_r, new_re = derive_rarity(vt)
        plan.append({
            "id": rid, "product_id": pid, "source": source,
            "variant_type": vt, "before_rarity": cur_rarity,
            "before_rarity_ebay": cur_re,
            "after_rarity": new_r, "after_rarity_ebay": new_re,
        })
        print(f"  {pid:20s} variant_type={vt or '-':<8s} "
              f"rarity None→{new_r!r} rarity_ebay None→{new_re!r}")

    if not apply:
        print("\n  (DRY-RUN: --apply で適用)")
        conn.close()
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = Path(DB).with_name(Path(DB).name + f".pre_leader_rarity_backfill_{stamp}")
    shutil.copy2(DB, backup)
    print(f"\nbackup: {backup.name}")
    BEFORE_JSON.write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"before JSON: {BEFORE_JSON} ({len(plan)} rows)")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    for entry in plan:
        row = conn.execute(
            "SELECT specs FROM products WHERE id=?", (entry["id"],)
        ).fetchone()
        d = json.loads(row[0]) if row and row[0] else {}
        d["rarity"] = entry["after_rarity"]
        d["rarity_ebay"] = entry["after_rarity_ebay"]
        d["spec_source"] = SPEC_SOURCE
        d["note"] = (
            (d.get("note", "") + " ") if d.get("note") else ""
        ) + (
            f"rarity backfilled 2026-08-10 (LEADER card_type / "
            f"variant_type={entry['variant_type'] or 'base'} / rule=derive)."
        )
        conn.execute(
            "UPDATE products SET specs=?, updated_at=? WHERE id=?",
            (json.dumps(d, ensure_ascii=False), now, entry["id"]),
        )
        n += 1
    conn.commit()
    conn.close()
    print(f"\n=== done: {n} 行 rarity/rarity_ebay 更新 ===")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
