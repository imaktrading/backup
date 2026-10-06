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
# ★2026-09-27 Catalog 依頼: 7 → 14。9/26 の products.sqlite ビット化けは 9/24 分で戻せたが、
#   気づくのが1週間遅れると戻せない (1本 110〜130MB / +約1GB)
KEEP = 14
HERE = os.path.dirname(os.path.abspath(__file__))
STATUS = os.path.join(HERE, "..", "review_logs", "data_backup_last.json")

# 丸ごと入れないフォルダ (SRC からの相対パス)。
# 公式サイトの dump・画像・PDF は取り直せる / ブラウザのプロファイルは作り直せる /
# 秘密情報はクラウドに置かない (USB 側だけ)。
EXCLUDE_DIRS = {
    "chrome_profile_psa", "credentials", "secrets", "secrets_backup",
    r"catalog\_bak", r"catalog\backups", r"catalog\_raw",
    r"catalog\montbell_pdfs", r"catalog\_don_images", r"catalog\_don_pdf_samples",
    r"catalog\_ygo_jp_images", r"catalog\pokemon_translation_cache",
    r"dedupe\img_cache",    # 重複くんの画像キャッシュ 2.3GB / 1.6万件。取り直せる (拡張子が無く種類で外せない)
    "_symbols",             # ★2026-10-01 Windows のデバッグ用ファイル (25MB)。Microsoft から取り直せる
}
EXCLUDE_DIR_PATTERNS = ("*_dumps", "*_dumps.bak_*", "*_dumps_*", "*.bak_*", "__pycache__", "_tmp*")
EXCLUDE_FILE_PATTERNS = ("*.bak*", "*pre_*", "*.sqlite", "*.sqlite-shm", "*.sqlite-wal",
                         "*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.pdf", "*.zip", "*.dmp",
                         "hwinfo_log*.csv")   # ★2026-10-01 PC の温度などの診断記録 (2本で39MB)。取り直せる
# ★2026-09-30 ユーザー確定: 共有データの外にある Claude の記憶・指示・skill も入れる
#   (どこにも複製が無く、SSD が壊れたら消える状態だった)。会話の記録 (*.jsonl, 約900MB) は入れない。
#   zip の中では _claude/ の下に置く
CLAUDE_HOME = os.path.join(os.path.expanduser("~"), ".claude")
EXTRA_GLOBS = ("CLAUDE.md", "skills", "agents", os.path.join("projects", "*", "memory"),
               "settings.json", "settings.local.json")    # 許可・hook の設定 (ログイン情報 .credentials.json は入れない)

# ★2026-09-30: 復旧一式 (予約タスクの控え・Python 部品・入っているソフト) は手で1回作っただけで古くなる。毎朝作り直す
RESTORE_KIT = os.path.join(SRC, "hq", "restore_kit")


def refresh_restore_kit(kit=RESTORE_KIT):
    """予約タスク (名前に iMak) の xml / pip freeze / winget export を作り直す → 失敗の一覧 (空なら全部できた)。"""
    import subprocess
    bad = []
    tdir = os.path.join(kit, "scheduled_tasks")
    os.makedirs(tdir, exist_ok=True)
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                              "(Get-ScheduledTask | Where-Object TaskName -match 'iMak').TaskName"],
                             capture_output=True, text=True, encoding="utf-8", timeout=120).stdout
        names = [n.strip() for n in out.splitlines() if n.strip()]   # 名前に空白を含むタスクがある
        if not names:
            bad.append("tasks 0件")
        for n in names:
            x = subprocess.run(["schtasks", "/query", "/tn", n, "/xml"], capture_output=True, timeout=60)
            if x.returncode == 0 and x.stdout:
                with open(os.path.join(tdir, n + ".xml"), "wb") as f:
                    f.write(x.stdout)
            else:
                bad.append(f"task {n}")
    except Exception as e:                                     # noqa: BLE001
        bad.append(f"tasks {type(e).__name__}")
    for fname, cmd in (("pip_freeze.txt", [sys.executable, "-m", "pip", "freeze"]),
                       ("installed_apps.json", ["winget", "export", "-o", os.path.join(kit, "installed_apps.json"),
                                                "--accept-source-agreements"])):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=300)
            if fname == "pip_freeze.txt" and r.returncode == 0:
                with open(os.path.join(kit, fname), "wb") as f:
                    f.write(r.stdout)
            elif not os.path.exists(os.path.join(kit, fname)):
                bad.append(fname)
        except Exception as e:                                 # noqa: BLE001
            bad.append(f"{fname} {type(e).__name__}")
    return bad

# ★2026-09-30: 種類 (画像・PDF) で外すと、取り直せない物まで落ちていた。この下は画像・PDF も入れる
#   (catalog\_input = 手で入れた元データ / shipping = 運送会社の料金表 PDF / hq・seller_hub = 画面の控え)。計 約0.1GB
KEEP_MEDIA_DIRS = (r"catalog\_input", "shipping", "hq", "seller_hub")
MEDIA_PATTERNS = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.pdf")

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
            if why == "type" and any(fnmatch.fnmatch(n.lower(), q) for q in MEDIA_PATTERNS) \
                    and any(rel_root == k or rel_root.startswith(k + os.sep) for k in KEEP_MEDIA_DIRS):
                why = ""
            if why:
                skipped[why] += 1
                if why == "size":
                    skipped["big"].append(os.path.join(rel_root, n))
                continue
            files.append((p, os.path.join(rel_root, n), size))
    return files, skipped


def pick_extra(home=CLAUDE_HOME, globs=EXTRA_GLOBS):
    """Claude の記憶・指示・skill → [(path, zip内の名前, size)] (読むだけ)。"""
    import glob
    out = []
    for g in globs:
        for top in glob.glob(os.path.join(home, g)):
            walk = [(os.path.dirname(top), [], [os.path.basename(top)])] if os.path.isfile(top) else os.walk(top)
            for root, _, names in walk:
                if ".trash" in root.replace("\\", "/").split("/"):
                    continue                    # ★2026-10-01 消した skill の置き場 (7.5MB)。戻す物ではない
                for n in names:
                    q = os.path.join(root, n)
                    try:
                        size = os.path.getsize(q)
                    except OSError:
                        continue
                    if size <= MAX_FILE_MB * 1024 * 1024:
                        out.append((q, "_claude/" + os.path.relpath(q, home).replace("\\", "/"), size))
    return out


# ★2026-09-30 ユーザー確定: 本元 (master) で GitHub に載せない設定のデータも入れる。
#   判定の控え (psa_research_cache.json 等) が GitHub にも zip にも無く、PC を替えると消えていた。
#   ログ・一時物・ブラウザのプロファイルは外す。zip の中では _repo/ の下に置く
REPO = r"C:\dev\iMak"
REPO_SKIP_DIRS = ("__pycache__", ".pytest_cache", "chrome_profile*", "edge_profile*", ".decompile_tmp",
                  "debug", "node_modules")
REPO_SKIP_FILES = EXCLUDE_FILE_PATTERNS + ("*.log", "*.lock", "*.heartbeat", "*.pyc")


def pick_repo(repo=REPO):
    """GitHub に載らない本元のデータ → [(path, zip内の名前, size)] (読むだけ)。"""
    import subprocess
    r = subprocess.run(["git", "-C", repo, "ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
                       capture_output=True, check=True)
    out = []
    for rel in r.stdout.decode("utf-8", "replace").split("\0"):
        if not rel:
            continue
        parts = rel.split("/")
        if any(fnmatch.fnmatch(d, p) for d in parts[:-1] for p in REPO_SKIP_DIRS):
            continue
        if any(fnmatch.fnmatch(parts[-1].lower(), p) for p in REPO_SKIP_FILES):
            continue
        q = os.path.join(repo, *parts)
        try:
            size = os.path.getsize(q)
        except OSError:
            continue
        if size <= MAX_FILE_MB * 1024 * 1024:
            out.append((q, "_repo/" + rel, size))
    return out


# ★2026-09-30: 各担当の worktree で GitHub に載らず取り直せない物 (担当の回答で決めた物だけ)。
#   zip の中では _worktrees/<担当>/ の下に置く。足す時は requests/2026-09-30_backup_gaps_response.md を根拠に
WORKTREE_DIRS = {
    "revise/csv_output": r"C:\dev\iMak_revise\iMakRevise\csv_output",   # 日次 revise の差分記録 (値付けの履歴)
}


def pick_worktrees(dirs=None):
    """担当の回答で決めた worktree のフォルダ → [(path, zip内の名前, size)] (読むだけ)。"""
    out = []
    for name, top in (WORKTREE_DIRS if dirs is None else dirs).items():
        for root, _, names in os.walk(top):
            for n in names:
                q = os.path.join(root, n)
                try:
                    size = os.path.getsize(q)
                except OSError:
                    continue
                if size <= MAX_FILE_MB * 1024 * 1024:
                    out.append((q, f"_worktrees/{name}/" + os.path.relpath(q, top).replace("\\", "/"), size))
    return out


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


def zips_to_prune(names, keep=KEEP):
    """消す zip を選ぶ (純関数)。**日付で数えて** 新しい keep 日分を残す。

    ★2026-10-01: 以前は「個数」で14本残していた。同じ日に何本もできる (PC が落ちて取り直す) と、
      14本あっても14日分にならなかった (9/30 は3本 → 13日分しか残っていなかった)。
    """
    zs = sorted(f for f in names if f.startswith("iMak_daily_") and f.endswith(".zip"))
    days = sorted({f[len("iMak_daily_"):len("iMak_daily_") + 8] for f in zs})
    keep_days = set(days[-keep:])
    return [f for f in zs if f[len("iMak_daily_"):len("iMak_daily_") + 8] not in keep_days]


def prune(dest=DEST, keep=KEEP):
    old = zips_to_prune(os.listdir(dest), keep)
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
        if not a.dry_run:
            st["restore_kit_bad"] = refresh_restore_kit()
        files, skipped = pick_files()
        extra = pick_extra()
        repo = pick_repo()
        st["claude_files"] = len(extra)
        wt = pick_worktrees()
        st["repo_files"] = len(repo)
        st["worktree_files"] = len(wt)
        files = files + extra + repo + wt
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
            # ★2026-10-06: KAGOYA から戻した控え (offload_work/button/*/srv/manifest.json) は日付が
            #   1970-01-01 で、zip が「1980年より前は入れられない」と ValueError で全体を落としていた。
            #   1980年より前の日付は 1980-01-01 に丸めて入れる (中身はそのまま)
            with zipfile.ZipFile(local_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6,
                                 strict_timestamps=False) as z:
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
        # ★2026-10-01 全体点検: USB への写しは **この zip ができた直後に続けて** 呼ぶ。
        #   別の予約 (5:30) だと、朝のバックアップが遅れた日 (10/1 は落ちて 6:00 に取り直し) に前日の zip を写していた。
        #   USB が無い / 失敗しても、こちらのバックアップは成功のまま (結果は st["usb"] に残す)。
        try:
            import subprocess
            _u = subprocess.run([sys.executable, "-X", "utf8", os.path.join(HERE, "usb_backup.py")],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
            st["usb"] = ((_u.stdout or "").strip().splitlines() or ["(出力なし)"])[-1][:200]
            print(st["usb"])
        except Exception as _ue:                               # noqa: BLE001
            st["usb"] = f"⚠️要対応 USB へ写せず: {type(_ue).__name__}"
            print(st["usb"])
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
            # ★2026-09-29: バックアップの後に、DB の壊れと1ビット化けを見張る (前日の zip と比べる)
            try:
                import data_integrity_watch
                data_integrity_watch.run()
            except Exception as e:                                 # noqa: BLE001 見張りの失敗でバックアップは失敗にしない
                print(f"⚠️ データの見張りを動かせませんでした: {type(e).__name__}: {e}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")                # ⚠️ 等が cp932 で書けず見張りの表示が落ちた (2026-09-30)
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
