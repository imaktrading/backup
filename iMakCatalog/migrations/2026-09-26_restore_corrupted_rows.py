# -*- coding: utf-8 -*-
"""ビット化けした specs / images をバックアップから戻し、DB を作り直す (2026-09-26).

依頼: `requests/2026-09-26_products_db_corrupted_rows.md`
判定: ①カタログの持ち物 (DB の中身) が壊れている。引き方の問題ではない。

状況 (2026-09-26 実測):
    pragma integrity_check -> 索引3件の欠落 + `database disk image is malformed`
    UTF-8 として読めない行 8件 (依頼書の6件 + SV5K-081 + GMA-S2100GA-7AJF)

原因は PC のブルースクリーン多発 (1日10回前後) によるビット化けと見ている。
9/24 05:00 のバックアップは `integrity_check=ok` で、8行とも正常に読める。
8行とも **更新日がバックアップと同じ** = 9/24 以降 中身は変わっていないので、そのまま戻せる。

やること:
  1. 8行の specs / images をバックアップの値で上書き
  2. `VACUUM INTO` で DB を作り直す (索引の欠落と malformed はこれで消える)
  3. 作り直した DB の integrity_check が ok で、行数が元と同じことを確かめてから差し替え

★実行前に本体を退避しておくこと (`_broken_backup/`)。
実行: python migrations/2026-09-26_restore_corrupted_rows.py [--commit]
"""
from __future__ import annotations

import os
import pathlib
import sqlite3
import sys

DB = "C:/dev/iMak_data/catalog/products.sqlite"
BK = "C:/tmp/bk/iMak_daily_20260924_0500/products.sqlite"
commit = "--commit" in sys.argv


def broken_rows(path: str) -> list[tuple[str, str]]:
    c = sqlite3.connect(path, timeout=300)
    c.text_factory = bytes
    out = []
    for pid, sp, im in c.execute("SELECT product_id, specs, images FROM products"):
        for col, v in (("specs", sp), ("images", im)):
            if v is None:
                continue
            try:
                v.decode("utf-8")
            except UnicodeDecodeError:
                out.append((pid.decode("utf-8", "replace"), col))
    c.close()
    return out


def unreadable_ids(path: str) -> list[int]:
    """行そのものが読めない (ページ破損) id を返す。塊で読んで落ちた所だけ1件ずつ見る."""
    c = sqlite3.connect(path, timeout=300)
    c.text_factory = bytes
    ids = [r[0] for r in c.execute("SELECT id FROM products ORDER BY id")]
    out = []
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        try:
            c.execute("SELECT * FROM products WHERE id BETWEEN ? AND ?",
                      (chunk[0], chunk[-1])).fetchall()
        except sqlite3.DatabaseError:
            for rid in chunk:
                try:
                    c.execute("SELECT * FROM products WHERE id=?", (rid,)).fetchall()
                except sqlite3.DatabaseError:
                    out.append(rid)
    c.close()
    return out


def main() -> None:
    bad = broken_rows(DB)
    print(f"=== 壊れている行 {len(bad)}件 ({'APPLY' if commit else 'DRY-RUN'}) ===")
    for pid, col in bad:
        print(f"  {pid:20} {col}")
    if not commit:
        print("\n(dry-run — --commit で適用)")
        return

    db = sqlite3.connect(DB, timeout=300)
    bk = sqlite3.connect(BK)
    bk.text_factory = bytes
    fixed = skipped = 0
    for pid, col in bad:
        row = bk.execute(f"SELECT {col} FROM products WHERE product_id=?", (pid,)).fetchone()
        if not row or row[0] is None:
            print(f"  ✗ {pid} {col}: バックアップに無い → 手で見る")
            skipped += 1
            continue
        try:
            val = row[0].decode("utf-8")
        except UnicodeDecodeError:
            print(f"  ✗ {pid} {col}: バックアップ側も壊れている → 手で見る")
            skipped += 1
            continue
        db.execute(f"UPDATE products SET {col}=? WHERE product_id=?", (val, pid))
        fixed += 1
    db.commit()
    db.close()
    bk.close()
    print(f"\n戻した {fixed}件 / 戻せなかった {skipped}件")
    rebuild()


def rebuild() -> None:
    """読める行を新しい DB に移し、読めない行はバックアップから入れる.

    ページが壊れている行は DELETE も UPDATE も通らない (`database disk image is malformed`)。
    VACUUM INTO も壊れを引き継ぐので、**作り直して移す**しかない。
    """
    new = pathlib.Path(DB + ".rebuilt")
    if new.exists():
        new.unlink()
    src = sqlite3.connect(DB, timeout=300)
    bk = sqlite3.connect(BK)
    dst = sqlite3.connect(str(new))
    # 作り: 表・索引をそのまま写す
    for (sql,) in src.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"):
        try:
            dst.execute(sql)
        except sqlite3.OperationalError as e:
            print("  skip:", str(e)[:60])
    moved = recovered = lost = 0
    for (t,) in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        cols = [r[1] for r in src.execute(f"pragma table_info({t})")]
        ph = ",".join("?" * len(cols))
        if t != "products":
            rows = src.execute(f"SELECT {','.join(cols)} FROM {t}").fetchall()
            dst.executemany(f"INSERT INTO {t} ({','.join(cols)}) VALUES ({ph})", rows)
            moved += len(rows)
            continue
        ids = [r[0] for r in src.execute("SELECT id FROM products ORDER BY id")]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            try:
                rows = src.execute(
                    f"SELECT {','.join(cols)} FROM products WHERE id BETWEEN ? AND ?",
                    (chunk[0], chunk[-1])).fetchall()
                dst.executemany(f"INSERT INTO products ({','.join(cols)}) VALUES ({ph})", rows)
                moved += len(rows)
                continue
            except sqlite3.DatabaseError:
                pass
            for rid in chunk:                      # 壊れた塊だけ1件ずつ
                try:
                    row = src.execute(
                        f"SELECT {','.join(cols)} FROM products WHERE id=?", (rid,)).fetchone()
                    dst.execute(f"INSERT INTO products ({','.join(cols)}) VALUES ({ph})", row)
                    moved += 1
                except sqlite3.DatabaseError:
                    row = bk.execute(
                        f"SELECT {','.join(cols)} FROM products WHERE id=?", (rid,)).fetchone()
                    if row:
                        dst.execute(f"INSERT INTO products ({','.join(cols)}) VALUES ({ph})", row)
                        recovered += 1
                        print(f"  バックアップから復元 id={rid}")
                    else:
                        lost += 1
                        print(f"  ✗ id={rid}: バックアップにも無い")
    dst.commit()
    ok = dst.execute("pragma integrity_check").fetchone()[0]
    after = dst.execute("SELECT count(*) FROM products").fetchone()[0]
    dst.close()
    before = len([r for r in src.execute("SELECT id FROM products")])
    src.close()
    bk.close()
    print(f"\n移した {moved} / 復元 {recovered} / 失った {lost}")
    print(f"新 DB: integrity={ok} 行数={after} (元 {before})")
    if ok != "ok" or after != before:
        print("⚠️ 条件を満たさないので差し替えない")
        return
    for ext in ("-wal", "-shm"):
        p = pathlib.Path(DB + ext)
        if p.exists():
            p.unlink()
    os.replace(str(new), DB)
    d = sqlite3.connect(DB, timeout=300)
    d.execute("pragma journal_mode=WAL")   # 作り直すと delete モードに戻るので付け直す
    print("差し替え完了:", d.execute("pragma integrity_check").fetchone()[0],
          d.execute("pragma journal_mode").fetchone()[0])
    d.close()


if __name__ == "__main__":
    main()
