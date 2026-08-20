"""欠けている promo 2行を base から clone して足す.

ユーザー GO 2026-08-21 (① = GIRLS EDITION ペローナ / ② = 7-ELEVEN ルフィ)。

## 1. OP01-077_GE — プレミアムカードコレクション -GIRLS EDITION- のペローナ
依頼: requests/2026-08-20_pdca_catalog_queue_tcg_response.md §2 (cert86028605)
公式 cardlist は GIRLS EDITION を1枚も載せていない (550801 の get_info 25種に無し) ので、
先例 `ST07-008_GE` (2026-07-10) と同じく base からの clone にする。
②側 (psa_to_csv の GIRLS EDITION edition pair) は 2026-07-10 に配線済 = 行が在れば当たる。

## 2. ST13-003_7E01 — 7-ELEVEN キャンペーンのルフィ (LEADER)
依頼: requests/2026-08-20_pdca_catalog_queue_tcg_question.md (cert155606219 / 145597172)
**現物で確定した (2026-08-21)**。PSA cert 145597172 を実取得し、同一カードの
PSA10 スラブ写真 (cert 143959180 / 163608761) で券面を目視:

    ラベル : 2024 ONE PIECE JAPANESE PROMOS #003 MONKEY D. LUFFY / Variety = 7-ELEVEN CAMPAIGN
    券面   : モンキー・D・ルフィ / LEADER / 5000 / ライフ4 / 超新星・麦わらの一味
    左下印字: ST13-003        ← カード番号は ST13-003 で確定

catalog の ST13-003 系 5行が持つ絵柄は2種類だけ (base=金背景 / _p1=モノクロ parallel) で、
現物の赤ジャケット・波背景の絵柄はどちらでもない。よって **①catalog の欠落**。
公式 (Bandai API / cardlist) には無いことも実測済 (requests/2026-08-20_hq_st13_003_..._response.md)。

★set_name_official は `ebay_filter_map` の完全一致キーをそのまま使う。
  ('セブンイレブンタイアップキャンペーン オリジナルカード' -> 'Promo Cards' は登録済)
  ここを崩すと derive が product_id prefix ST13 に fallback して
  Set が 'The Three Brothers' に化ける (= promo なのに通常セット名で誤出品)。

images は入れない。公式画像が存在せず、手元にあるのは eBay の出品写真 (URL が消える) だけのため。
目視は PSA cert の写真で足りる。

実行:
  python migrations/2026-08-21_op01_077_ge_and_st13_003_7eleven.py           # dry-run
  python migrations/2026-08-21_op01_077_ge_and_st13_003_7eleven.py --commit
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

CLONES = [
    {
        "base": "OP01-077",
        "new": "OP01-077_GE",
        "set_official": "プレミアムカードコレクション -GIRLS EDITION-",
        "variant_type": "premium_card_collection_girls_edition",
        "source": "opcg_official+clone_OP01-077",
        "source_url": "https://www.onepiece-cardgame.com/cardlist/?series=550101",
        "note": ("プレミアムカードコレクション -GIRLS EDITION- 収録の parallel。"
                 "公式 cardlist が GIRLS EDITION を掲載しないため base からの clone "
                 "(先例 ST07-008_GE)。PSA cert86028605。"),
    },
    {
        "base": "ST13-003",
        "new": "ST13-003_7E01",
        "set_official": "セブンイレブンタイアップキャンペーン オリジナルカード",
        "variant_type": "seven_eleven_campaign",
        "source": "clone_ST13-003+psa_cert145597172_slab_confirmed",
        "source_url": "https://www.psacard.com/ja-JP/cert/145597172/psa",
        "note": ("7-ELEVEN キャンペーン配布の LEADER parallel。公式 (Bandai API / cardlist) に "
                 "掲載が無く、PSA スラブ実写で券面 'ST13-003' を目視確定 (2026-08-21)。"
                 "catalog の既存 ST13-003 系 5行はいずれも別絵柄。"),
    },
]

# clone 元から引き継がない (= その variant では別値 or 未確定になる) キー
DROP_SPEC_KEYS = ("get_info", "images_source_note")


def _restamp_existing(db: sqlite3.Connection, c: dict, commit: bool) -> bool:
    """既に入れた行の specs.set_name_ebay が空なら埋める (不変条件テスト対策)."""
    r = db.execute("SELECT id, specs FROM products WHERE category='one_piece_tcg' "
                   "AND product_id=?", (c["new"],)).fetchone()
    m = db.execute("SELECT ebay_value FROM ebay_filter_map WHERE category='one_piece_tcg' "
                   "AND field='set' AND source_value=?", (c["set_official"],)).fetchone()
    if r is None or m is None:
        return False
    s = json.loads(r["specs"] or "{}")
    if s.get("set_name_ebay") == m["ebay_value"]:
        return False
    s["set_name_ebay"] = m["ebay_value"]
    s["set_name_ebay_source"] = "clone_promo_20260821"
    if commit:
        db.execute("UPDATE products SET specs = ?, updated_at = ? WHERE id = ?",
                   (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    return True


def process(commit: bool) -> int:
    print(f"=== promo clone 追加 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    added = 0

    for c in CLONES:
        exists = db.execute(
            "SELECT 1 FROM products WHERE category='one_piece_tcg' AND product_id=?",
            (c["new"],)).fetchone()
        if exists:
            fixed = _restamp_existing(db, c, commit)
            print(f"  - {c['new']:<16} 既に在る → skip" + ("  (specs.set_name_ebay を restamp)" if fixed else ""))
            continue

        b = db.execute(
            "SELECT * FROM products WHERE category='one_piece_tcg' AND product_id=?",
            (c["base"],)).fetchone()
        if b is None:
            print(f"  ✗ {c['new']:<16} base {c['base']} が無い → skip (fail-closed)")
            continue

        # set_name_official は filter_map の完全一致キーであること (崩れると Set が化ける)
        mapped = db.execute(
            "SELECT ebay_value FROM ebay_filter_map WHERE category='one_piece_tcg' "
            "AND field='set' AND source_value=?", (c["set_official"],)).fetchone()
        if mapped is None:
            print(f"  ✗ {c['new']:<16} filter_map に set={c['set_official']!r} が無い → skip")
            continue

        s = json.loads(b["specs"] or "{}")
        for k in DROP_SPEC_KEYS:
            s.pop(k, None)
        s["get_info"] = c["set_official"]
        s["variant_type"] = c["variant_type"]
        s["variant_note"] = c["note"]
        # 契約 v1.2 §1-5: stored に焼く (restamp 方式)。
        # 落とすと canonical fresh 不変条件テストに引っかかる。
        s["set_name_ebay"] = mapped["ebay_value"]
        s["set_name_ebay_source"] = "clone_promo_20260821"

        print(f"  + {c['new']:<16} base={c['base']} set={c['set_official']!r} -> {mapped['ebay_value']!r}")
        print(f"      name={b['name']!r} / {b['name_en']!r} rarity={s.get('rarity')!r}")

        if commit:
            db.execute(
                "INSERT INTO products (category, product_id, name, name_jp, name_en, "
                "name_en_source, set_name, set_name_official, specs, images, source, "
                "source_url, created_at, updated_at, language) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("one_piece_tcg", c["new"], b["name"], b["name_jp"], b["name_en"],
                 b["name_en_source"], c["set_official"], c["set_official"],
                 json.dumps(s, ensure_ascii=False), "[]", c["source"],
                 c["source_url"], NOW, NOW, "ja"))
        added += 1

    print(f"\n追加 {added} 行")
    if commit:
        db.commit()
        print("✅ 適用")
    else:
        print("(dry-run — --commit で適用)")
    db.close()
    return added


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
