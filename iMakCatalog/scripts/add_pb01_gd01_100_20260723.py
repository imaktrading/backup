"""PB01 プレミアムグッズセット -新機動戦記ガンダムW- の GD01-100 再録を登録 — 2026-07-23

依頼: requests/2026-07-23_auto_catalog_add_gundam_tcg.md (cert154708671 "PB01 ... [A SHOW OF
RESOLVE] #100")。

背景:
- PB01 同梱カードは 2種×2枚 (公式 gundam-gcg.com/jp/products/pb01.html で構成確認) =
  GD01-100 覚悟の表れ[Ito画] U+ / ST02-010 ヒイロ・ユイ[Ito画] C+ (+リソース10種)。
- bandai_tcg_plus には両方とも "Promotion Card" として既収録
  (GD01-100_P = api card/105571, rarity U+, source_title 'Mobile Suit Gundam Wing' /
   ST02-010_P = api card/105572, rarity C+, 同上) = 公式 API で刷りの実在は確認済。
- 2026-07-10 (cert154708676 Heero Yuy #010) で `ST02-010_PB01` が clone 登録済だが
  rarity 空のまま。GD01-100 側の PB01 record は未作成 → #100 cert が resolve 不能。

処置 (ST02-010_PB01 と同一 convention):
1. `GD01-100_PB01` を base GD01-100 の clone + rarity 'U+' + set_name PB01 で登録。
2. `ST02-010_PB01` の rarity 空を 'C+' で補完 (同一物理カード ST02-010_P の bandai 公式値)。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

DB = "C:/dev/iMak_data/catalog/products.sqlite"
CAT = "gundam_tcg"
PB01_SET = "プレミアムグッズセット-新機動戦記ガンダムW-[PB01]"
SPEC_SOURCE = "gundam_official_pb01_structure+bandai_tcg_plus_promo_print_20260723"


def main(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 1) GD01-100_PB01 (clone of base, rarity from bandai promo print 105571)
    row = conn.execute(
        "select name, name_jp, specs, images from products where category=? and product_id='GD01-100'",
        (CAT,),
    ).fetchone()
    assert row, "base GD01-100 not found"
    name, name_jp, specs_json, images = row
    specs = json.loads(specs_json)
    specs["rarity"] = "U+"
    specs["variant_type"] = "premium_goods_set_pb01"
    specs["source_title"] = "Mobile Suit Gundam Wing"
    specs["spec_source"] = SPEC_SOURCE
    specs["note"] = (
        "PB01 プレミアムグッズセット同梱の再録 (新規 Ito 画イラスト)。rarity U+ は "
        "bandai_tcg_plus Promotion Card (api card/105571, GD01-100_P と同一刷り) の公式値。"
        "公式 products/pb01.html でセット構成 (カード2種×2) 確認済。"
    )
    exists = conn.execute(
        "select 1 from products where category=? and product_id='GD01-100_PB01'", (CAT,)
    ).fetchone()
    print(f"{'SKIP(exists)' if exists else ('APPLY' if apply else 'DRY ')} GD01-100_PB01 "
          f"rarity=U+ set={PB01_SET}")
    if apply and not exists:
        conn.execute(
            """insert into products
               (category, product_id, name, name_jp, set_name, set_name_official,
                specs, images, source, source_url, created_at, updated_at)
               values (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (CAT, "GD01-100_PB01", name, name_jp, PB01_SET, PB01_SET,
             json.dumps(specs, ensure_ascii=False), images,
             "gundam_official+clone_GD01-100",
             "https://www.gundam-gcg.com/jp/products/pb01.html", now, now),
        )

    # 2) ST02-010_PB01 の rarity 空 → 'C+' (bandai promo print 105572 の公式値)
    r2 = conn.execute(
        "select id, specs from products where category=? and product_id='ST02-010_PB01'", (CAT,)
    ).fetchone()
    if r2:
        rid, sp = r2
        d = json.loads(sp)
        if not d.get("rarity"):
            d["rarity"] = "C+"
            d["spec_source"] = SPEC_SOURCE
            d["note"] = (d.get("note", "") + " " if d.get("note") else "") + (
                "rarity C+ は bandai_tcg_plus Promotion Card (api card/105572, ST02-010_P と同一刷り) の公式値。"
            )
            print(f"{'APPLY' if apply else 'DRY '} ST02-010_PB01 rarity '' → 'C+'")
            if apply:
                conn.execute("update products set specs=?, updated_at=? where id=?",
                             (json.dumps(d, ensure_ascii=False), now, rid))
        else:
            print(f"SKIP ST02-010_PB01 rarity already {d.get('rarity')!r}")
    if apply:
        conn.commit()
    print(f"--- done ({'applied' if apply else 'dry-run'})")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
