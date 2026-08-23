"""EB02-003_CH01 — 集英社『ONE PIECE CHOPPER’s 1』同梱カードのチョッパーを足す.

窓口 GO 2026-08-21 ([IMPLEMENT-GO]):
  requests/2026-08-19_auto_catalog_add_one_piece_tcg_response.md
  requests/2026-08-18_hq_eb02_003_promo_missing_response.md   (同一件・どちらか1回でよい)
値の出所: requests/2026-08-18_eb02_003_chopper_promo_missing_response.md

## 判定 (1丁目1番地): ①カタログのデータが誤り (欠落) → catalog 側で直す

②は正しい。出品くんは canonical KEY (product_id) 完全一致でしか引かず、自由文を作らない。
PSA cert168157614 の現物 (©CHOPPER's Friends / NOT FOR SALE) は公式画像3枚
(EB02-003 / _p / _p1) のいずれとも別絵柄で、catalog に受け皿が無かった。

## 2026-08-23 に公式を再取得して確かめたこと (保存値を根拠にしない)

  https://www.onepiece-cardgame.com/images/cardlist/card/EB02-003.png     200
  https://www.onepiece-cardgame.com/images/cardlist/card/EB02-003_p1.png  200
  https://www.onepiece-cardgame.com/images/cardlist/card/EB02-003_p2.png  404
  https://www.onepiece-cardgame.com/images/cardlist/card/EB02-003_p3.png  404

→ バンダイはこの絵柄を未収録で、公式の `_pN` 枠は今も 2 つまで。**別採番は存在しない**。
  よって内部IDは公式が将来使う枠を避けて `_CH01` にする (先例 `OP06-068_AC01` / `ST07-008_GE`)。

集英社 (isbn 978-4-08-884100-7) も同日再取得:

  <title> ONE PIECE CHOPPER’s 1／『ONE PIECE』（原作：尾田栄一郎）より | 集英社
  本文    【同梱カード】ONE PIECEカードゲーム EB02-003 トニートニー・チョッパー

★書名の apostrophe は **U+2019 '’'** (ASCII の "'" ではない)。回答書は ASCII で書かれて
  いたが、公式表記が正なので '’' を採った。先例 `ONE PIECE DAY’24 来場者特典` と同じ扱い。
  set_name_official と ebay_filter_map のキーは同じ文字で書いてあるので derive は当たる
  (崩すと product_id prefix 'EB02' に fallback して Set が '25th Anniversary Collection' に
   化ける = promo なのに通常セット名で誤出品)。

## 値

cost 3 / power 3000 / counter 1000 / rarity R は同じカード番号なので base EB02-003 から複製。
`illustration_type` は **落とす**。base の 'Anime' は EB-02 (Anime 25th collection) の絵柄を
指す値で、CHOPPER's の絵柄が公式に何と分類されるかは不明。推測で埋めない。

images は入れない。公式画像が存在せず、手元にあるのは PSA/eBay の写真 (URL が消える) だけ。
先例 ST13-003_7E01 と同じ。目視は PSA cert の写真で足りる。

実行:
  python migrations/2026-08-23_eb02_003_ch01_chopper.py           # dry-run
  python migrations/2026-08-23_eb02_003_ch01_chopper.py --commit
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

CAT = "one_piece_tcg"
BASE = "EB02-003"
NEW = "EB02-003_CH01"
# ★U+2019 (’)。集英社の公式書名どおり。ebay_filter_map/one_piece.yaml と同じ文字。
SET_OFFICIAL = "『ONE PIECE CHOPPER’s 1』付録"
VARIANT_TYPE = "chopper1_bundle"
SOURCE = "shueisha_chopper1_bundle+psa_cert168157614"
SOURCE_URL = "https://www.shueisha.co.jp/books/items/contents.html?isbn=978-4-08-884100-7"
NOTE = (
    "集英社『ONE PIECE CHOPPER’s 1』(2026-04-23 発売 / ISBN 978-4-08-884100-7) 同梱カード。"
    "券面は ©CHOPPER's Friends / NOT FOR SALE 表記の promo 絵柄で、公式画像 EB02-003 / _p / _p1 "
    "のいずれとも別絵柄 (PSA cert168157614)。バンダイ未収録で公式の別採番が無いため "
    "(_p2/_p3 は 2026-08-23 再取得でも 404)、内部IDを _CH01 にした (先例 OP06-068_AC01)。"
)

# clone 元から引き継がない spec キー
#   get_info        … この variant では set_official に差し替える
#   illustration_type … base の 'Anime' は EB-02 の絵柄を指す値。CHOPPER's 版は不明 → 推測しない
DROP_SPEC_KEYS = ("get_info", "illustration_type")


def process(commit: bool) -> int:
    print(f"=== {NEW} 追加 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    if db.execute("SELECT 1 FROM products WHERE category=? AND product_id=?",
                  (CAT, NEW)).fetchone():
        print(f"  - {NEW} 既に在る → skip")
        db.close()
        return 0

    b = db.execute("SELECT * FROM products WHERE category=? AND product_id=?",
                   (CAT, BASE)).fetchone()
    if b is None:
        print(f"  ✗ base {BASE} が無い → skip (fail-closed)")
        db.close()
        return 0

    # set_name_official は filter_map の完全一致キーであること (崩れると Set が化ける)
    mapped = db.execute(
        "SELECT ebay_value FROM ebay_filter_map WHERE category=? AND field='set' "
        "AND source_value=?", (CAT, SET_OFFICIAL)).fetchone()
    if mapped is None:
        print(f"  ✗ filter_map に set={SET_OFFICIAL!r} が無い → skip "
              f"(先に ebay_filter_map/loader.py one_piece を流す)")
        db.close()
        return 0

    s = json.loads(b["specs"] or "{}")
    for k in DROP_SPEC_KEYS:
        s.pop(k, None)
    s["get_info"] = SET_OFFICIAL
    s["variant_type"] = VARIANT_TYPE
    s["variant_note"] = NOTE
    # 契約 v1.2 §1-5: stored に焼く (restamp 方式)
    s["set_name_ebay"] = mapped["ebay_value"]
    s["set_name_ebay_source"] = "clone_promo_20260823"

    print(f"  + {NEW}  base={BASE}")
    print(f"      set_name_official = {SET_OFFICIAL!r}")
    print(f"      set_name_ebay     = {mapped['ebay_value']!r}")
    print(f"      name={b['name']!r} / name_jp={b['name_jp']!r} / name_en={b['name_en']!r}")
    print(f"      rarity={s.get('rarity')!r} cost={s.get('cost')!r} "
          f"power={s.get('power')!r} counter={s.get('counter')!r}")
    print(f"      images=[] (公式画像が無いため入れない)")

    if commit:
        db.execute(
            "INSERT INTO products (category, product_id, name, name_jp, name_en, "
            "name_en_source, set_name, set_name_official, specs, images, source, "
            "source_url, created_at, updated_at, language) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (CAT, NEW, b["name"], b["name_jp"], b["name_en"], b["name_en_source"],
             SET_OFFICIAL, SET_OFFICIAL, json.dumps(s, ensure_ascii=False), "[]",
             SOURCE, SOURCE_URL, NOW, NOW, "ja"))
        db.commit()
        print("\n✅ 適用 1 行")
    else:
        print("\n(dry-run — --commit で適用)")
    db.close()
    return 1


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
