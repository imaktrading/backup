# -*- coding: utf-8 -*-
"""同じ商品が英語名と日本語名の2通りで入っていたのを公式 (日本語) に揃える (2026-09-05).

判定 (1丁目1番地): **①カタログのデータ**。誤りではないが、**同じ商品が2つの名前**で
入っていた。公式 (onepiece-cardgame.com) の書き方に揃える。

    BOOSTER PACK -THE WORLD’S STRONGEST WARRIORS- [OP-17]  ->  ブースターパック 世界最強の戦士【OP-17】   156行
    BOOSTER PACK -ADVENTURE ON KAMI’S ISLAND- [OP15-EB04]  ->  ブースターパック 神の島の冒険【OP-15】     141行

★eBay に出る値は **変わらない** (両方とも `The World’s Strongest Warriors` /
  `Adventure on Kami's Island` を導出する。適用前に1行ずつ確認済み)。
  変わるのは catalog の中の書き方の統一だけ。

なぜやるか: 同じ商品が2つの名前で入っていると、あとから「どちらが正か」を毎回考えることになる。
公式の書き方1つに寄せておけば、次に公式と突き合わせた人が同じ判断をしなくて済む。

実行:
  python migrations/2026-09-05_op_setname_jp_unify.py [--commit]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import api  # noqa: E402
import official_drift_check as O  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
SERIES = ["550901", "550801", "550204", "550115", "550117"]


def run(commit: bool) -> None:
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    fix, why, skip = [], Counter(), Counter()
    for sid in SERIES:
        page = O._get(O.LIST_URL.format(sid=sid))
        for b in re.split(r'(?=<dl class="modalCol")', page)[1:]:
            mid = re.search(r'<dl class="modalCol" id="([^"]+)"', b)
            mget = re.search(r'class="getInfo"><h3>[^<]*</h3>(.*?)</div>', b, re.S)
            if not (mid and mget):
                continue
            pid = mid.group(1)
            want = O._norm(re.sub(r"<[^>]+>", " ", mget.group(1)))
            r = db.execute("SELECT id, set_name_official, specs FROM products "
                           "WHERE category='one_piece_tcg' AND product_id=?", (pid,)).fetchone()
            if not r or O._norm(r["set_name_official"] or "") == want:
                continue
            now_v = api.derive_set_name_ebay("one_piece_tcg", r["set_name_official"], pid)
            new_v = api.derive_set_name_ebay("one_piece_tcg", want, pid)
            if now_v != new_v:
                # ★eBay に出る値が変わるものは **やらない** (別の話になる)
                skip[f"{r['set_name_official']} -> {want}"] += 1
                continue
            fix.append((r["id"], want))
            why[f"{(r['set_name_official'] or '')[:40]} -> {want[:32]}"] += 1

    print(f"=== 商品名を公式 (日本語) に統一 ({'APPLY' if commit else 'DRY-RUN'}) — {len(fix)}行 ===")
    for k, v in why.most_common(10):
        print(f"    {v:4d}行  {k}")
    if skip:
        print("  ★eBay の値が変わるので触らないもの:")
        for k, v in skip.most_common(5):
            print(f"      {v:4d}行  {k}")
    done = 0
    if commit:
        for _id, want in fix:
            db.execute("UPDATE products SET set_name=?, set_name_official=?, updated_at=? "
                       "WHERE id=?", (want, want, NOW, _id))
            done += 1
            if done % 50 == 0:
                db.commit()
        db.commit()
    db.close()
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} {len(fix)} 行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
