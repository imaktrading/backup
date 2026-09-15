"""日本語版の旧セット 31組に焼かれていた「英語版の別セット名」を、その弾自身の値に直す — 2026-09-15

## 何が誤っていたか
2026-08-23 ユーザー確定「③ 英語版の別セット名を使う → 禁止。例外は作らない」の後も、
XY / XY BREAK / DP / DPt / BW / LEGEND の日本語版セットに英語版のセット名が残っていた:

    拡張パック「赤い閃光」 / 「青い衝撃」      -> Breakthrough        (英語版 XY8)
    拡張パック「湖の秘密」                    -> Mysterious Treasures
    拡張パック「秘境の叫び」 / 「怒りの神殿」  -> Legends Awakened    ほか (計 1,580行)

8/10 の `ssot_canonical_upgrade_20260810` 等で焼かれ、8/23 の決め直しで洗い直していなかった
(CLAUDE.md 追記⑤ の形)。§0c (別セットの名前) は弾コードで始まる値しか見ないので、コードの無い古い値を拾えなかった。
見つけたのは週次の整合性チェック §5 (map潰れ: 2つの日本語セットが1つの eBay 値に潰れている)。

## どう直すか
    ① eBay master (Pokémon TCG) に日本語版の値が在る → それ
       (破空の激闘 = Intense Fight in the Destroyed Sky / 頂上大激突 = L3: Clash at the Summit / DPt ギフトボックス3種)
    ② 無い → 日本語セット名の英語表記。**英訳は Bulbapedia の日本語版セット一覧で確認した名前**
       (倉庫: `_raw/pokemon_tcg/bulbapedia_jp_expansions_20260915.txt.gz`)
       既に登録簿にある値 (HeartGold Collection 等) はそれに合わせる

変換表 (`ebay_filter_map/pokemon.yaml` の set) に同日追加・修正済み。ここでは DB の焼き直しだけをする。
★`tools/restamp_set_name_ebay.py` は「今の値が eBay 一覧に在れば触らない (格下げ禁止)」ので、
  一覧に在る英語版の名前 (Breakthrough 等) を直せない。だから専用に書く。

## 安全
- 今の値が **表の「旧」と一致する行だけ**書く。違う値の行は触らない
- 書く値は **変換表から引き直した値** (`api.derive_set_name_ebay`) と一致することを確かめてから書く
- 前後の件数を出す。残り 0 で閉じる

実行:
    python migrations/2026-09-15_pokemon_jp_old_sets_own_value.py            # dry-run
    python migrations/2026-09-15_pokemon_jp_old_sets_own_value.py --commit
"""
from __future__ import annotations

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

SOURCE = "jp_old_set_own_value_20260915"

# set_name_official -> (旧 = 英語版の別セット, 新)
FIX = {
    "ポケモンカードゲームDP 拡張パック「ひかる闇」": ("Secret Wonders", "Shining Darkness"),
    "ポケモンカードゲームDP 拡張パック「湖の秘密」": ("Mysterious Treasures", "Secret of the Lakes"),
    "ポケモンカードゲームDP 拡張パック「破空の激闘」": ("Stormfront", "Intense Fight in the Destroyed Sky"),
    "拡張パック「時空の創造 ダイヤモンドコレクション」": ("Diamond & Pearl", "Space-Time Creation: Diamond Collection"),
    "拡張パック「時空の創造 パールコレクション」": ("Diamond & Pearl", "Space-Time Creation: Pearl Collection"),
    "ポケモンカードゲームXY 拡張パック「ライジングフィスト」": ("XY - Furious Fists", "Rising Fist"),
    "ポケモンカードゲームXY 拡張パック「ファントムゲート」": ("XY - Phantom Forces", "Phantom Gate"),
    "ポケモンカードゲームXY 拡張パック「バンデットリング」": ("XY - Ancient Origins", "Bandit Ring"),
    "ポケモンカードゲームXY 拡張パック「エメラルドブレイク」": ("Roaring Skies", "Emerald Break"),
    "ポケモンカードゲームXY BREAK 拡張パック「めざめる超王」": ("Fates Collide", "Awakening Psychic King"),
    "拡張パック「めざめる超王」": ("Fates Collide", "Awakening Psychic King"),
    "拡張パック「夜明けの疾走」": ("Majestic Dawn", "Dawn Dash"),
    "拡張パック「月光の追跡」": ("Great Encounters", "Moonlit Pursuit"),
    "拡張パック「怒りの神殿」": ("Legends Awakened", "Temple of Anger"),
    "拡張パック「秘境の叫び」": ("Legends Awakened", "Cry from the Mysterious"),
    "ポケモンカードゲームXY BREAK 拡張パック「青い衝撃」": ("Breakthrough", "Blue Shock"),
    "拡張パック「青い衝撃」": ("Breakthrough", "Blue Shock"),
    "ポケモンカードゲームXY BREAK 拡張パック「赤い閃光」": ("Breakthrough", "Red Flash"),
    "拡張パック「赤い閃光」": ("Breakthrough", "Red Flash"),
    "ポケモンカードゲームXY BREAK 拡張パック「冷酷の反逆者」": ("XY - Steam Siege", "Cruel Traitor"),
    "拡張パック「冷酷の反逆者」": ("XY - Steam Siege", "Cruel Traitor"),
    "ポケモンカードゲームXY BREAK 拡張パック「爆熱の闘士」": ("XY - Steam Siege", "Fever-Burst Fighter"),
    "拡張パック「爆熱の闘士」": ("XY - Steam Siege", "Fever-Burst Fighter"),
    "ポケモンカードゲームBW 拡張パック「ドラゴンセレクション」": ("Dragon Vault", "Dragon Selection"),
    "拡張パック「ハートゴールドコレクション」": ("Heartgold & Soulsilver", "HeartGold Collection"),
    "拡張パック「ソウルシルバーコレクション」": ("Heartgold & Soulsilver", "SoulSilver Collection"),
    "拡張パック「破天の怒り」": ("Breakpoint", "Rage of the Broken Heavens"),
    "拡張パック「頂上大激突」": ("Triumphant", "L3: Clash at the Summit"),
    "強化拡張パック「サン＆ムーン」": ("Sun & Moon", "Enhanced Expansion Pack Sun & Moon"),   # eBay の Sun & Moon は英語版の基本セット
    "ポケモンカードゲームDPtギフトボックス（ナエトルデッキ）": ("Platinum", "DPt Gift Box (Turtwig)"),
    "ポケモンカードゲームDPtギフトボックス（ヒコザルデッキ）": ("Platinum", "DPt Gift Box (Chimchar)"),
    "ポケモンカードゲームDPtギフトボックス（ポッチャマデッキ）": ("Platinum", "DPt Gift Box (Piplup)"),
    "ポケモンカードゲームDPt エントリーパック(ギラティナデッキ)": ("Platinum", "DPt Entry Pack (Giratina)"),
    "ポケモンカードゲームDPt エントリーパック(ディアルガデッキ)": ("Platinum", "DPt Entry Pack (Dialga)"),
    "ポケモンカードゲームDPt エントリーパック(パルキアデッキ)": ("Platinum", "DPt Entry Pack (Palkia)"),
}


def main(commit: bool) -> None:
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    now = datetime.now().isoformat(timespec="seconds")
    stat, todo, mismatch = Counter(), [], []
    for son, (old, new) in FIX.items():
        for rid, pid, sp in db.execute(
                "SELECT id, product_id, specs FROM products WHERE category='pokemon_tcg' "
                "AND set_name_official=?", (son,)).fetchall():
            s = json.loads(sp or "{}")
            stored = s.get("set_name_ebay")
            if stored == new:
                stat["既に新しい値"] += 1
                continue
            if stored != old:
                stat[f"旧と違う値なので触らない ({stored})"] += 1
                continue
            derived = api.derive_set_name_ebay("pokemon_tcg", son, pid)
            if derived != new:
                mismatch.append((pid, son, derived))
                continue
            todo.append((rid, s, old, new))
            stat["書く"] += 1
    if mismatch:
        print(f"★変換表から引いた値が合わない {len(mismatch)}行 — 書かずに止める: {mismatch[:5]}")
        return
    if commit:
        for rid, s, old, new in todo:
            s["set_name_ebay"] = new
            s["set_name_ebay_source"] = SOURCE
            s["set_name_ebay_prev"] = old
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), now, rid))
        db.commit()
    left = sum(db.execute(
        "SELECT count(*) FROM products WHERE category='pokemon_tcg' AND set_name_official=? "
        "AND json_extract(specs,'$.set_name_ebay')=?", (son, old)).fetchone()[0]
        for son, (old, _) in FIX.items())
    for k, v in stat.most_common():
        print(f"  {k}: {v}")
    print(f"英語版の別セット名の残り {left}行 / {'commit' if commit else 'dry-run'}")


if __name__ == "__main__":
    main("--commit" in sys.argv)
