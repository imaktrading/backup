# -*- coding: utf-8 -*-
"""手元の USB に「PC を入れ替えても戻せる一式」を写す (2026-09-30 ユーザー確定)。

Google ドライブの毎朝の zip に入れていない物 (鍵・パスワード類) を含めて、USB だけに置く。
USB を差したら1回走らせる:

    python usb_backup.py            # D: に写す
    python usb_backup.py --drive E

写す物 (D:/iMak_usb_backup/<日付>/ の下):
  secrets/      鍵・トークン・パスワード類 (クラウドには置かない)
  restore_kit/  予約タスクの控え・Python の部品一覧・復旧手順 (iMak_data/hq/restore_kit)
  最新の毎朝の zip (データ・カタログ DB・Claude の記憶)
写した後、全ファイルを読み直して大きさとハッシュを照合する。古い日付のフォルダは3つ残して消す。
"""
from __future__ import annotations

import argparse
import datetime
import glob
import hashlib
import os
import shutil
import sys

SECRETS = [r"C:\dev\iMak_data\credentials", r"C:\dev\iMak_data\secrets", r"C:\dev\iMak_data\secrets_backup",
           r"C:\dev\iMak\double-hold-421922-7c0d38d3f73d.json",          # Google スプシ用のサービスアカウント
           r"C:\dev\iMak\iMakeBayAPI\ebay_oauth_token*.json",
           r"C:\dev\iMak\iMakTCG\API key.txt"]
RESTORE_KIT = r"C:\dev\iMak_data\hq\restore_kit"
DAILY = r"G:\マイドライブ\iMak_backup\daily"
KEEP = 3


def _md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


def plan():
    """[(元, USB 内の相対パス)] (読むだけ)。"""
    out = []
    for pat in SECRETS:
        for src in glob.glob(pat):
            if os.path.isdir(src):
                for root, dirs, names in os.walk(src):
                    dirs[:] = [d for d in dirs if d != "__pycache__"]
                    for n in names:
                        q = os.path.join(root, n)
                        out.append((q, os.path.join("secrets", os.path.basename(src), os.path.relpath(q, src))))
            else:
                out.append((src, os.path.join("secrets", os.path.basename(src))))
    for root, _, names in os.walk(RESTORE_KIT):
        for n in names:
            q = os.path.join(root, n)
            out.append((q, os.path.join("restore_kit", os.path.relpath(q, RESTORE_KIT))))
    zs = sorted(glob.glob(os.path.join(DAILY, "iMak_daily_*.zip")))
    if zs:
        out.append((zs[-1], os.path.basename(zs[-1])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", default="D")
    a = ap.parse_args()
    root = f"{a.drive}:\\iMak_usb_backup"
    dest = os.path.join(root, datetime.date.today().strftime("%Y%m%d"))
    items = plan()
    bad = []
    for src, rel in items:
        dst = os.path.join(dest, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        if os.path.getsize(dst) != os.path.getsize(src) or _md5(dst) != _md5(src):
            bad.append(rel)
    old = sorted(d for d in os.listdir(root) if d.isdigit())[:-KEEP]
    for d in old:
        shutil.rmtree(os.path.join(root, d))
    mb = sum(os.path.getsize(s) for s, _ in items) / 1e6
    print(("✅ 正常" if not bad else f"⚠️要対応 照合が合わない {bad}") +
          f": {dest} に {len(items)}件 {mb:.0f}MB / 消した古い世代 {old}")
    return 1 if bad else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
