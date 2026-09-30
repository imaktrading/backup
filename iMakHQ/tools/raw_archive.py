# -*- coding: utf-8 -*-
"""カタログの _raw (公式サイトから取った元データ 約1.7GB / 8.3万件) を、毎晩少しずつ Google ドライブへ送る (2026-09-30)。

毎朝の zip には入れていない (大きすぎる)。9/30 朝に 1.8GB を1本で圧縮していてブルースクリーンになったので、
1本 100MB まで・一晩 3本まで・低い優先度で送る。送り済みは manifest.json に記録し、次の晩は新しい物と変わった物だけ送る。

    python raw_archive.py            # 一晩分を送る (予約タスク iMakHQ_RawArchive_0200)
    python raw_archive.py --dry-run  # 残りを数えるだけ

戻す時: G:/マイドライブ/iMak_backup/raw の zip を**名前の順に全部**展開して上書きする (後の本が新しい)。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile

SRC = r"C:\dev\iMak_data\catalog\_raw"
DEST = r"G:\マイドライブ\iMak_backup\raw"
MANIFEST = "manifest.json"
PART_MB = 100
PARTS_PER_NIGHT = 3
STORED = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf", ".zip")   # もう縮まない物は圧縮しない (CPU を使わない)
HERE = os.path.dirname(os.path.abspath(__file__))
STATUS = os.path.join(HERE, "..", "review_logs", "raw_archive_last.json")


def scan(src=SRC):
    """{相対パス: [大きさ, 更新時刻ns]} (読むだけ)。"""
    out = {}
    for root, _, names in os.walk(src):
        for n in names:
            p = os.path.join(root, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[os.path.relpath(p, src).replace("\\", "/")] = [st.st_size, st.st_mtime_ns]
    return out


def plan(now, sent, part_bytes=PART_MB * 1024 * 1024, parts=PARTS_PER_NIGHT):
    """送る物を本ごとに分ける → ([[相対パス]], 残りの件数)。sent = {相対パス: [大きさ, 更新時刻ns, 本の名前]}。"""
    todo = sorted(r for r, (size, mt) in now.items() if r not in sent or sent[r][:2] != [size, mt])
    books, cur, cur_b = [], [], 0
    for r in todo:
        size = now[r][0]
        if cur and cur_b + size > part_bytes:
            books.append(cur)
            cur, cur_b = [], 0
            if len(books) == parts:
                break
        cur.append(r)
        cur_b += size
    else:
        if cur:
            books.append(cur)
    done = sum(len(b) for b in books)
    return books, len(todo) - done


def _low_priority():
    """CPU とディスクの優先度を下げる (Windows のみ。失敗しても続ける)。"""
    try:
        import ctypes
        h = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(h, 0x00100000)   # PROCESS_MODE_BACKGROUND_BEGIN (CPU・ディスクとも低)
    except Exception:                                            # noqa: BLE001
        pass


def _load(dest):
    p = os.path.join(dest, MANIFEST)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save(dest, sent):
    p = os.path.join(dest, MANIFEST)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sent, f, ensure_ascii=False)
    os.replace(tmp, p)


def write_book(src, rels, path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for r in rels:
            how = zipfile.ZIP_STORED if r.lower().endswith(STORED) else zipfile.ZIP_DEFLATED
            z.write(os.path.join(src, *r.split("/")), r, compress_type=how)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    st = {"at": datetime.datetime.now().isoformat(timespec="seconds"), "ok": False, "dest": DEST}
    try:
        _low_priority()
        if not os.path.isdir(os.path.dirname(os.path.dirname(DEST))):
            raise RuntimeError("Google ドライブ (G:) が見つからない。パソコン版ドライブが止まっている可能性")
        os.makedirs(DEST, exist_ok=True)
        now = scan()
        sent = _load(DEST)
        books, left = plan(now, sent)
        st.update(files=len(now), sent_before=len(sent), books=len(books), left_after=left)
        print(f"全 {len(now)}件 / 送り済み {len(sent)}件 / 今晩 {len(books)}本 {sum(map(len, books))}件 / 残り {left}件")
        if a.dry_run:
            return 0
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        made = []
        for i, rels in enumerate(books, 1):
            name = f"raw_{stamp}_{i:02d}.zip"
            with tempfile.TemporaryDirectory() as t:
                local = os.path.join(t, name)
                write_book(SRC, rels, local)
                dst = os.path.join(DEST, name)
                shutil.copyfile(local, dst)
                want = os.path.getsize(local)
                for _ in range(30):              # Google ドライブは書いた直後の大きさが遅れて見える (9/30 初回で空振り)
                    if os.path.getsize(dst) == want:
                        break
                    time.sleep(2)
                else:
                    raise RuntimeError(f"{name} の大きさが合わない ({os.path.getsize(dst)} ≠ {want})")
            with zipfile.ZipFile(dst) as z:
                bad = z.testzip()
                if bad or len(z.namelist()) != len(rels):
                    raise RuntimeError(f"{name} の中身が合わない (壊れ {bad} / {len(z.namelist())}件 ≠ {len(rels)}件)")
            for r in rels:                       # 1本ずつ記録する (途中で落ちても送った分は二度送らない)
                sent[r] = now[r] + [name]
            _save(DEST, sent)
            made.append(name)
        st.update(ok=True, made=made)
        print(("✅ 正常: 全部送り済み" if left == 0 else f"✅ 正常: 残り {left}件 (次の晩に続き)") + f" / 今晩 {made}")
        return 0
    except Exception as e:                                     # noqa: BLE001
        st["error"] = f"{type(e).__name__}: {e}"
        print(f"⚠️要対応: _raw の送り失敗 — {st['error']}")
        return 1
    finally:
        if not a.dry_run:
            os.makedirs(os.path.dirname(STATUS), exist_ok=True)
            with open(STATUS, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
