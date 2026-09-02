"""OP-17 / SD-01 の新規 178行に、出品に出る値を付ける (2026-09-02).

きっかけ: 公式突合ツール (`tools/official_drift_check.py`) を作って走らせたら、公式に
在って catalog に無いカードが出た → `scrapers/one_piece_tcg.py --update` を流した。
scraper が入れるのは **公式の生値だけ**なので、そのままでは出品に出る値が空のまま
(定数5項目・Set・Rarity・Card Type)。テスト5本が落ちる状態になる。

★これが「取り込んだのに出せない」の正体。新弾を入れたら **必ずここまでやる**
  (memory `tcg_newset_ingest_flow` の定型。normalize → phase_b → 定数 → Set/種別)。

このスクリプトは残りの4つを埋める:

    game_ebay / manufacturer_ebay  … category ごとの定数 (api.derive_*)
    card_type_ebay                 … 既存行と同じ対応 (Character / Event / Leader / Stage)
    set_name_ebay                  … 変換表から導出 (api.derive_set_name_ebay)

`card_size_ebay` / `language` / `country_of_origin_ebay` は既存の定数 migration で、
`rarity_ebay` は phase_b で埋め済み。

実行:
  python migrations/2026-09-02_op17_ingest_finish.py
  python migrations/2026-09-02_op17_ingest_finish.py --commit
"""
from __future__ import annotations

import argparse
import json
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

NOW = datetime.now().isoformat(timespec="seconds")
CAT = "one_piece_tcg"
# 既存 8,729行が使っている対応をそのまま踏襲する (新しい語彙は作らない)
CARD_TYPE = {"CHARACTER": "Character", "Character": "Character", "キャラクター": "Character",
             "EVENT": "Event", "Event": "Event", "イベント": "Event",
             "LEADER": "Leader", "Leader": "Leader", "リーダー": "Leader",
             "STAGE": "Stage", "Stage": "Stage", "ステージ": "Stage",
             "DON!! Card": "DON!! Card"}


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, product_id, set_name_official, specs FROM products "
        "WHERE category=? AND IFNULL(json_extract(specs,'$.game_ebay'),'')=''",
        (CAT,)).fetchall()
    print(f"=== OP 新規行の仕上げ ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(rows)}行 ===")
    game, maker = api.derive_game_ebay(CAT), api.derive_manufacturer(CAT)
    filled, unmapped = Counter(), []
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        s["game_ebay"] = game
        s["manufacturer_ebay"] = maker
        filled["game_ebay"] += 1
        filled["manufacturer_ebay"] += 1
        ct = CARD_TYPE.get(str(s.get("card_type") or "").strip())
        if ct:
            s["card_type_ebay"] = ct
            filled["card_type_ebay"] += 1
        elif s.get("card_type"):
            unmapped.append((r["product_id"], "card_type", s.get("card_type")))
        sn = api.derive_set_name_ebay(CAT, r["set_name_official"], r["product_id"])
        if sn:
            s["set_name_ebay"] = sn
            s["set_name_ebay_source"] = "op17_ingest_20260902"
            filled["set_name_ebay"] += 1
        else:
            unmapped.append((r["product_id"], "set", r["set_name_official"]))
        if commit:
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    if commit:
        db.commit()
    db.close()
    for k, v in filled.items():
        print(f"  + {k:18s} {v}行")
    if unmapped:
        print(f"  ★変換表に無い {len(unmapped)}件 (fail-closed: 空欄のまま)")
        for pid, kind, v in unmapped[:8]:
            print(f"      {pid} {kind}={v!r}")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
