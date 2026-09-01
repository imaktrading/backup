"""ポケモンの型 (Type) のキー名を `type_en` に揃える (2026-09-01).

依頼: `requests/2026-09-01_hq_cl_series_type_key_naming.md`
判定 (1丁目1番地): **①カタログのデータが誤り (キー名)** → catalog 側で直す。

## 何が起きていたか

出品くんは `specs.type_en` を読む。ところが 9行だけ `specs.type` という**別のキー名**で
持っていて、値は正しいのに出品くんに渡らず `C:Type` が空 → セルフチェック落ち。

    CLK-008 Lapras   type='Water'      type_en 無し
    CLF-002 Ivysaur  type='Grass'      type_en 無し   ほか (下の TARGETS)

いずれも 2026-05〜06 に第三者裏取りで手投入した行 (source が bulbapedia / yuyu-tei 等)。
scraper 経由の 22,102行は最初から `type_en` なので、**手投入の時だけ名前が揺れた**。

## やること (キーを1つに寄せるだけ。値は変えない)

1. `type` があって `type_en` が無い → `type_en` に移す (7行)
2. `type` と `type_en` が両方あって同じ値 → `type` を落とす (2行: EBB-045 / CP4-075)
3. 値が食い違う行があれば **触らずに報告** (fail-closed。実測では0行)

★CLL-002 (Charmeleon) は値そのものが無い。note に「HP/イラストレーター/わざは裏取り
  不能のため未収録」と書いてあるので **正当な欠落**。ここでは触らない。

回帰: tests/test_pokemon_type_key_20260901.py (`type` キーを持つ行が0であること)

実行:
  python migrations/2026-09-01_pokemon_type_key_rename.py
  python migrations/2026-09-01_pokemon_type_key_rename.py --commit
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
CAT = "pokemon_tcg"


def run(commit: bool) -> None:
    db = sqlite3.connect(Path(api._DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute("SELECT id, product_id, specs FROM products WHERE category=?",
                      (CAT,)).fetchall()
    moved, dropped, conflicts = [], [], []
    for r in rows:
        s = json.loads(r["specs"] or "{}")
        if "type" not in s:
            continue
        old, new = s.get("type"), s.get("type_en")
        if new and str(old).strip() != str(new).strip():
            conflicts.append((r["product_id"], old, new))       # fail-closed
            continue
        if not new:
            s["type_en"] = old
            moved.append((r["product_id"], old))
        else:
            dropped.append((r["product_id"], old))
        s.pop("type", None)
        if commit:
            db.execute("UPDATE products SET specs=?, updated_at=? WHERE id=?",
                       (json.dumps(s, ensure_ascii=False), NOW, r["id"]))
    if commit:
        db.commit()
    db.close()

    print(f"=== type → type_en ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for pid, v in moved:
        print(f"  + {pid:12s} type_en={v!r} (type から移した)")
    for pid, v in dropped:
        print(f"  - {pid:12s} type={v!r} を落とした (type_en に同じ値が在る)")
    for pid, o, n in conflicts:
        print(f"  ✗ {pid:12s} 値が食い違う type={o!r} type_en={n!r} → 触らない (要確認)")
    print("")
    print(f"{'適用' if commit else '(dry-run — --commit で適用)'}: "
          f"移動 {len(moved)} / 削除 {len(dropped)} / 未処理 {len(conflicts)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    run(p.parse_args().commit)
