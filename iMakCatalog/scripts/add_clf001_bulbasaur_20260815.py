"""CLF-001 フシギダネ (ポケモンカードゲーム Classic) を追加.

依頼: requests/2026-08-15_pdca_catalog_queue_tcg.md 層A
      「001/032 【PSA10】ポケモンカード フシギダネ CLF 001/032」(missing_models)

判定 (1丁目1番地): **① 誤 (データ欠落)**。Classic は catalog に CLF-002 / CLF-015 /
CLK-008 の 3 枚しか入っておらず、001 が欠けていた。

出典について (2026-08-15 実取得):
  公式 (pokemon-card.com) は Classic の **カードリストを公開していない**。
  /ex/classic/index.html は商品紹介ページで収録カード一覧が無く、公式カード検索にも
  Classic の番号 (001/032) は出ない。実測済。
  → 先行 3 枚と同じ扱いで、**独立した 2 つの小売カタログでクロス確認**した値のみ入れる:
      - 遊々亭 [CLF] ポケモンカードゲーム Classic「フシギバナ＆ルギアexデッキ」
      - カードラッシュ 「フシギダネ(Classicキラ)【-】{001/032} [CLF]」
    両方が「フシギダネ / 001/032 / CLF / レアリティ表記【-】」で一致。
  裏取りできない項目 (HP・イラストレーター等) は **入れない** (推測禁止)。

rarity: Classic は printed rarity 記号を持たない (小売表記【-】) → 空が正。
        CLF-002 / CLF-015 / CLK-008 と同じ (CP4 と同型)。

実行:
  python scripts/add_clf001_bulbasaur_20260815.py           # dry-run
  python scripts/add_clf001_bulbasaur_20260815.py --commit
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CAT = "pokemon_tcg"
PID = "CLF-001"
SET_OFFICIAL = "ポケモンカードゲーム クラシック フシギバナ&ルギアexデッキ"
SOURCE = "yuyu_tei_cardrush_crossconfirmed"
SOURCE_URL = "https://www.pokemon-card.com/ex/classic/index.html"

SPECS = {
    "card_type": "Pokémon",
    "card_type_ebay": "Pokémon",
    "card_size_ebay": "Standard",
    "game_ebay": "Pokémon TCG",
    "language": "Japanese",
    "set_name_ebay": "Pokemon Card Game Classic",
    "set_name_ebay_source": "free_text_product_name_20260718",
    "rarity": "",
    "rarity_ebay": "",
    "finish": "Holo",
    "card_number_text": "001/032",
    "type": "Grass",
    "character_name": "Bulbasaur",
    "spec_source": "yuyu_tei_cardrush_crossconfirmed_20260815",
    "note": ("ポケモンカードゲーム クラシック(2023). Classic は printed rarity 記号を"
             "持たない(小売表記【-】)= C:Rarity 空が正。CLF-002 / CLK-008 と同型。"
             "公式はカードリスト非公開のため小売2社クロス確認 (2026-08-15 実取得)。"
             "HP / イラストレーターは裏取り不能のため未収録。"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    existing = api.lookup(category=CAT, product_id=PID)
    if existing:
        print(f"既に登録済: {PID} → 投入不要")
        return

    print(f"追加: {CAT} / {PID} フシギダネ (Bulbasaur) 001/032")
    print(f"  set  : {SET_OFFICIAL}")
    print(f"  specs: {json.dumps(SPECS, ensure_ascii=False)[:300]}...")
    if not args.commit:
        print("(dry-run — --commit で適用)")
        return

    api.upsert(
        category=CAT,
        product_id=PID,
        name="フシギダネ",
        name_jp="フシギダネ",
        name_en="Bulbasaur",
        name_en_source=SOURCE,
        specs=SPECS,
        set_name=SET_OFFICIAL,
        set_name_official=SET_OFFICIAL,
        language="Japanese",
        images=[],
        source=SOURCE,
        source_url=SOURCE_URL,
    )
    r = api.lookup(category=CAT, product_id=PID)
    print(f"✅ 登録: {r['product_id']} / {r['name']} / {r['specs'].get('card_number_text')} "
          f"/ set_name_ebay={r['specs'].get('set_name_ebay')!r}")


if __name__ == "__main__":
    main()
