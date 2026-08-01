"""facet N:1 batch1: 8 facet の straggler(誤マップ) の set_name_ebay を空欄化 — 2026-08-01

依頼: requests/2026-08-01_hq_go_perona_tie_and_facet_batch1 ② (窓口GO, 8 facet)。
検出: name_guard.find_facet_n1_candidates (allowlist=facet_n1_allowlist.yaml)。

方式 (Ultra Prism 同型 + 窓口条件):
  - **straggler だけ空欄化** (主セット=allowlist 済は不変)。
  - straggler の多くは SM-P-* promo で、set_name_ebay が別の拡張 facet に誤マップ。正しい promo/
    set facet は **公式で突合できていない**ため、**推測で付け替えず空欄化** (窓口条件1: できなければ空欄化)。
  - specs.set_name_ebay を json_remove + source=blank マーカー + b_layer_status を unverified。
  - **変更した product_id 一覧を返球** (窓口が出品中商品と突合し eBay revision 要否を判断)。
  - dry-run で件数照合 → --apply。実行時に allowlist を再読込して straggler を再特定。

実行: python migrations/2026-08-01_facet_n1_batch1_blank_stragglers.py         (dry-run)
      python migrations/2026-08-01_facet_n1_batch1_blank_stragglers.py --apply
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from name_guard import load_facet_n1_allowlist  # noqa: E402

DB = "C:/dev/iMak_data/catalog/products.sqlite"
BEFORE_JSON = Path("C:/dev/iMak_data/catalog/facet_n1_batch1_before_20260801.json")
CAT = "pokemon_tcg"
BLANK_SOURCE = "blanked_by_facet_n1_batch1_20260801"
BLANK_NOTE = "reverted mismapped set_name_ebay (facet N:1 straggler, batch1)"

# 窓口 GO の 8 facet
BATCH1_FACETS = [
    "Sun & Moon—Team Up", "Sun & Moon—Celestial Storm", "Sun & Moon—Forbidden Light",
    "Sun & Moon—Unbroken Bonds", "Sun & Moon—Guardians Rising", "Galactic's Conquest",
    "Sword & Shield—Lost Origin", "Sun & Moon—Cosmic Eclipse",
]


def _targets(conn) -> list:
    """batch1 facet を持ち、set_name_official が **allowlist 外(=straggler)** の行。
    ※ set_name_official が NULL/空 の行は audit 非検出のため対象外 (別 issue)。"""
    allow = (load_facet_n1_allowlist().get(CAT) or {})
    rows = conn.execute(
        "select id, product_id, set_name_official, specs from products "
        "where category=? and json_extract(specs,'$.set_name_ebay') in (%s)"
        % ",".join("?" * len(BATCH1_FACETS)),
        (CAT, *BATCH1_FACETS),
    ).fetchall()
    out = []
    for rid, pid, so, sp in rows:
        se = json.loads(sp).get("set_name_ebay")
        if not so:
            continue                                   # None-official は対象外
        if so in allow.get(se, set()):
            continue                                   # 主セット (allowlist) は不変
        out.append((rid, pid, so, se, sp))
    return out


def main(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    tgt = _targets(conn)
    from collections import Counter
    by_facet = Counter(se for _, _, _, se, _ in tgt)
    print(f"=== facet N:1 batch1 straggler 空欄化 ({'APPLY' if apply else 'DRY-RUN'}) ===")
    print(f"straggler 対象: {len(tgt)} 件")
    for se, n in by_facet.most_common():
        print(f"  {se!r}: {n}")

    if not apply:
        print("dry-run: --apply で実行。")
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    before = []
    for rid, pid, so, se, sp in tgt:
        bl = conn.execute("select status, oracle, note from b_layer_status "
                          "where product_id_ref=? and field='set_name_ebay'", (rid,)).fetchone()
        before.append({"id": rid, "product_id": pid, "set_name_official": so,
                       "set_name_ebay": se,
                       "b_layer_status": (list(bl) if bl else None)})
    BEFORE_JSON.write_text(json.dumps(before, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"before JSON: {BEFORE_JSON} ({len(before)} rows)")

    n_specs = n_bl = 0
    changed_pids = []
    for rid, pid, so, se, sp in tgt:
        d = json.loads(sp)
        d.pop("set_name_ebay", None)
        d["set_name_ebay_source"] = BLANK_SOURCE
        conn.execute("update products set specs=?, updated_at=? where id=?",
                     (json.dumps(d, ensure_ascii=False), now, rid))
        n_specs += 1
        cur = conn.execute(
            "update b_layer_status set status='unverified', oracle=?, note=?, checked_at=? "
            "where product_id_ref=? and field='set_name_ebay'",
            (BLANK_SOURCE, BLANK_NOTE, now, rid))
        n_bl += cur.rowcount
        changed_pids.append(pid)
    conn.commit()
    print(f"specs 空欄化: {n_specs} / b_layer_status 更新: {n_bl}")
    print("変更 product_id 一覧:")
    for pid in sorted(changed_pids):
        print(f"  {pid}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
