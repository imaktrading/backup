"""EB02-003_CH01 に目視用の画像を入れる (公式に絵が無いため第三者画像の例外を使う).

依頼: requests/2026-08-24_hq_eb02_003_ch01_image_may_not_exist.md

## 例外規約の4条件を満たしているか (CLAUDE.md「画像の第三者 source 例外規約」)

1. 公式に当該カードが存在しない  ← 2026-08-23 実取得で確認
     bandai-tcg-plus JA/EN (card_param=EB02-003)      -> 通常版 + パラレルのみ
     onepiece-cardgame.com プロモ一覧 (series=550901) -> EB02-003 は 0件
     発売元 集英社 (isbn 978-4-08-884100-7)           -> 書影のみ・カードの絵は無い
2. 内容が全項目一致することを人手で確認  ← PSA スラブ実写で券面を確認
     券面 'EB02-003' / 'R' / 'トニートニー・チョッパー' / NOT FOR SALE / ©CHOPPER's Friends
     いずれも catalog の値と一致
3. 用途が社内目視照合限定  ← eBay 出品画像は PSA スラブ実写。この画像は表に出ない
4. source に第三者由来と分かる印  ← `_review_image_psa_cert168544559_20260824`

## URL が消えることへの備え

同じ画像を共有領域にも保存した (先例 `_psa_cert_146160792_image.jpg` 等):
    C:/dev/iMak_data/catalog/_psa_cert168544559_eb02_003_ch01.jpg

## ★これは回避策であって根治ではない

本来は目視画面に **セット名** が出れば、絵が無くても
『ONE PIECE CHOPPER’s 1』付録 と PSA ラベル "ONE PIECE CHOPPER'S 1" で一致が取れる。
画面は重複くんの持ち物なので、別途依頼を出してある。

実行:
  python migrations/2026-08-24_ch01_review_image.py           # dry-run
  python migrations/2026-08-24_ch01_review_image.py --commit
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

PID = "EB02-003_CH01"
IMG = ("https://d1htnxwo4o0jhw.cloudfront.net/cert/216679829/large/"
       "lVWUyS4cRUabUUQJN2h6MQ.jpg")
LOCAL = "C:/dev/iMak_data/catalog/_psa_cert168544559_eb02_003_ch01.jpg"
NOW = datetime.now().isoformat(timespec="seconds")


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    r = db.execute("SELECT id, product_id, images, source, specs FROM products "
                   "WHERE category='one_piece_tcg' AND product_id=?", (PID,)).fetchone()
    if r is None:
        print(f"✗ {PID} が無い → skip")
        db.close()
        return
    cur = json.loads(r["images"] or "[]")
    print(f"=== {PID} ({'APPLY' if commit else 'DRY-RUN'}) ===")
    print(f"  今の images = {cur}")
    if cur:
        print("  既に画像がある → 触らない (公式画像が入ったなら第三者画像は不要)")
        db.close()
        return
    s = json.loads(r["specs"] or "{}")
    s["review_image_note"] = (
        "公式に絵が無いため PSA スラブ実写 (cert168544559) を目視照合用に入れている。"
        "eBay 出品画像には使わない。公式が絵を出したら差し替えること。"
        f"控え: {LOCAL}")
    src = r["source"] + "+review_image_psa_cert168544559_20260824"
    print(f"  + images = [{IMG}]")
    print(f"  + source = {src}")
    if commit:
        db.execute("UPDATE products SET images=?, source=?, specs=?, updated_at=? WHERE id=?",
                   (json.dumps([IMG], ensure_ascii=False), src,
                    json.dumps(s, ensure_ascii=False), NOW, r["id"]))
        db.commit()
        print("\n[OK] 適用 1 行")
    else:
        print("\n(dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
