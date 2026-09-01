"""CLL-009 ライチュウ に目視用の画像を入れる (2026-09-01).

依頼: `requests/2026-09-01_auto_catalog_add_pokemon_tcg.md`
      (cert155921531「catalog CLL-009 は在るが画像が無く目視できない」)

判定: **①カタログのデータが不足** (画像) → catalog 側で入れる。行そのものは在る。

## 公式に絵が無いことは確認済 (終端マーク)

`specs.no_official_image=true` / 理由「公式特設 (pokemon-card.com/ex/classic) が出して
いる30枚は基本エネルギー3枚を除き全て別の行に割当済。番号付きの行に入る絵を公式が
出していない」。= 公式を待っても出てこない。

## 第三者 source 例外の4条件 (CLAUDE.md) を満たす

1. 公式に当該カードの絵が存在しない … 上の終端マーク (特設を実取得して判定済)
2. 内容が全項目一致 … PSA スラブ実写で券面を確認:
     `CLL 009/032` / ライチュウ / HP130 / 1進化 (ピカチュウから進化) / Illus. Hasuno
     → catalog CLL-009 ライチュウ と一致
3. 用途は社内目視限定 … eBay 出品画像は PSA スラブ実写。この画像は表に出ない
4. source に第三者由来の印 … `+review_image_psa_cert155921531_20260901`

★公式が絵を出したら差し替える。控えを共有領域にも置く (URL が消えるため)。

実行:
  python migrations/2026-09-01_cll_009_review_image.py
  python migrations/2026-09-01_cll_009_review_image.py --commit
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
PID = "CLL-009"
CERT = "155921531"
IMG = ("https://d1htnxwo4o0jhw.cloudfront.net/cert/206366303/large/"
       "gYVNZ__coEuCHuEVlPyVOw_52531.jpg")
LOCAL = "C:/dev/iMak_data/catalog/_psa_cert155921531_cll_009.jpg"


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    r = db.execute("SELECT id, product_id, images, source, specs FROM products "
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
    s = json.loads(r["specs"] or "{}")
    # 画像が入る = 終端マーク (「公式に絵が無い → 目視不能」) の前提が消えるので落とす
    for k in [k for k in list(s) if k == "no_official_image" or k.startswith("no_official_image_")]:
        s.pop(k, None)
    s["review_image_note"] = (
        f"公式に絵が無いため PSA スラブ実写 (cert{CERT}) を目視照合用に入れている。"
        "eBay 出品画像には使わない。公式が絵を出したら差し替えること。"
        f"券面 `CLL 009/032` を確認済。控え: {LOCAL}")
    src = r["source"] + f"+review_image_psa_cert{CERT}_20260901"
    print(f"  + images = [{IMG[:60]}...]")
    print(f"  + source = {src}")
    if commit:
        db.execute("UPDATE products SET images=?, source=?, specs=?, updated_at=? WHERE id=?",
                   (json.dumps([IMG], ensure_ascii=False), src,
                    json.dumps(s, ensure_ascii=False), NOW, r["id"]))
        db.commit()
        print("  [OK] 適用 1 行")
    else:
        print("  (dry-run — --commit で適用)")
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
