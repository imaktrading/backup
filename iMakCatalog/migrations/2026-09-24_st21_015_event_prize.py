# -*- coding: utf-8 -*-
"""ST21-015 のオフィシャルイベント賞品版を登録する (2026-09-24).

依頼: `requests/2026-09-24_auto_catalog_add_one_piece_tcg.md` (cert176142085)
判定: ①カタログのデータ不足。catalog の ST21-015 系3行はどれも**赤い通常絵**で、
      現物 (PSA ラベル `OFFICIAL EVENT PRIZE`) は**青い名前枠の別絵柄**。

公式に無いことを今その場で確認 (2026-09-24):
    onepiece-cardgame.com  ST21-015_p2 / _p3 / _r1 -> 404 (在るのは ST21-015 と _p1 だけ)
    bandai-tcg-plus  OP-JA/P/ST21-015*.png -> 403 (プロモ側にも無い)

値の出所 (CLAUDE.md 2026-08-24「公式カードリストに無いカード」の規約):
  - 番号・名前・レアリティ・コスト等 … PSA スラブ実写の券面 (cert176142085) で読める分
  - 効果文・特徴・色など券面で読める共通項目は 公式行 ST21-015 と同じ (複製と分かる印を source に残す)
  - 画像 … PSA スラブ写真 (目視照合専用。eBay 出品画像には使わない)
★公式がこのカードを載せたら公式値で上書きすること。

実行: python migrations/2026-09-24_st21_015_event_prize.py [--commit]
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PID = "ST21-015_EVENT"
BASE = "ST21-015"
CERT = "176142085"
IMG = ("https://d1htnxwo4o0jhw.cloudfront.net/cert/222581001/large/"
       "rlC0UjpeqkeYRtvgazmZcQ.jpg")
LOCAL = Path(f"C:/dev/iMak_data/catalog/_psa_cert{CERT}_st21_015_event.jpg")
commit = "--commit" in sys.argv

db = sqlite3.connect(str(api._DB_PATH), timeout=120)
db.row_factory = sqlite3.Row
base = db.execute("SELECT * FROM products WHERE category='one_piece_tcg' AND product_id=?",
                  (BASE,)).fetchone()
if db.execute("SELECT 1 FROM products WHERE category='one_piece_tcg' AND product_id=?",
              (PID,)).fetchone():
    print(f"{PID} は既に在る → 触らない")
    sys.exit(0)

s = json.loads(base["specs"])
s.update({
    "variant_type": "event_prize",
    # clone 行の決まり (tests/test_clone_rows_no_parent_image_20260823): 複製元を明示する
    "cloned_from": BASE,
    "card_number_text": "ST21-015",
    "set_name_ebay": "Promo Cards",
    "set_name_ebay_source": "filter_map_promo_20260924",
    "psa_subject_hint": ["OFFICIAL EVENT PRIZE"],
    "spec_source": (f"PSA スラブ実写 cert{CERT} の券面 + 公式行 {BASE} からの複製 "
                    "(効果文・特徴・色・コスト)。公式カードリストに この絵柄の行が無い "
                    "(2026-09-24 実測: _p2/_p3/_r1 とも 404)"),
    "review_image_note": (f"公式に絵が無いため PSA スラブ実写 (cert{CERT}) を目視照合用に入れている。"
                          f"eBay 出品画像には使わない。公式が出したら差し替えること。控え: {LOCAL}"),
})
print(f"=== {PID} を登録 ({'APPLY' if commit else 'DRY-RUN'}) ===")
print(f"  {base['name']} / SR / オフィシャルイベント賞品 (青い名前枠の別絵柄)")
print(f"  画像: {IMG}")
if commit:
    try:
        with urllib.request.urlopen(urllib.request.Request(
                IMG, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
            LOCAL.write_bytes(r.read())
        print(f"  控え: {LOCAL} ({LOCAL.stat().st_size:,} bytes)")
    except Exception as e:
        print(f"  ⚠️ 控えを保存できず: {type(e).__name__}")
    now = datetime.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO products (category, product_id, name, name_jp, name_en, name_en_source, "
        "set_name, set_name_official, specs, images, source, source_url, created_at, updated_at) "
        "VALUES ('one_piece_tcg',?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (PID, base["name"], base["name_jp"], base["name_en"], base["name_en_source"],
         "プロモーションカード", "プロモーションカード",
         json.dumps(s, ensure_ascii=False), json.dumps([IMG], ensure_ascii=False),
         f"psa_cert{CERT}_slab_confirmed+clone_{BASE}", "", now, now))
    db.commit()
    print("\n適用 1行")
else:
    print("\n(dry-run — --commit で適用)")
