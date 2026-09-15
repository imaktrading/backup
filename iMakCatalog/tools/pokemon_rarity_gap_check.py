#!/usr/bin/env python3
"""ポケモンのレアリティ取りこぼしを毎日見つけて、公式で確かめる — 2026-09-15

依頼: requests/2026-09-11_pokemon_vmax_rarity_rrr_missing_response.md の Q3 で約束した仕組み。

## なぜ
2026-09-13 に S4a の VMAX 126行が rarity 空だった (8/22 の取り直しが rarity を書いていなかった)。
公式は一部のカードにしかレアリティを表示しない (CLAUDE.md「Rarity の空欄は天井」) ので、
空欄を全部数えても意味が無い。公式を毎日 2万回叩くのも無理。

## やること
    候補 = rarity が空 かつ 同じ弾 (set_name_official) の他の行には rarity が入っている
           かつ まだ公式で確かめていない (印が無い)
    確かめ方 = 倉庫に保存した公式ページ (`_raw/pokemon_tcg/<cardID>`) を読み直す。無ければ公式を1回だけ取る
      公式に表示あり → rarity と rarity_ebay を入れる (取りこぼし)
      公式に表示なし → `rarity_official_absent_checked_at` を付ける (空欄が正。次から候補に出ない)

毎日の監査 (`set_name_integrity_audit.py`) が「印の無い候補」の件数を出す。**0件で維持する**。
1件でも出たら、それは新しく入った行 → このスクリプトで確かめる。

## 途中保存
1行ごとに commit。再実行は印の無い行だけを見る。

実行:
    python tools/pokemon_rarity_gap_check.py              # 候補の件数だけ
    python tools/pokemon_rarity_gap_check.py --commit
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scrapers")]
import api  # noqa: E402
import _raw_store  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATEGORY = "pokemon_tcg"
MARK = "rarity_official_absent_checked_at"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def _has_rarity(s: dict) -> bool:
    return bool(s.get("rarity") or s.get("rarity_ebay"))


def candidates(conn) -> list[tuple]:
    """(id, product_id, set_name_official, source_url, specs) — 印の無い取りこぼし候補."""
    rows = conn.execute("SELECT id, product_id, set_name_official, source_url, specs FROM products "
                        "WHERE category=?", (CATEGORY,)).fetchall()
    parsed = [(r[0], r[1], r[2], r[3], json.loads(r[4] or "{}")) for r in rows]
    sets_with = {son for _, _, son, _, s in parsed if son and _has_rarity(s)}
    return [(rid, pid, son, url, s) for rid, pid, son, url, s in parsed
            if son in sets_with and not _has_rarity(s) and not s.get(MARK)]


def official_rarity(url: str) -> tuple[str | None, str]:
    """(公式の rarity or None, 根拠)。倉庫 → 無ければ公式を1回."""
    import pokemon_tcg as P
    m = re.search(r"/card/(\d+)", url or "")
    if not m:
        raise ValueError("cardID の無い URL")
    cid = m.group(1)
    for key in (cid, f"detail_{cid}"):
        h = _raw_store.load(CATEGORY, key)
        if h:
            d = P._parse_detail_html(h, cid)
            return (d or {}).get("rarity"), f"raw:{key}"
    h = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode("utf-8", "replace")
    _raw_store.save(CATEGORY, cid, h, url)                       # 取れたものは残す
    time.sleep(1.5)
    d = P._parse_detail_html(h, cid)
    return (d or {}).get("rarity"), f"live:{datetime.now().date()}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    conn = sqlite3.connect(str(api._DB_PATH), timeout=120)
    cands = candidates(conn)
    print(f"  候補 (同じ弾に rarity が在るのに空・未確認) {len(cands)}行", flush=True)
    if not args.commit:
        return
    stat = Counter()
    now = datetime.now().isoformat(timespec="seconds")
    for i, (rid, pid, son, url, s) in enumerate(cands, 1):
        try:
            rar, basis = official_rarity(url)
        except Exception as e:                       # 1件の失敗で走行を落とさない
            stat[f"確かめられない ({type(e).__name__})"] += 1
            continue
        if rar:
            s["rarity"] = rar
            s["rarity_ebay"] = api.derive_rarity_ebay(CATEGORY, rar)
            s["rarity_source"] = f"official_gap_check_{now[:10]}"
            stat["公式に表示あり → 埋めた"] += 1
            print(f"    + {pid} {rar} ({basis})", flush=True)
        else:
            s[MARK] = now
            s["rarity_official_absent_basis"] = basis
            stat["公式に表示なし (空欄が正)"] += 1
        conn.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                     (json.dumps(s, ensure_ascii=False), now, rid))
        conn.commit()                                # ★1行ごとに保存
        if i % 200 == 0:
            print(f"  {i}/{len(cands)} {dict(stat)}", flush=True)
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print(f"  残りの候補 {len(candidates(conn))}行")


if __name__ == "__main__":
    main()
