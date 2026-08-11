"""pokemon set_name_official — 316 set_code × 1 fetch.

依頼書: `C:/dev/iMak_data/catalog/requests/2026-08-02_pokemon_set_name_official_316_setcode_fetch.md`
Phase 1: uniform / all-null / small groups だけを対象。多値9群・デッキ系は除外。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("C:/dev/iMak_data/catalog/products.sqlite")
SNAPSHOT_DIR = Path("C:/dev/iMak_data/catalog/backups")
BEFORE_AFTER_DIR = Path("C:/dev/iMak_data/catalog/requests")
SOURCE_TAG = "official_setcode_fetch_20260802"

USER_AGENT = "Mozilla/5.0 (compatible; iMakCatalogFetch/1.0; +imak-trading)"
POLITE_SLEEP_SEC = 2.5
FETCH_TIMEOUT_SEC = 30

# 多値9群 (既知9): 群単位一括の前提が成り立たない
MIXED_GROUPS = {
    "cardID", "SM-P", "XYP", "SV-P", "BWP", "SM9a", "DPtP", "SMI", "SMM",
}

# デッキ系 (既知7 + 疑い): 1 set_code に複数商品が混在
DECK_LIKE_GROUPS = {
    "SD",   # BRAVO 実測: 1枚 = 1商品 で非均一
    "SVD", "SVM", "SMH", "SGG",  # BRAVO 未実測 / 同型の疑い
    "SGI", "SGL",                 # 同型の疑い (deck 系名称)
}

# 購入導線パターン (li から捨てる)
PURCHASE_LINK_PATTERNS = [
    "こちら",       # ポケモンセンターオンラインでの購入はこちら
    "オンライン",   # 汎用
    "受注生産",     # まれに
    "Amazon",
]

SECTION_RE = re.compile(
    r'<section[^>]*class="[^"]*SubSection[^"]*".*?</section>',
    re.DOTALL,
)
LI_RE = re.compile(
    r'<li[^>]*class="[^"]*List_item[^"]*"[^>]*>(.*?)</li>',
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def sc_of(pid: str) -> str:
    m = re.match(r"^(.+?)-\d+$", pid)
    return m.group(1) if m else pid


def clean_text(html: str) -> str:
    text = TAG_RE.sub("", html)
    text = WS_RE.sub(" ", text).strip()
    return text


def is_purchase_link(text: str) -> bool:
    if not text:
        return True
    for pat in PURCHASE_LINK_PATTERNS:
        if pat in text:
            return True
    return False


def fetch_set_name(url: str) -> tuple[list[str], str | None]:
    """Return (real_products, error). real_products = purchase-link 除外後の li テキスト."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as r:
            html = r.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        return [], f"fetch_error: {e!r}"
    m = SECTION_RE.search(html)
    if not m:
        return [], "no SubSection"
    lis = LI_RE.findall(m.group(0))
    if not lis:
        return [], "no List_item"
    products = []
    for li in lis:
        text = clean_text(li)
        if is_purchase_link(text):
            continue
        products.append(text)
    return products, None


def build_group_index(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, product_id, set_name, set_name_official, source, source_url, specs "
        "FROM products WHERE category='pokemon_tcg'"
    )
    groups: dict[str, list[dict]] = {}
    for row_id, pid, sn, sno, src, url, specs in cur.fetchall():
        sc = sc_of(pid)
        groups.setdefault(sc, []).append({
            "id": row_id,
            "product_id": pid,
            "set_name": sn,
            "set_name_official": sno,
            "source": src,
            "source_url": url,
            "specs": specs,
        })
    return groups


def pick_representative(rows: list[dict]) -> dict | None:
    """1件だけ fetch する代表行: source_url が details.php を指すものを優先。"""
    for r in rows:
        u = r["source_url"] or ""
        if "pokemon-card.com/card-search/details.php/card/" in u:
            return r
    return None


def snapshot_db() -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = SNAPSHOT_DIR / f"products_{ts}_before_set_name_official_fetch.sqlite"
    shutil.copy2(DB_PATH, dest)
    return dest


def process_group(
    conn: sqlite3.Connection,
    set_code: str,
    rows: list[dict],
    apply: bool,
) -> dict:
    result = {
        "set_code": set_code,
        "row_count": len(rows),
        "picked": None,
        "fetched_products": None,
        "fetched_url": None,
        "fetch_error": None,
        "action": None,  # applied | skipped_multi | skipped_no_product | skipped_no_url | dry_run
        "target_value": None,
        "updates": 0,
        "before_values": {},
        "after_values": {},
    }

    if set_code in MIXED_GROUPS:
        result["action"] = "skipped_mixed_group"
        return result
    if set_code in DECK_LIKE_GROUPS:
        result["action"] = "skipped_deck_like"
        return result

    rep = pick_representative(rows)
    if rep is None:
        result["action"] = "skipped_no_url"
        return result
    result["picked"] = rep["product_id"]
    result["fetched_url"] = rep["source_url"]

    products, err = fetch_set_name(rep["source_url"])
    result["fetched_products"] = products
    if err:
        result["fetch_error"] = err
        result["action"] = "skipped_fetch_error"
        return result
    if len(products) == 0:
        result["action"] = "skipped_no_product"
        return result
    if len(products) >= 2:
        result["action"] = "skipped_multi_product"
        return result

    target = WS_RE.sub(" ", products[0]).strip()
    result["target_value"] = target

    # ここから apply モードのみ書き込む
    result["before_values"] = {r["product_id"]: r["set_name_official"] for r in rows}
    if not apply:
        result["action"] = "dry_run"
        result["after_values"] = {r["product_id"]: target for r in rows}
        return result

    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in rows:
        cur.execute(
            "UPDATE products SET set_name_official=?, source=?, updated_at=? WHERE id=?",
            (target, SOURCE_TAG, now, r["id"]),
        )
        result["updates"] += 1
    result["after_values"] = {r["product_id"]: target for r in rows}
    result["action"] = "applied"
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--group", help="set_code (例: S8a). 指定なら1群だけ実行")
    p.add_argument("--apply", action="store_true", help="実際に書き込む (既定は dry-run)")
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="before/after JSON 出力先。既定は requests/_evidence_YYYY-MM-DD_...json",
    )
    args = p.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")

    groups = build_group_index(conn)
    print(f"[info] pokemon_tcg groups={len(groups)} rows={sum(len(v) for v in groups.values())}")

    if not args.group:
        print("[usage] --group <set_code> を指定してください (Phase 1 は 1群ずつ)")
        return 2
    if args.group not in groups:
        print(f"[error] group not found: {args.group}")
        return 2

    snap = None
    if args.apply:
        snap = snapshot_db()
        print(f"[snapshot] {snap}")

    rows = groups[args.group]
    print(f"[group] {args.group} row_count={len(rows)}")

    # apply=True でも fetch→UPDATE→評価の順を守る
    if args.apply:
        conn.execute("BEGIN")
    result = process_group(conn, args.group, rows, apply=args.apply)
    if args.apply:
        if result["action"] == "applied":
            conn.commit()
        else:
            conn.rollback()
            print(f"[warn] rolled back: action={result['action']}")
    conn.close()

    # polite sleep between groups (今は1群だけだが将来複数に備える)
    time.sleep(POLITE_SLEEP_SEC)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or (
        BEFORE_AFTER_DIR
        / f"_evidence_{ts}_alpha_set_name_official_fetch_{args.group}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": ts,
                "source_tag": SOURCE_TAG,
                "snapshot": str(snap) if snap else None,
                "apply": args.apply,
                "result": result,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"[out] {out}")
    print(f"[action] {result['action']} updates={result['updates']} target={result['target_value']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
