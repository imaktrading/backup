# -*- coding: utf-8 -*-
"""共有データ (C:/dev/iMak_data) の毎晩バックアップ → Google ドライブ (法人アカウント)。

背景 (2026-09-17):
    PC が SSD の読み書き失敗でブルースクリーンを繰り返した (0x154 / 0x1A / 0x7A, c0000185)。
    コードは GitHub に在るが、**iMak_data は git 管理外で どこにも複製が無かった**
    (カタログ DB・台帳・依頼書・残務ボード)。SSD が壊れたら全部消える状態だった。

やること (1回分):
    1. products.sqlite を **sqlite の backup API** で一時ファイルに写す (使用中でも壊れない)
       → quick_check と行数を確かめる
    2. 大事なフォルダを1つの zip にまとめる (画像・PDF・公式 dump・退避ファイル・秘密情報は入れない)
    3. zip を Google ドライブ (G:) に置く → 置いた zip を開き直して CRC と DB 行数を照合
    4. 7日分より古い zip を消す
    5. 結果を review_logs/data_backup_last.json に書く。**全部通った時だけ ok=true**
       Console はこのファイルを見て、失敗・36時間更新なし を「知らせ」に出す

使い方:
    python data_backup.py            # 1回実行
    python data_backup.py --dry-run  # 何を入れるかの件数と大きさだけ出す (書かない)
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import sqlite3
import sys
import tempfile
import time
import zipfile

SRC = r"C:\dev\iMak_data"
DB = os.path.join(SRC, "catalog", "products.sqlite")
DEST = r"G:\マイドライブ\iMak_backup\daily"
KEEP = 7
HERE = os.path.dirname(os.path.abspath(__file__))
STATUS = os.path.join(HERE, "..", "review_logs", "data_backup_last.json")

# 丸ごと入れないフォルダ (SRC からの相対パス)。
# 公式サイトの dump・画像・PDF は取り直せる / ブラウザのプロファイルは作り直せる /
# 秘密情報はクラウドに置かない (USB 側だけ)。
EXCLUDE_DIRS = {
    "chrome_profile_psa", "credentials", "secrets", "secrets_backup",
    r"catalog\_bak", r"catalog\backups", r"catalog\_raw", r"catalog\_input",
    r"catalog\montbell_pdfs", r"catalog\_don_images", r"catalog\_don_pdf_samples",
    r"catalog\_ygo_jp_images", r"catalog\pokemon_translation_cache",
    r"dedupe\img_cache",    # 重複くんの画像キャッシュ 2.3GB / 1.6万件。取り直せる (拡張子が無く種類で外せない)
}
EXCLUDE_DIR_PATTERNS = ("*_dumps", "*_dumps.bak_*", "*_dumps_*", "*.bak_*", "__pycache__", "_tmp*")
EXCLUDE_FILE_PATTERNS = ("*.bak*", "*pre_*", "*.sqlite", "*.sqlite-shm", "*.sqlite-wal",
                         "*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.pdf", "*.zip", "*.dmp")
MAX_FILE_MB = 50            # これより大きい1ファイルは入れない (件数は結果に残す)


def _excluded_dir(rel):
    if rel in EXCLUDE_DIRS:
        return True
    name = os.path.basename(rel)
    return any(fnmatch.fnmatch(name, p) for p in EXCLUDE_DIR_PATTERNS)


def _excluded_file(name, size):
    if any(fnmatch.fnmatch(name.lower(), p) for p in EXCLUDE_FILE_PATTERNS):
        return "type"
    if size > MAX_FILE_MB * 1024 * 1024:
        return "size"
    return ""


def pick_files(src=SRC):
    """入れるファイルの一覧と、外した件数 (純関数に近い: 読むだけ)。"""
    files, skipped = [], {"type": 0, "size": 0, "big": []}
    for root, dirs, names in os.walk(src):
        rel_root = os.path.relpath(root, src)
        rel_root = "" if rel_root == "." else rel_root
        dirs[:] = [d for d in dirs if not _excluded_dir(os.path.join(rel_root, d) if rel_root else d)]
        for n in names:
            p = os.path.join(root, n)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            why = _excluded_file(n, size)
            if why:
                skipped[why] += 1
                if why == "size":
                    skipped["big"].append(os.path.join(rel_root, n))
                continue
            files.append((p, os.path.join(rel_root, n), size))
    return files, skipped


def copy_db(tmpdir):
    out = os.path.join(tmpdir, "products.sqlite")
    src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)
        rows_src = src.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    finally:
        dst.close()
        src.close()
    c = sqlite3.connect(out)
    try:
        qc = c.execute("PRAGMA quick_check").fetchone()[0]
        rows = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    finally:
        c.close()
    if qc != "ok" or rows != rows_src:
        raise RuntimeError(f"DB の写しが壊れている (quick_check={qc} / 行数 {rows} ≠ 元 {rows_src})")
    return out, rows


def verify_zip(path, db_rows):
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"zip の中身が壊れている: {bad}")
        n = len(z.namelist())
        with tempfile.TemporaryDirectory() as t:
            z.extract("catalog/products.sqlite", t)
            c = sqlite3.connect(os.path.join(t, "catalog", "products.sqlite"))
            try:
                rows = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            finally:
                c.close()
    if rows != db_rows:
        raise RuntimeError(f"zip の DB 行数 {rows} ≠ 写した時 {db_rows}")
    return n


def prune(dest=DEST, keep=KEEP):
    zs = sorted(f for f in os.listdir(dest) if f.startswith("iMak_daily_") and f.endswith(".zip"))
    old = zs[:-keep] if len(zs) > keep else []
    for f in old:
        os.remove(os.path.join(dest, f))
    return old


def write_status(d):
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    st = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "ok": False, "dest": DEST}
    try:
        files, skipped = pick_files()
        total = sum(s for _, _, s in files)
        st.update(files=len(files), raw_mb=round(total / 1e6, 1), skipped_type=skipped["type"],
                  skipped_big=skipped["big"][:20])
        print(f"入れる: {len(files)}件 {total / 1e6:.1f}MB / 外した: 種類 {skipped['type']} / "
              f"{MAX_FILE_MB}MB超 {len(skipped['big'])} {skipped['big'][:5]}")
        if a.dry_run:
            return 0
        if not os.path.isdir(os.path.dirname(os.path.dirname(DEST))):
            raise RuntimeError("Google ドライブ (G:) が見つからない。パソコン版ドライブが止まっている可能性")
        os.makedirs(DEST, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            db_copy, rows = copy_db(tmp)
            st["db_rows"] = rows
            local_zip = os.path.join(tmp, f"iMak_daily_{stamp}.zip")
            with zipfile.ZipFile(local_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                z.write(db_copy, "catalog/products.sqlite")
                for p, rel, _ in files:
                    try:
                        z.write(p, rel.replace("\\", "/"))
                    except OSError as e:          # 走っている処理が書き換え中のファイル等
                        st.setdefault("unreadable", []).append(f"{rel}: {e.__class__.__name__}")
            verify_zip(local_zip, rows)
            dst = os.path.join(DEST, os.path.basename(local_zip))
            with open(local_zip, "rb") as fi, open(dst, "wb") as fo:
                while True:
                    b = fi.read(8 * 1024 * 1024)
                    if not b:
                        break
                    fo.write(b)
            n = verify_zip(dst, rows)
            st.update(zip=dst, zip_mb=round(os.path.getsize(dst) / 1e6, 1), zip_entries=n)
        st["pruned"] = prune()
        st["ok"] = True
        print(f"✅ 正常: {st['zip']} ({st['zip_mb']}MB / {n}件 / DB {rows}行) 残り世代 {KEEP}")
        return 0
    except Exception as e:                                     # noqa: BLE001
        st["error"] = f"{type(e).__name__}: {e}"
        print(f"⚠️要対応: バックアップ失敗 — {st['error']}")
        return 1
    finally:
        st["sec"] = round(time.time() - t0)
        if not a.dry_run:
            write_status(st)


if __name__ == "__main__":
    sys.exit(main())
