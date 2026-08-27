"""3rd ANNIVERSARY SET の2行に目視用の画像を入れる (公式に絵が無いため第三者画像の例外).

きっかけ: 2026-08-26 ユーザー「でも、わかりにくいよ」。
セット名が出るようになった (HQ 2026-08-24) 後でも、**絵が無い行は絵で確かめられない**。
今回のように通常弾と絵柄だけが違うカードは、絵が並んでいれば一目で分かる。

## 例外規約の4条件 (CLAUDE.md「画像の第三者 source 例外規約」)

1. 公式に当該カードが存在しない  ← 2026-08-26 実取得で確認
     onepiece-cardgame.com /images/cardlist/card/OP12-079{,_p,_p1,_p2,_p3}.png
        -> 通常版のみ 200、_p 以降は全て 404
     OP07-118 は _p1/_p2/_r1 が 200 だが **どれも別絵柄** (実画像を目視)
2. 内容が全項目一致  ← PSA スラブ実写で券面を確認
     OP12-079 / R      ・ルフィは"海賊王"になる男だ!!! (cert151301749)
     OP07-118 / SEC    ・サボ + 3rd Anniversary 箔押しロゴ (cert155570650)
3. 用途が社内目視照合限定  ← eBay 出品画像は PSA スラブ実写。この画像は表に出ない
4. source に第三者由来と分かる印  ← `+review_image_psa_cert<cert>_20260826`

URL が消えることへの備えに、同じ画像を共有領域にも置いた:
    C:/dev/iMak_data/catalog/_psa_cert151301749_op12_079_an03.jpg
    C:/dev/iMak_data/catalog/_psa_cert155570650_op07_118_an03.jpg

★公式がこの絵を出したら差し替える。

実行:
  python migrations/2026-08-26_an03_review_images.py           # dry-run
  python migrations/2026-08-26_an03_review_images.py --commit
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

NOW = datetime.now().isoformat(timespec="seconds")

# (product_id, cert, PSA 画像 URL, 共有領域の控え)
ROWS = [
    ("OP12-079_AN03", "151301749",
     "https://d1htnxwo4o0jhw.cloudfront.net/cert/202663845/large/jys41x_kGkK0HawfjRe-GA.jpg",
     "C:/dev/iMak_data/catalog/_psa_cert151301749_op12_079_an03.jpg"),
    ("OP07-118_AN03", "155570650",
     "https://d1htnxwo4o0jhw.cloudfront.net/cert/206211964/large/f29FWqRctkyIO1vw6PU_WQ.jpg",
     "C:/dev/iMak_data/catalog/_psa_cert155570650_op07_118_an03.jpg"),
]


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    n = 0
    print(f"=== 3rd ANNIVERSARY SET 目視画像 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for pid, cert, img, local in ROWS:
        r = db.execute("SELECT id, product_id, images, source, specs FROM products "
                       "WHERE category='one_piece_tcg' AND product_id=?", (pid,)).fetchone()
        if r is None:
            print(f"  ✗ {pid} が無い → skip")
            continue
        s = json.loads(r["specs"] or "{}")
        # 画像が入る = 終端マーク ("公式に絵が無い → 目視不能") の前提が消えるので落とす。
        # tools/no_official_image_audit.py と同じキー (test_no_official_image_mark_20260824)。
        dropped = [k for k in list(s)
                   if k == "no_official_image" or k.startswith("no_official_image_")]
        for k in dropped:
            s.pop(k, None)
        if json.loads(r["images"] or "[]"):
            if dropped and commit:
                db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                           (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
                db.commit()
            print(f"  - {pid} 既に画像がある → 画像は触らない"
                  f"{' / 終端マークを外した' if dropped else ''}")
            continue
        s["review_image_note"] = (
            f"公式に絵が無いため PSA スラブ実写 (cert{cert}) を目視照合用に入れている。"
            "eBay 出品画像には使わない。公式が絵を出したら差し替えること。"
            f"控え: {local}")
        src = r["source"] + f"+review_image_psa_cert{cert}_20260826"
        print(f"  + {pid}  images=[{img[:60]}...]")
        if commit:
            db.execute("UPDATE products SET images=?, source=?, specs=?, updated_at=? "
                       "WHERE id=?",
                       (json.dumps([img], ensure_ascii=False), src,
                        json.dumps(s, ensure_ascii=False), NOW, r["id"]))
            db.commit()
        n += 1
    db.close()
    print("")
    print(f"{'[OK] 適用' if commit else '(dry-run — --commit で適用)'} {n} 行")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
