"""ポケモンカードゲーム クラシック 3デッキ (CLF / CLK / CLL) をまとめて入れる.

ユーザー GO 2026-08-21 (「①はやって」)。

## なぜ一括なのか
Classic は PSA 依頼が来るたびに1枚ずつ足していた: CLK-008 (7/18) / CLF-001 (8/15) /
CLL-002 (8/20) で **3回目**。発生源の処置として 3デッキ 96枚を一度に入れる。

## 出所 (公式はカードリストを公開していない)
`https://www.pokemon-card.com/ex/classic/index.html` は商品紹介のみで収録リストが無く、
公式カード検索にも Classic は1件も載らない (2026-08-20 実測)。
既存4行も同じ理由で小売/第三者のクロス確認で入っている。今回は**3ソース突合**:

  1. cardrush-pokemon.jp  … 番号 (nnn/032) + 日本語名。3デッキとも 001-032 が揃う
  2. yuyu-tei.jp          … 日本語名。cardrush と 32件全一致
                             (差は表記ゆれのみ: オーキドはかせ/オーキド博士,
                              ボスの指令/サカキ ↔ ボスの指令[サカキ])
  3. bulbapedia           … 日本語版デッキの /032 リスト = **番号と英語名**
                             (英語版は /034 で番号体系も並びも違うので、必ず
                              「Japanese & Traditional Chinese decks」節の方を使う)

3ソースが同じ番号割当を示し、既存4行 (CLF-001/002/015, CLK-008) とも一致した。

## 入れない値 (推測しない)
- rarity は **空が正**。Classic は printed rarity 記号を持たない (小売表記も【-】)。
- HP / イラストレーター / わざ は裏取りできないので入れない。
- images も入れない (公式画像が存在しない)。
- 基本エネルギーは番号を持たない (yuyu-tei に各デッキ2枚あるが /032 の外) ので入れない。

## 英語名について
ハイパーボール → **Ultra Ball** / バトルサーチャー → **VS Seeker** を採用した。
catalog の他 set の行はローマ字寄りの 'Hyper Ball' / 'Battle Searcher' を持っているが、
英語版 Classic の券面はこの2つで、ここは券面表記に合わせる。
(他 set 側をどうするかは別件。触っていない)

実行:
  python migrations/2026-08-21_pokemon_classic_3decks_bulk.py           # dry-run
  python migrations/2026-08-21_pokemon_classic_3decks_bulk.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
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
DATA = Path(__file__).with_name("_classic_cards_20260821.json")

SET_OFFICIAL = {
    "CLF": "ポケモンカードゲーム クラシック フシギバナ&ルギアexデッキ",
    "CLK": "ポケモンカードゲーム クラシック カメックス&スイクンexデッキ",
    "CLL": "ポケモンカードゲーム クラシック リザードン&ホウオウexデッキ",
}
SET_EBAY = "Pokemon Card Game Classic"
SPEC_SOURCE = "cardrush_yuyutei_bulbapedia_crossconfirmed_20260821"
NOTE = ("ポケモンカードゲーム クラシック(2023)。Classic は printed rarity 記号を持たない"
        "(小売表記【-】)= C:Rarity 空が正。公式はカードリスト非公開のため "
        "cardrush / yuyu-tei / bulbapedia の3ソース突合 (2026-08-21 実取得)。"
        "HP / イラストレーター / わざ は裏取り不能のため未収録。")


def process(commit: bool) -> tuple[int, int]:
    decks = json.loads(DATA.read_text(encoding="utf-8"))
    print(f"=== Classic 3デッキ 一括投入 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    added = skipped = 0

    for code in ("CLF", "CLK", "CLL"):
        print(f"\n--- {code}  {SET_OFFICIAL[code]}")
        for num, name_jp, name_en in decks[code]:
            pid = f"{code}-{num}"
            cur = db.execute(
                "SELECT product_id, name, name_en FROM products "
                "WHERE category='pokemon_tcg' AND product_id=?", (pid,)).fetchone()
            if cur:
                # 既存4行。名前が食い違ったら止める (突合の失敗を握り潰さない)
                if cur["name"] != name_jp:
                    print(f"  ✗ {pid} 既存と日本語名が違う: DB={cur['name']!r} / 今回={name_jp!r}")
                    raise SystemExit("既存行と不一致。中断します")
                skipped += 1
                continue

            specs = {
                "card_type": "Pokémon",
                "card_type_ebay": "Pokémon",
                "card_size_ebay": "Standard",
                "game_ebay": "Pokémon TCG",
                "language": "Japanese",
                "set_name_ebay": SET_EBAY,
                "set_name_ebay_source": SPEC_SOURCE,
                "rarity": "",
                "rarity_ebay": "",
                "finish": "Holo",
                "card_number_text": f"{num}/032",
                "character_name": name_en,
                "spec_source": SPEC_SOURCE,
                "note": NOTE,
            }
            print(f"  + {pid}  {name_jp:<18} | {name_en}")
            if commit:
                db.execute(
                    "INSERT INTO products (category, product_id, name, name_jp, name_en, "
                    "name_en_source, set_name, set_name_official, specs, images, source, "
                    "source_url, created_at, updated_at, language) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("pokemon_tcg", pid, name_jp, name_jp, name_en,
                     "bulbapedia_jp_deck_list_20260821", SET_OFFICIAL[code], SET_OFFICIAL[code],
                     json.dumps(specs, ensure_ascii=False), "[]", SPEC_SOURCE,
                     "https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_Trading_Card_Game_Classic",
                     NOW, NOW, "ja"))
            added += 1

    print(f"\n追加 {added} 行 / 既存 skip {skipped} 行")
    if commit:
        db.commit()
        print("✅ 適用")
    else:
        print("(dry-run — --commit で適用)")
    db.close()
    return added, skipped


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
