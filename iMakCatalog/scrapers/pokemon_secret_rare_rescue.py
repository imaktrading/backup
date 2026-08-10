#!/usr/bin/env python3
"""Pokemon TCG secret rare 画像救出 (案C: cardID BFS で resultAPI 網目外の HR/UR/SR を回収).

背景 (窓口GO §Q2 案C, 2026-08-10 card_images_leader_back_and_pokemon_missing_response.md):
  pokemon-card.com の resultAPI (`pg=SMxx`) は base set (~094 番台まで) のみ index する。
  #107 以降の HR/UR/secret rare は index に載らないため
  `iMakCatalog/scrapers/pokemon_tcg.py:find_official_card` では拾えない。
  bulbapedia/serebii 経由で specs は投入済だが images が空のまま。

対策:
  set の既知 cardID 範囲 (products.source_url から derive) の周辺 (± window) を BFS 走査し、
  detail.set_code + detail.card_number_text (printed 番号) が target と一致した cardID から
  image_url を pokemon-card.com から取得 → products.images に upsert。

不変条件 (fail-closed 原則):
  - set_code が一致しない cardID は無視 (画像混同を防ぐ)
  - card_number_text が一致しない cardID は無視 (同 set 内の別カード混同を防ぐ)
  - target の DB record が居ない場合は skip (勝手に新規 upsert しない)
  - 画像が取れない target は「救えなかった pid」として報告

CLI:
  python scrapers/_pokemon_secret_rare_rescue.py --probe               # 事前調査 (現状レポートのみ)
  python scrapers/_pokemon_secret_rare_rescue.py --window 200          # BFS window ± 200 cardIDs
  python scrapers/_pokemon_secret_rare_rescue.py --targets SM11-112,SM12-112,...  # 対象指定
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scrapers"))
import api  # noqa: E402
import pokemon_tcg as pt  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# 窓口 GO の対象 5件 (secret rare - HR/UR). 追加要望は SV-P-291 / cardID- 5件
DEFAULT_TARGETS = [
    "SM11-112",   # Dragonite-GX HR
    "SM12-112",   # Arceus & Dialga & Palkia-GX HR
    "SM12a-214",  # Jirachi-GX HR
    "SM12a-224",  # Lucario & Melmetal-GX UR
    "SM9a-067",   # Gardevoir & Sylveon-GX HR
]


def parse_target(pid: str) -> tuple[str, str] | None:
    """'SM11-112' → ('SM11', '112'). ハイフン前後で分割."""
    if "-" not in pid:
        return None
    set_code, card_num = pid.rsplit("-", 1)
    if not set_code or not card_num:
        return None
    return set_code, card_num


def known_cardid_range(cur: sqlite3.Cursor, set_code: str) -> tuple[int, int] | None:
    """DB の source_url から set_code の既知 cardID 範囲を返す (min, max). 無ければ None."""
    rows = cur.execute(
        "SELECT source_url FROM products WHERE category='pokemon_tcg' "
        "AND product_id LIKE ? AND source='pokemon_card_jp' "
        "AND source_url IS NOT NULL",
        (f"{set_code}-%",),
    ).fetchall()
    cids: list[int] = []
    for (url,) in rows:
        if not url or "/card/" not in url:
            continue
        tail = url.rsplit("/", 1)[-1]
        if tail.isdigit():
            cids.append(int(tail))
    if not cids:
        return None
    return (min(cids), max(cids))


def match_target(detail: dict, set_code: str, card_num: str) -> bool:
    """detail が target (set_code + card_num) に一致するか判定.

    - detail.set_code (画像URLから抽出) と set_code が完全一致
    - detail.card_number_text の 分子 (印刷番号) が card_num の 0-strip と一致
    """
    if not detail:
        return False
    if (detail.get("set_code") or "") != set_code:
        return False
    printed = (detail.get("card_number_text") or "").split("/")[0].lstrip("0")
    want = card_num.lstrip("0")
    return bool(printed) and printed == want


def find_cardid_for_target(set_code: str, card_num: str,
                            window: int, cur: sqlite3.Cursor,
                            verbose: bool = True) -> dict | None:
    """target (set_code, card_num) に一致する pokemon-card.com detail を BFS で探索.

    戦略:
      1. DB から set の既知 cardID 範囲 (min..max) を取得
      2. max+1 .. max+window を forward 走査 (HR は末尾側に多い)
      3. min-window .. min-1 を backward 走査 (未網羅の分岐用)
      各 cardID で get_detail → match_target で一致確認.
      一致した最初の detail を返す (通常は 1 枚しかヒットしない).
    """
    rng = known_cardid_range(cur, set_code)
    if rng is None:
        if verbose:
            print(f"  ⚠️ {set_code}: 既知 cardID 範囲なし (skip)")
        return None
    lo, hi = rng
    if verbose:
        print(f"  {set_code}-{card_num}: 既知範囲 [{lo}..{hi}], window ±{window}")

    scan_order: list[int] = []
    # forward 先行 (HR は set の末尾に集約されることが多い)
    scan_order.extend(range(hi + 1, hi + 1 + window))
    scan_order.extend(range(max(1, lo - window), lo))

    for cid in scan_order:
        try:
            detail = pt.get_detail(cid)
        except Exception as e:
            if verbose:
                print(f"    cardID={cid}: fetch fail {e}")
            continue
        if not detail:
            continue
        if match_target(detail, set_code, card_num):
            if verbose:
                print(f"    ✓ HIT cardID={cid} set={detail.get('set_code')} "
                      f"num={detail.get('card_number_text')} name={detail.get('name')!r}")
            return {"cardID": cid, "detail": detail}
    return None


def upsert_image(cur: sqlite3.Cursor, conn: sqlite3.Connection,
                  product_id: str, image_url: str, dry_run: bool) -> bool:
    """既存 products record の images 列に image_url を書込. dry_run=True なら print のみ.

    fail-closed: 対象 record が存在しない場合は False を返す (勝手に新規 upsert しない).
    """
    row = cur.execute(
        "SELECT id, images FROM products WHERE category='pokemon_tcg' AND product_id=?",
        (product_id,),
    ).fetchone()
    if not row:
        return False
    rid, existing = row
    try:
        existing_list = json.loads(existing) if existing else []
    except Exception:
        existing_list = []
    if image_url in existing_list:
        return True  # 既に登録済
    new_list = [image_url]  # single-front-image で上書き (pokemon の通常仕様)
    if dry_run:
        print(f"    [dry-run] would UPDATE products id={rid} pid={product_id} "
              f"images={new_list}")
        return True
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE products SET images=?, updated_at=? WHERE id=?",
        (json.dumps(new_list, ensure_ascii=False), now, rid),
    )
    conn.commit()
    return True


def rescue(targets: list[str], window: int = 200,
           dry_run: bool = False, verbose: bool = True) -> dict:
    """targets の各 pid について画像救出を試行し、結果 dict を返す.

    Returns:
        {"rescued": [pid, ...], "not_found": [pid, ...], "skipped": [pid, ...]}
    """
    conn = sqlite3.connect(str(api._DB_PATH))
    cur = conn.cursor()

    result: dict[str, list[str]] = {"rescued": [], "not_found": [], "skipped": []}
    started = time.time()

    for pid in targets:
        parsed = parse_target(pid)
        if not parsed:
            if verbose:
                print(f"  ⚠️ {pid}: parse fail → skip")
            result["skipped"].append(pid)
            continue
        set_code, card_num = parsed
        # target が DB に居ることを確認 (画像空でも OK)
        row = cur.execute(
            "SELECT images FROM products WHERE category='pokemon_tcg' AND product_id=?",
            (pid,),
        ).fetchone()
        if not row:
            if verbose:
                print(f"  ⚠️ {pid}: DB 未登録 → skip")
            result["skipped"].append(pid)
            continue
        try:
            existing_imgs = json.loads(row[0]) if row[0] else []
        except Exception:
            existing_imgs = []
        if existing_imgs:
            if verbose:
                print(f"  {pid}: already has images ({len(existing_imgs)}件) → skip")
            result["skipped"].append(pid)
            continue

        hit = find_cardid_for_target(set_code, card_num, window, cur, verbose=verbose)
        if not hit:
            if verbose:
                print(f"  ✗ {pid}: BFS 範囲内で一致なし")
            result["not_found"].append(pid)
            continue
        img = (hit["detail"] or {}).get("image_url") or ""
        if not img:
            if verbose:
                print(f"  ✗ {pid}: detail hit したが image_url なし")
            result["not_found"].append(pid)
            continue
        if upsert_image(cur, conn, pid, img, dry_run=dry_run):
            result["rescued"].append(pid)
        else:
            result["skipped"].append(pid)

    conn.close()
    elapsed = int(time.time() - started)
    if verbose:
        print(f"\n=== rescue summary (elapsed {elapsed}s) ===")
        print(f"  rescued  : {len(result['rescued'])} / {len(targets)}")
        print(f"  not_found: {len(result['not_found'])}")
        print(f"  skipped  : {len(result['skipped'])}")
        for k in ("rescued", "not_found", "skipped"):
            for pid in result[k]:
                print(f"    [{k:9}] {pid}")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--targets", type=str, default="",
                   help="カンマ区切り product_id list (default: 窓口GOの5件)")
    p.add_argument("--window", type=int, default=200,
                   help="BFS window ± cardIDs from known range (default 200)")
    p.add_argument("--dry-run", action="store_true",
                   help="DB 更新せず結果のみ表示")
    p.add_argument("--probe", action="store_true",
                   help="target の DB 状態のみ表示、fetch はしない")
    args = p.parse_args()

    targets = ([s.strip() for s in args.targets.split(",") if s.strip()]
               if args.targets else list(DEFAULT_TARGETS))

    if args.probe:
        conn = sqlite3.connect(str(api._DB_PATH))
        cur = conn.cursor()
        for pid in targets:
            parsed = parse_target(pid)
            if not parsed:
                print(f"  {pid}: unparseable")
                continue
            set_code, card_num = parsed
            row = cur.execute(
                "SELECT name, images, source FROM products "
                "WHERE category='pokemon_tcg' AND product_id=?",
                (pid,),
            ).fetchone()
            rng = known_cardid_range(cur, set_code)
            print(f"  {pid}: db={'yes' if row else 'no'} "
                  f"imgs={row[1] if row else '?'} "
                  f"source={row[2] if row else '?'} "
                  f"set_range={rng}")
        conn.close()
        return

    rescue(targets, window=args.window, dry_run=args.dry_run, verbose=True)


if __name__ == "__main__":
    main()
