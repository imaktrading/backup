# -*- coding: utf-8 -*-
"""公式サイトの絵を共有領域に保存し、目視画面で出せるようにする (2026-09-22).

なぜ: onepiece-cardgame.com / gundam-gcg.com は `Cross-Origin-Resource-Policy: same-site` を返し、
      ブラウザは他のページ (目視画面 127.0.0.1:8770) への埋め込みを拒否する。
      ワンピ 2,243行・ガンダム 817行は日本語の絵がこの2サイトにしか無く、目視で何も見えなかった
      (ユーザー「目視のタイミングじゃないとわからん」)。
      目視画面は共有領域のファイルを `/catalog/img?p=` で出せる (ドンの絵と同じ経路)。

やること: 絵を `_official_images/<category>/<ファイル名>` に保存し、images の先頭にその path を足す。
          公式 URL は消さない (後ろに残す)。以後 `api.upsert` が同じ path を先頭に足す。

途中保存: 1枚ずつ保存。保存済みのファイルは取り直さない (再実行は残りだけ)。

実行:
  python tools/mirror_blocked_images.py            # dry-run
  python tools/mirror_blocked_images.py --commit
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def run(commit: bool) -> None:
    db = sqlite3.connect(str(api._DB_PATH), timeout=120)
    rows = [(rid, cat, json.loads(im or "[]")) for rid, cat, im in db.execute(
        "SELECT id, category, images FROM products")]
    todo = [(rid, cat, L) for rid, cat, L in rows
            if L and api._is_blocked_host(L[0])]
    print(f"=== 公式の絵を保存 ({'APPLY' if commit else 'DRY-RUN'}) — 対象 {len(todo)}行 ===")
    have = sum(1 for _, cat, L in todo if api._mirror_path(cat, L[0]).exists())
    print(f"  保存済み {have}枚は取り直さない")
    if not commit:
        return
    now = datetime.now().isoformat(timespec="seconds")
    got = fail = 0
    for i, (rid, cat, L) in enumerate(todo, 1):
        p = api._mirror_path(cat, L[0])
        if not p.exists():
            try:
                req = urllib.request.Request(L[0], headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
                got += 1
                time.sleep(0.2)
            except Exception as e:
                fail += 1
                print(f"  ✗ {L[0]}: {type(e).__name__}")
                continue
        local = str(p).replace("\\", "/")
        db.execute("UPDATE products SET images=?, updated_at=? WHERE id=?",
                   (json.dumps([local] + [u for u in L if u != local], ensure_ascii=False), now, rid))
        db.commit()
        if i % 200 == 0:
            print(f"  … {i}/{len(todo)} (取得 {got} / 失敗 {fail})", flush=True)
    db.close()
    print(f"\n取得 {got}枚 / 失敗 {fail}枚 / 適用 {len(todo) - fail}行")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    run(ap.parse_args().commit)


if __name__ == "__main__":
    main()
