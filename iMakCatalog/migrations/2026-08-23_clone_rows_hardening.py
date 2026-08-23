#!/usr/bin/env python3
"""clone 行に親の絵が入らない作りにする (cloned_from / source_url 空 / 親コピー画像を戻す).

2026-08-23。回答書
`requests/2026-08-23_hq_go_cll_images_and_clone_hardening_response.md` §2 [IMPLEMENT-GO]。

## 判定 (1丁目1番地): ①カタログのデータが誤り → catalog 側で直す

②は正しい (出品くんは product_id 完全一致でしか引かない)。
誤りは clone 行の作りで、`source_url` が親の series ページを指していたため
画像補完が親の絵を入れてしまった (`OP01-077_GE` = 8/22 / 3日連続で指摘)。

## やること (規則 `clone_rows.py` のとおり。例外を作らない)

1. `specs.cloned_from` = base の product_id。base 行が実在することを確かめてから書く
   (無ければ **書かずに報告** = fail-closed)。
2. `source_url` を空にする。出所は `source` 列 (`...+clone_<base>`) に残る。
3. **images が base 行と完全一致する行は空に戻す**。別絵柄の行に親の絵が入っている状態
   (= 目視照合が誤る) なので、公式の別絵柄が出るまで空が正しい。
   実測 2026-08-23: `GD01-100_PB01` が該当。この行の note は「新規 Ito 画イラスト」と
   書いてあるのに images が base `GD01-100` の3枚と byte 一致していた。
   (`OP01-077_GE` は 8/23 に別 migration で処置済)

実行:
  python migrations/2026-08-23_clone_rows_hardening.py           # dry-run
  python migrations/2026-08-23_clone_rows_hardening.py --commit
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
import clone_rows  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NOW = datetime.now().isoformat(timespec="seconds")
STAMP = "clone_rows_hardening_20260823"


def _norm_images(raw: str | None) -> list:
    try:
        v = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    return v if isinstance(v, list) else []


def process(commit: bool) -> int:
    print(f"=== clone 行の是正 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    db = sqlite3.connect(api._DB_PATH, timeout=120)
    db.row_factory = sqlite3.Row

    rows = db.execute(
        "SELECT id, category, product_id, source, source_url, images, specs "
        r"FROM products WHERE source LIKE '%clone\_%' ESCAPE '\'").fetchall()
    print(f"clone 行: {len(rows)} 件\n")

    updates, changed = [], 0
    for r in rows:
        base = clone_rows.base_from_source(r["source"])
        if not base:
            print(f"  ✗ {r['product_id']:<16} source から base を読めない ({r['source']!r}) → skip")
            continue
        b = db.execute("SELECT images FROM products WHERE category=? AND product_id=?",
                       (r["category"], base)).fetchone()
        if b is None:
            print(f"  ✗ {r['product_id']:<16} base {base} が無い → skip (fail-closed)")
            continue

        s = json.loads(r["specs"] or "{}")
        imgs, todo = _norm_images(r["images"]), []

        if s.get(clone_rows.SPEC_KEY) != base:
            s[clone_rows.SPEC_KEY] = base
            s["cloned_from_source"] = STAMP
            todo.append(f"cloned_from={base}")
        new_url = "" if (r["source_url"] or "") else r["source_url"]
        if (r["source_url"] or "") != "":
            new_url = ""
            todo.append(f"source_url 空 (旧 {r['source_url']})")
        if imgs and imgs == _norm_images(b["images"]):
            imgs = []
            s["images_cleared_note"] = (
                f"base {base} の画像と完全一致していたため空に戻した ({STAMP})。"
                "別絵柄の行に親の絵が入ると目視照合が誤るため、公式の別絵柄が出るまで空が正しい。")
            todo.append(f"images を空に戻す (base {base} と一致していた)")

        if not todo:
            print(f"  - {r['product_id']:<16} 変更なし")
            continue
        changed += 1
        print(f"  + {r['product_id']:<16} base={base}")
        for t in todo:
            print(f"      {t}")
        updates.append((json.dumps(s, ensure_ascii=False),
                        json.dumps(imgs, ensure_ascii=False), new_url, NOW, r["id"]))

    print(f"\n変更 {changed} 行")
    if commit and updates:
        db.executemany("UPDATE products SET specs=?, images=?, source_url=?, updated_at=? "
                       "WHERE id=?", updates)
        db.commit()
        print("✅ 適用")
    elif not commit:
        print("(dry-run — --commit で適用)")
    db.close()
    return changed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--commit", action="store_true")
    process(p.parse_args().commit)


if __name__ == "__main__":
    main()
