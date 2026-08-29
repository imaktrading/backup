"""3rd ANNIVERSARY SET の収録カードを足す (PSA の cert が出た分だけ 1枚ずつ).

  OP12-079_AN03  ルフィは"海賊王"になる男だ!!!  (cert151301749)  漫画調の単色パラレル
  OP07-118_AN03  サボ                            (cert155570650)  新規絵 + 3rd Anniversary 箔押し

きっかけ: PSA cert151301749 (2025 ONE PIECE JAPANESE 3RD ANNIVERSARY SET #079
LUFFY/KING OF PIRATES / GEM MT 10) が **ブースターの OP12-079 に当たっていた**。
ユーザーが目視画面で「柄は一致しているけど、なんか違う気がする」と止めた。

## 判定 (1丁目1番地): ①カタログのデータが誤り (欠落) → catalog 側で直す

②も同時に直した (別カードを返す fail-open だったため、integrations/psa_to_csv.py に
「その商品限定のカードを名指しされたのに行が無い時は出さない」ガードを追加)。

## 2026-08-26 に実取得して確かめたこと (保存値を根拠にしない)

- PSA スラブ実写 (cert151301749 large): 券面右下に **`OP12-079` `R` `③`**。
  絵柄は **紫の単色・漫画コマ + 金の箔押しタイトル**で、公式 OP12-079 (フルカラー金枠) とは別物。
- 公式画像の別採番は無い:
      OP12-079.png     200
      OP12-079_p.png   404   _p1 404   _p2 404   _p3 404
  → バンダイはこの絵柄を未収録。内部IDは公式が将来使う `_pN` 枠を避けて `_AN03`
    (先例 `EB02-003_CH01` / `OP06-068_AC01` / `ST13-003_7E01`)。
- 商品自体は公式: プレミアムバンダイ「ONEPIECEカードゲーム 3rd ANNIVERSARY SET」
  (抽選 2025-08-29〜09-30 / 19,800円 / プロモ10種 + DON10枚)。
  収録カードの一覧は **公式が公開していない** ので、PSA の cert が出た1枚ずつ足す。

## 値

cost 1 / power - / counter - / color 紫 / block 3 / feature 麦わらの一味 / card_type EVENT /
rarity R は **同じカード番号の公式行 (OP12-079) から複製**。券面の読みと一致する。
`illustration_type` は落とす — base の 'Comic' は通常版の絵柄を指す値で、この単色版が
公式に何と分類されるかは不明 (推測で埋めない)。

images は入れない。公式画像が存在せず、手元にあるのは PSA の写真 (URL が消える) だけ。
目視は PSA cert の写真で足りる。★公式がこの絵を出したら公式値で上書きする。

実行:
  python migrations/2026-08-26_op12_079_an03_3rd_anniversary.py           # dry-run
  python migrations/2026-08-26_op12_079_an03_3rd_anniversary.py --commit
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
SET_OFFICIAL = "3rd ANNIVERSARY SET"   # 1st/2nd と同じ書き方 (公式 get_info の慣習)
VARIANT_TYPE = "anniversary_set_3rd"
_PRODUCT = (
    "プレミアムバンダイ「ONE PIECEカードゲーム 3rd ANNIVERSARY SET」"
    "(抽選 2025-08-29〜09-30 / 19,800円 / プロモ10種 + DON10枚) 収録。"
)

# (base, 新ID, cert, 券面の見え方)
CARDS = [
    ("OP12-079", "OP12-079_AN03", "151301749",
     "券面は紫の単色・漫画コマ + 金の箔押しタイトル。通常版 (フルカラー金枠) とは別絵柄。"
     "券面右下の印字は OP12-079 / R"),
    ("OP07-118", "OP07-118_AN03", "155570650",
     "新規イラスト (赤い炎・Minato Sashima) に 3rd Anniversary の箔押しロゴ。公式の "
     "OP07-118 / _p1 / _p2 / _r1 のどれとも別絵柄。券面右下の印字は OP07-118 / SEC"),
    # 2026-08-29 追記 (この商品は cert が出た分だけ 1枚ずつ足す設計)
    ("ST15-005", "ST15-005_AN03", "152977069",
     "新規イラスト (赤い炎・Makitoshi) に 3rd Anniversary の箔押しロゴ。公式の "
     "ST15-005 / _p1 (SP・Hoshimoto Q) とは別絵柄。券面右下の印字は ST15-005 / SR"),
]

# clone 元から引き継がない spec キー
#   get_info          … この variant では set_official に差し替える
#   illustration_type … base の 'Comic' は通常版の絵柄を指す値。単色版は不明 → 推測しない
DROP_SPEC_KEYS = ("get_info", "illustration_type")


def _add(db, base_pid: str, new_pid: str, cert: str, look: str, commit: bool) -> int:
    BASE, NEW = base_pid, new_pid
    SOURCE = f"clone_{BASE}+psa_cert{cert}_slab_confirmed"
    NOTE = (
        _PRODUCT + look + f" (PSA cert{cert} スラブ実写)。"
        "公式カードリスト未収録・別採番も無い (2026-08-26 に公式画像の _p〜_p3 を実取得して確認) "
        "ため内部IDを _AN03 にした。効果文・コスト等は同じカード番号の公式行からの複製。"
    )

    if db.execute("SELECT 1 FROM products WHERE category=? AND product_id=?",
                  (CAT, NEW)).fetchone():
        print(f"  - {NEW} 既に在る → skip")
        return 0

    b = db.execute("SELECT * FROM products WHERE category=? AND product_id=?",
                   (CAT, BASE)).fetchone()
    if b is None:
        print(f"  ✗ base {BASE} が無い → skip (fail-closed)")
        return 0

    mapped = db.execute(
        "SELECT ebay_value FROM ebay_filter_map WHERE category=? AND field='set' "
        "AND source_value=?", (CAT, SET_OFFICIAL)).fetchone()
    if mapped is None:
        print(f"  ✗ filter_map に set={SET_OFFICIAL!r} が無い → skip "
              f"(先に ebay_filter_map/loader.py one_piece を流す)")
        return 0

    s = json.loads(b["specs"] or "{}")
    for k in DROP_SPEC_KEYS:
        s.pop(k, None)
    s["get_info"] = SET_OFFICIAL
    s["variant_type"] = VARIANT_TYPE
    s["variant_note"] = NOTE
    s["cloned_from"] = BASE            # clone_rows.is_clone → 画像補完が親の絵を入れない
    s["set_name_ebay"] = mapped["ebay_value"]
    s["set_name_ebay_source"] = "clone_promo_20260826"

    print(f"  + {NEW}  base={BASE}")
    print(f"      set_name_official = {SET_OFFICIAL!r}")
    print(f"      set_name_ebay     = {mapped['ebay_value']!r}")
    print(f"      name={b['name']!r} / name_en={b['name_en']!r}")
    print(f"      rarity={s.get('rarity')!r} cost={s.get('cost')!r} "
          f"color={s.get('color')!r} card_type={s.get('card_type')!r}")
    print("      images=[] (公式画像が無いため入れない) / source_url='' (clone 規約)")

    if commit:
        db.execute(
            "INSERT INTO products (category, product_id, name, name_jp, name_en, "
            "name_en_source, set_name, set_name_official, specs, images, source, "
            "source_url, created_at, updated_at, language) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (CAT, NEW, b["name"], b["name_jp"], b["name_en"], b["name_en_source"],
             SET_OFFICIAL, SET_OFFICIAL, json.dumps(s, ensure_ascii=False), "[]",
             SOURCE, "", NOW, NOW, "ja"))
        db.commit()
        print("      OK 追加")
    return 1


def process(commit: bool) -> int:
    print(f"=== 3rd ANNIVERSARY SET 追加 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    n = 0
    for base, new_pid, cert, look in CARDS:
        n += _add(db, base, new_pid, cert, look, commit)
    db.close()
    tail = "適用" if commit else "(dry-run — --commit で適用)"
    print("")
    print(f"{tail} {n} 行")
    return n


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
