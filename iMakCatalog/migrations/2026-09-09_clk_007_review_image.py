# -*- coding: utf-8 -*-
"""CLK-007 ギャラドス に目視用の画像を入れる (2026-09-09).

依頼: `requests/2026-09-07_auto_catalog_add_pokemon_tcg.md`
      / `requests/2026-09-09_pdca_catalog_queue_tcg.md`
      (cert153496820「catalog CLK-007 は在るが画像が無く目視できない」= 出品できない)

判定 (1丁目1番地): **①カタログのデータが不足** (画像)。行そのものは在る。

## 公式に絵が無いことを今その場で確かめた

    公式 resultAPI  pg=CLK -> 2枚 (基本水エネルギー / 基本超エネルギー) だけ
                    pg=CLF -> 2枚   pg=CLL -> 2枚

クラシック3デッキは **公式が番号付きカードの絵を出していない**。待っても出てこない。
(2026-09-01 の CLL-009 と同じ形。`migrations/2026-09-01_cll_009_review_image.py`)

## 第三者 source 例外の4条件 (CLAUDE.md) を満たす

1. 公式に当該カードの絵が存在しない … 上のとおり実測済
2. 内容が全項目一致 … PSA cert 153496820 の券面 (2026-09-09 実取得):
       Brand/Title : POKEMON JAPANESE CLK-TRADING CARD GAME CLASSIC BLASTOISE & SUICUNE EX DECK
       Subject     : GYARADOS      Card Number : 007      Year : 2023
   → catalog `CLK-007 ギャラドス / クラシック カメックス&スイクンexデッキ` と一致
3. 用途は社内目視限定 … eBay 出品画像は PSA スラブ実写。この画像は表に出ない
4. source に第三者由来の印 … `+review_image_psa_cert153496820_20260909`

★公式が絵を出したら差し替える。控えを共有領域にも置く (URL が消えるため)。

実行:
  python migrations/2026-09-09_clk_007_review_image.py
  python migrations/2026-09-09_clk_007_review_image.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
PID = "CLK-007"
CERT = "153496820"
IMG = ("https://d1htnxwo4o0jhw.cloudfront.net/cert/204682933/large/"
       "UT7SLzAH-067raCO2ivKyg.jpg")
LOCAL = Path(f"C:/dev/iMak_data/catalog/_psa_cert{CERT}_clk_007.jpg")
MARK = f"review_image_psa_cert{CERT}_20260909"


def run(commit: bool) -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    db.row_factory = sqlite3.Row
    r = db.execute("SELECT id, product_id, name, images, source, specs FROM products "
                   "WHERE category='pokemon_tcg' AND product_id=?", (PID,)).fetchone()
    print(f"=== {PID} 目視画像 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    if r is None:
        print(f"  ✗ {PID} が無い → skip")
        db.close()
        return
    if json.loads(r["images"] or "[]"):
        print("  - 既に画像がある → 触らない")
        db.close()
        return
    print(f"  {PID} {r['name']}  <- PSA cert {CERT} のスラブ写真")
    print(f"     {IMG}")
    if not commit:
        print("\n(dry-run — --commit で適用)")
        db.close()
        return

    # 控えを共有領域に置く (cloudfront の URL はいつか消える)
    try:
        with urllib.request.urlopen(
                urllib.request.Request(IMG, headers={"User-Agent": "Mozilla/5.0"}),
                timeout=30) as resp:
            LOCAL.write_bytes(resp.read())
        print(f"     控え: {LOCAL} ({LOCAL.stat().st_size:,} bytes)")
    except Exception as e:
        print(f"     ⚠️ 控えを保存できず: {type(e).__name__} {e}")

    s = json.loads(r["specs"] or "{}")
    # ★キー名は CLL-009 (2026-09-01) と揃える。`review_image_note` を
    #   回帰テスト `test_pokemon_classic_official_images_20260823.py` が見ている。
    # ★「公式に絵が無い」の終端マークは外す。絵が入った行に残すと
    #   `test_no_official_image_mark_20260824.py` が落ちる (CLL-009 も外してある)。
    #   公式に絵が無い事実は下の注記が持つ。
    s.pop("no_official_image", None)
    s.pop("no_official_image_reason", None)
    s["review_image_note"] = (
        f"公式に絵が無いため PSA スラブ実写 (cert{CERT}) を目視照合用に入れている。"
        "eBay 出品画像には使わない。公式が絵を出したら差し替えること。"
        f"券面 `CLK 007` / GYARADOS を確認済。控え: {LOCAL}")
    db.execute("UPDATE products SET images=?, source=?, specs=?, updated_at=? WHERE id=?",
               (json.dumps([IMG], ensure_ascii=False),
                (r["source"] or "") + "+" + MARK,
                json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    db.commit()
    db.close()
    print("\n適用 1行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
