"""DON!! PRB02 character-key POC: Buggy/Shanks (Gold) を character 付きで登録 — 2026-07-25

依頼: requests/2026-07-25_don_prb02_character_poc.md (HQ POC go)。
背景: DON-PRB02-* は 90件 generic (psa_subject_hint=["PRB-02","#NNN"], character 無) で、
PSA Subject "DON!! CARD" だけでは 90-way tie で一意特定不能。HQ が cert cache の Vision
character を「正」として lookup_don(vision_character=...) に渡せることを確認 → character
一致キーで一意化する。

本 POC: PRB02 の Buggy / Shanks (Gold) 2件を character 付きで登録。resolver 側の
vision_character 一致キー (psa_to_csv.lookup_don) と対で E2E 解決させる。
- product_id は Catalog 内部 KEY (公式 card_number 不在)。character を含む記述 id を採用。
- 既存 generic DON-PRB02-NNN との物理重複可能性は POC 段では許容 (vision_character 経路でのみ
  解決し、generic は score=0 tie で fail-closed skip のため二重出品にならない)。本実装で整合予定。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

DB = "C:/dev/iMak_data/catalog/products.sqlite"
CAT = "one_piece_tcg"
SET_OFFICIAL = "プレミアムブースター ONE PIECE CARD THE BEST Vol.2 [PRB-02]"

# HQ提供 Vision character = 権威値 (requests/2026-07-25_don_prb02_character_poc.md)
TARGETS = [
    {"pid": "DON-PRB02-BUGGY-GOLD", "character": "Buggy", "treatment": "Gold (Alt Art)",
     "cert": "152976738"},
    {"pid": "DON-PRB02-SHANKS-GOLD", "character": "Shanks", "treatment": "Gold",
     "cert": "158452517"},
]


def build_specs(character: str, treatment: str) -> dict:
    return {
        "card_type": "DON!! Card",
        "set_code": "PRB02",
        "source_note": SET_OFFICIAL,
        # psa_subject_hint は **空**: これらは vision_character 一致キー専用の record。
        #   hint を持たせると generic な subject 'DON!! CARD' が他 DON(KUMAMON 等)の
        #   subject に混入して tie を作る (2026-07-25 test_kumamon_zoro 回帰で発覚)。
        #   hint scoring からは除外し、vision_character 経路でのみ解決させる (fail-closed)。
        "psa_subject_hint": [],
        "character": character,          # ← vision_character 一致キー (2026-07-25)
        "treatment": treatment,
        "catalog_internal_key_note": (
            "公式 card_number 不在; Catalog 内部 dedup KEY; eBay 'C:Card Number' 列には送信せず、"
            "AI 列 (= dedup index) で利用。character は Vision(cert cache)= 正 で登録 (HQ承認)。"),
        "card_size_ebay": "Standard",
        "game_ebay": "One Piece CCG",
        "language": "Japanese",
        "finish": "",
        "character_name": "DON!! Card",
        "set_name_ebay": "Premium Booster Vol.2",
        "set_name_ebay_source": "mirror_don_prb02_generic_20260725",
        "spec_source": "HQ_vision_character_authoritative_20260725",
    }


def main(apply: bool) -> None:
    conn = sqlite3.connect(DB)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for t in TARGETS:
        exists = conn.execute(
            "select 1 from products where category=? and product_id=?", (CAT, t["pid"])
        ).fetchone()
        specs = build_specs(t["character"], t["treatment"])
        print(f"{'SKIP(exists)' if exists else ('APPLY' if apply else 'DRY ')} {t['pid']} "
              f"character={t['character']} treatment={t['treatment']} (cert {t['cert']})")
        if apply and not exists:
            conn.execute(
                """insert into products
                   (category, product_id, name, name_jp, set_name, set_name_official,
                    specs, images, source, source_url, created_at, updated_at)
                   values (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (CAT, t["pid"], "DON!! Card", "ドン!! カード", "DON!! Card", SET_OFFICIAL,
                 json.dumps(specs, ensure_ascii=False), "[]",
                 "HQ_vision_character_poc", "", now, now),
            )
    if apply:
        conn.commit()
    print(f"--- done ({'applied' if apply else 'dry-run'})")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
