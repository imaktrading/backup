"""specs.set_name_ebay を _row_to_dict() の fresh 値で再 populate (2026-08-12 Advisor GO).

依頼: iMak_data/catalog/requests/2026-08-11_pdca_catalog_queue_tcg_response_question_response.md
  §決定 案A (2 commit) — commit 1: specs 再 populate migration
  「OPCG / DBSCG / Gundam の全行に _row_to_dict() の fresh 値を specs.set_name_ebay へ上書き」

**目的**: 続く adapter 反転 (commit 2) を「反転前後で値が変わる行=0」で通す前提工事。
  現行 adapter:  record.set_name or specs.set_name_ebay or ""      (fresh 優先)
  反転後 adapter: specs.set_name_ebay or record.set_name or ""      (specs 優先)
  → specs.set_name_ebay が record.set_name (= _row_to_dict の "set_name" キー) と一致すれば
    反転しても listing への出力は不変。

**scope 判定** (「変わる」rows = both_populated かつ fresh != stale = 1,016 行相当):
  対象: category ∈ {one_piece_tcg, gundam_tcg, dragonball_scg}
  更新: specs.set_name_ebay を _row_to_dict(row).get("set_name") で上書き
  skip: (a) fresh 空欄 (specs もそのまま = no-op) — 触らない
        (b) fresh == 現行 specs.set_name_ebay — no-op で touch しない
        (c) fresh に CJK/bracket が含まれる = raw 長形 fallback → skip + 報告
             (これを specs に焼くと SSOT 契約 §1-1 の canonical から逸脱するため)

**pokemon_tcg 対象外**: 2026-08-10/11 に SSOT canonical UPGRADE + longform + SM4p の3段で
  既に specs.set_name_ebay が canonical 化済。

**mojibake ガード**: 「fresh 側で mojibake が消えるはず。消えなければその行だけ止めて報告」
  (Advisor 指示)。実測: E01-* 24 行の set_name_official が Katakana 長形 (エナジーマーカーパック01)
  で fresh も同じ。specs は 'Energy Marker Pack 01' (英語 canonical, 2026-06-11 の migration
  で焼いた) が正。この 24 行は上書きしない (skip)。

**mojibake 検出**: CJK Unified / Hiragana / Katakana / bracket (`[` `【`) を含む fresh を
  「canonical でない fallback」として skip。

**冪等**: 再実行しても no-op (specs == fresh になっているため)。

**source tag**: `specs_repopulate_from_fresh_20260812_reversal_prep`

実行:
  python migrations/2026-08-12_specs_set_name_ebay_repopulate_from_fresh.py           # dry-run
  python migrations/2026-08-12_specs_set_name_ebay_repopulate_from_fresh.py --commit  # 適用
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
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
NOW = datetime.now().isoformat()
CATS = ("one_piece_tcg", "gundam_tcg", "dragonball_scg")
SRC_TAG = "specs_repopulate_from_fresh_20260812_reversal_prep"
BEFORE_JSON = Path(
    "C:/dev/iMak_data/catalog/specs_repopulate_from_fresh_before_20260812.json")
SKIP_JSON = Path(
    "C:/dev/iMak_data/catalog/specs_repopulate_from_fresh_skipped_20260812.json")

# fresh が「raw 長形 / 日本語 fallback」= canonical でない印を検出.
# _row_to_dict は filter_map miss 時 set_raw に落ちるため、CJK / 括弧が入り得る。
_NON_CANONICAL_RE = re.compile(
    r"[぀-ゟ"    # Hiragana
    r"゠-ヿ"     # Katakana
    r"一-鿿"     # CJK Unified Ideographs
    r"㐀-䶿"     # CJK Extension A
    r"\[\]"              # ASCII brackets
    r"【】"      # 【】 全角 brackets
    r"]"
)


def _is_non_canonical_fresh(s: str) -> bool:
    """fresh が canonical っぽくない (raw 長形 fallback) を検出."""
    if not s:
        return False
    return bool(_NON_CANONICAL_RE.search(s))


def _collect(con: sqlite3.Connection):
    """3 category を走査し、update / skip / noop を分類."""
    updates: list[dict] = []
    skipped_non_canonical: list[dict] = []
    for cat in CATS:
        rows = con.execute(
            "SELECT * FROM products WHERE category=?", (cat,)
        ).fetchall()
        for r in rows:
            rec = api._row_to_dict(r)
            fresh = rec.get("set_name") or ""
            specs = json.loads(r["specs"]) if r["specs"] else {}
            stale = specs.get("set_name_ebay") or ""

            # (a) fresh 空欄 → 触らない (specs もそのまま; 反転しても `or record.set_name` で
            #     どちらも空欄になるので no-op)
            if not fresh:
                continue

            # (b) fresh == stale → 既に一致、no-op
            if fresh == stale:
                continue

            # (c) fresh が canonical でない (CJK / bracket 含む raw 長形) → skip + 報告
            if _is_non_canonical_fresh(fresh):
                skipped_non_canonical.append({
                    "id": r["id"],
                    "product_id": r["product_id"],
                    "category": cat,
                    "set_name_official": r["set_name_official"],
                    "stale_specs": stale,
                    "fresh_would_be": fresh,
                    "reason": "fresh contains CJK/bracket = raw long-form fallback",
                })
                continue

            # 更新対象 (both_populated&&fresh!=stale の大半 + fresh_only の canonical 分)
            updates.append({
                "id": r["id"],
                "product_id": r["product_id"],
                "category": cat,
                "specs_dict": specs,
                "stale_specs": stale,
                "fresh": fresh,
                "prev_src": specs.get("set_name_ebay_source"),
            })
    return updates, skipped_non_canonical


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    updates, skipped = _collect(con)

    print(f"=== specs.set_name_ebay repopulate from fresh "
          f"({'COMMIT' if args.commit else 'DRY-RUN'}) ===")
    print(f"  更新対象: {len(updates)} 行  (skip 非-canonical fresh: {len(skipped)} 行)")

    # 内訳: category 別
    by_cat = Counter(u["category"] for u in updates)
    for cat, n in sorted(by_cat.items()):
        print(f"    {cat}: {n} 行")

    # 内訳: stale -> fresh (top 15)
    by_change = Counter((u["stale_specs"], u["fresh"]) for u in updates)
    print("\n  変換 top 15:")
    for (s, f), n in by_change.most_common(15):
        print(f"    {n:5d}  {s!r} -> {f!r}")

    # skip 内訳
    if skipped:
        print(f"\n  ★ skip: 非-canonical fresh {len(skipped)} 行 (specs は温存):")
        by_skip = Counter((s["category"], s["stale_specs"]) for s in skipped)
        for (cat, stale), n in by_skip.most_common(10):
            print(f"    {n:4d}  [{cat}] specs={stale!r} (fresh は raw 長形/日本語のため上書きしない)")

    # 方向性 verification (stale->fresh か fresh->stale か)
    both_populated_changes = [
        u for u in updates if u["stale_specs"] and u["fresh"]
    ]
    # 「fresh が canonical っぽくないケース」を skip した後は、
    # 上書きは常に stale -> fresh 方向 (fresh は filter_map 経由の canonical) のはず。
    print(f"\n  方向性: both_populated 更新 = {len(both_populated_changes)} 行 "
          f"(全て stale -> fresh 方向, canonical fresh のみ)")

    if not args.commit:
        print("\n  (DRY-RUN: --commit で適用)")
        con.close()
        return

    # backup
    backup = DB_PATH.with_name(
        DB_PATH.name + ".pre_specs_repopulate_from_fresh_"
        + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB_PATH, backup)
    print(f"backup: {backup.name}")

    # before-JSON (差分の完全な dump; specs_dict は除外)
    BEFORE_JSON.write_text(
        json.dumps(
            [{k: v for k, v in u.items() if k != "specs_dict"} for u in updates],
            ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"before JSON: {BEFORE_JSON} ({len(updates)} rows)")

    # skip 記録
    SKIP_JSON.write_text(
        json.dumps(skipped, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"skip JSON:   {SKIP_JSON} ({len(skipped)} rows)")

    n = 0
    for u in updates:
        d = u["specs_dict"]
        d["set_name_ebay"] = u["fresh"]
        d["set_name_ebay_source"] = SRC_TAG
        con.execute(
            "UPDATE products SET specs=?, updated_at=? WHERE id=?",
            (json.dumps(d, ensure_ascii=False), NOW, u["id"]))
        n += 1
    con.commit()
    con.close()
    print(f"\n=== done: {n} 行 repopulate (source={SRC_TAG}) ===")


if __name__ == "__main__":
    main()
