# -*- coding: utf-8 -*-
"""「ミュウツーVSゲノセクト」の2デッキを ID で分ける + 混ざった英語名を直す (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが誤り**。公式を今その場で取り直して確認した。

## 何が起きていたか

公式 `30枚デッキ対戦set「ミュウツーVSゲノセクト」` は **2つのデッキ**で、
**収録商品名が同じ・番号も同じ 001〜016**。catalog の鍵は `MG-001` 1つなので、
2デッキが1つの行を奪い合っていた。実測 (公式 cardID で確認):

    ゲノセクト側 cardID 28759〜28775   ミュウツー側 cardID 28776〜28792

結果、catalog の MG-001〜016 は **2デッキの混ざり物**で、しかも
`name_en` に **別デッキのカード名**が入っていた:

    MG-001  name_jp='ミュウツー'      name_en='Tangela'   (=モンジャラ / ゲノセクト側 001)
    MG-008  name_jp='ユニラン'        name_en='Genesect'  (=ゲノセクト / ゲノセクト側 008)
    MG-009  name_jp='クラッシュハンマー' name_en='Energy Switch' (=エネルギーつけかえ)

このまま出すと **絵と英語名が別のカード** = 誤出品。

## 直し方

1. `name_en` を JP 名から引き直す (ポケモン名は PokeAPI、トレーナーズは api 辞書)。
2. ゲノセクト側で **番号が衝突して入れられなかった 10枚**を `MG-G-###` で入れる
   (前例 `S8a-G` / `SCS-C`)。**先に入っている MG-* は動かさない** (出品で使う鍵を変えない)。

★010/011/012/014/015/016 は **両デッキに同じカードが入っている**ので1行のままでよい
  (絵の刷り違いだけ。公式突合では「別刷り」に数える)。

## 出品くんが引けること

PSA のラベルは両デッキとも `MEWTWO VS GENESECT` で、**ラベルからはデッキを決められない**。
そこで `integrations/psa_to_csv.py` に「兄弟デッキ」を持たせ、
`MG` で引いて名前が合わなければ `MG-G` を見る (名前照合で決める)。

実行:
  python migrations/2026-09-05_mg_deck_split.py [--commit]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import pokemon_name_translation as T  # noqa: E402
import pokemon_tcg as P  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
SRC = "mg_deck_split_20260905"

# ゲノセクト側で **番号が衝突して入れられなかった** cardID (公式 001〜009, 013)。
# 010/011/012/014/015/016 は ミュウツー側と同じカードなので入れない (上の説明)。
GENESECT_IDS = ["28759", "28760", "28761", "28762", "28763",
                "28764", "28765", "28766", "28767", "28771"]
SUFFIX = "MG-G"


def _en(name_jp: str, d1: dict, d2: dict) -> str:
    g = T.resolve_name_en(name_jp, d1, d2)
    got = g[0] if isinstance(g, tuple) else g
    return got or d2.get(name_jp) or ""      # トレーナーズは api 辞書 (既存 MG 行と同じ出所)


def run(commit: bool) -> None:
    d1, d2 = T.load_pokeapi_dict(), T.load_api_dict()
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row

    # --- 1. 混ざった name_en を直す -------------------------------------
    fix = []
    for r in db.execute("SELECT id, product_id, name_jp, name_en FROM products "
                        "WHERE category='pokemon_tcg' AND product_id LIKE 'MG-0%'"):
        want = _en(r["name_jp"] or "", d1, d2)
        if want and want != (r["name_en"] or ""):
            fix.append((r["id"], r["product_id"], r["name_jp"], r["name_en"], want))
    print(f"=== 1. 別デッキの英語名 ({'APPLY' if commit else 'DRY-RUN'}) — {len(fix)}行 ===")
    for _, pid, jp, old, new in fix:
        print(f"    {pid:10s} {jp:14s} {old!r} -> {new!r}")
    if commit:
        for _id, _pid, _jp, _old, new in fix:
            db.execute("UPDATE products SET name_en=?, name_en_source=?, updated_at=? WHERE id=?",
                       (new, SRC, NOW, _id))
        db.commit()
    db.close()

    # --- 2. ゲノセクト側を MG-G-### で入れる ----------------------------
    print(f"\n=== 2. ゲノセクトデッキの投入 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    added = 0
    for cid in GENESECT_IDS:
        d = P.get_detail(cid)
        if not d:
            print(f"    ✗ cardID {cid} 公式が取れない → 飛ばす")
            continue
        pid = f"{SUFFIX}-{d.get('card_number')}"
        if api.lookup("pokemon_tcg", pid) is not None:
            print(f"    · {pid} 済み")
            continue
        name = d.get("name", "")
        print(f"    + {pid:10s} {name}")
        if commit:
            api.upsert(
                category="pokemon_tcg", product_id=pid,
                name=name, name_jp=name, name_en=_en(name, d1, d2),
                set_name=d.get("set_name_official"),
                set_name_official=d.get("set_name_official"),
                card_set_id=None, language="ja",
                specs=P.build_specs(d),
                images=[d["image_url"]] if d.get("image_url") else [],
                source=P.SOURCE, source_url=f"{P.DETAIL_BASE}/{cid}",
            )
            added += 1
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'} "
          f"英語名 {len(fix)}行 / 投入 {added}枚")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
