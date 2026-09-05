# -*- coding: utf-8 -*-
"""コロちゃおVer. を M-P の通し番号から切り離す (2026-09-05).

判定 (1丁目1番地): **①カタログのデータが誤り**。公式の券面を取り直して確認した。

## 何が起きていたか

`スタートデッキ100 バトルコレクション コロちゃおVer.` は **自前の 001〜023** で
刷られている (券面 `001/023`)。一方 M-P のプロモは **通し番号** (`001/M-P`)。
公式の画像フォルダが両方 `M-P` なので、catalog は同じ鍵にまとめてしまい、
`M-P-001` を チコリータ (`001/M-P`) と アイアント (`001/023`) が奪い合っていた。
結果、アイアントが **構造的に入らない**状態だった。

## やること

コロちゃお側 23枚を `M-P-KC-###` に移す。M-P の通し番号側 (チコリータ等) は動かさない。

★出品くんは PSA ラベルでどちらか決められないことがあるので、`_POKEMON_SIBLING_SETS` に
  `M-P` ↔ `M-P-KC` を入れてある (名前が合う方を選ぶ。合わなければ引かない)。

★HQ へ: `M-P-002`〜`M-P-023` を鍵にした出品が在れば `M-P-KC-002`〜`M-P-KC-023` に読み替え。
  スターターデッキの通常カードなので出品済みは想定していない。

実行:
  python migrations/2026-09-05_mp_korochao_split.py [--commit]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))
import api  # noqa: E402
import pokemon_tcg as P  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
SET = "スタートデッキ100 バトルコレクション コロちゃおVer."
NEW_ID = "49587"          # アイアント 001/023 (今まで入れられなかった1枚)


def run(commit: bool) -> None:
    db = sqlite3.connect(str(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, product_id FROM products WHERE category='pokemon_tcg' "
                      "AND set_name_official=? AND product_id LIKE 'M-P-%' "
                      "AND product_id NOT LIKE 'M-P-KC-%' ORDER BY product_id", (SET,)).fetchall()
    print(f"=== コロちゃおVer. を切り離す ({'APPLY' if commit else 'DRY-RUN'}) — {len(rows)}行 ===")
    done = 0
    for r in rows:
        new = r["product_id"].replace("M-P-", "M-P-KC-", 1)
        print(f"    {r['product_id']} -> {new}")
        if commit:
            db.execute("UPDATE products SET product_id=?, updated_at=? WHERE id=?",
                       (new, NOW, r["id"]))
            done += 1
            if done % 10 == 0:
                db.commit()
    if commit:
        db.commit()
    db.close()

    print("\n=== 入れられなかった1枚 ===")
    # ★cache に 収録商品名が入っていない古い読み取りが残っているので取り直す
    cache = P.CACHE_DIR / f"detail_{NEW_ID}.json"
    if commit and cache.exists():
        cache.unlink()
    d = P.get_detail(NEW_ID)
    pid = P.derive_product_id(d) if d else None
    print(f"    cardID {NEW_ID} -> {pid} ({d.get('name') if d else None})")
    if commit and pid:
        P.build_and_upsert(NEW_ID, dry_run=False)
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
