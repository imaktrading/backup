# -*- coding: utf-8 -*-
"""UT の取りこぼし潰しを **最後まで** 走らせる (2026-09-11 ユーザー指示「完走させろ」).

順番 (どれも済みは飛ばす + 途中保存。1本落ちても後ろを止めない):

    1. 前後の品番を歩く (reviews API)            … 起こしと並行してよい (叩く先が違う)
    2. 廃盤候補の起こし (Wayback) が終わるのを待つ … Wayback は同時に叩くと弾かれる
    3. 前後で見つけた分を起こす (Wayback)
    4. 保存済みの Wayback ページから取りこぼしを起こす (--from-raw)
    5. 色・サイズ・価格を保存済み JSON から埋める
    6. 実寸表 (公式に在る分だけ。Selenium 3本)
    7. 在庫
    8. Fashion Press の突き合わせ / 年表 / カタログ HTML

★各ステップは **別の処理** として起動する。同じ処理の中で import し直すと、
  古い版のモジュールと混ざって落ちる (2026-09-11 に 611件ぶんを失った)。

実行:
    python tools/ut_finish_all.py --wait-pid <起こしの PID>
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = Path("C:/dev/iMak_data/catalog/_ut_finish_all.log")
PY = sys.executable

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def start(name: str, args: list[str]) -> subprocess.Popen:
    out = open(Path("C:/dev/iMak_data/catalog") / f"_ut_step_{name}.log", "a", encoding="utf-8")
    log(f"開始 {name}: {' '.join(args)}")
    return subprocess.Popen([PY, "-u", *args], cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT,
                            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})


def run(name: str, args: list[str]) -> None:
    p = start(name, args)
    rc = p.wait()
    log(f"終了 {name}: rc={rc}")          # ★落ちても後ろを止めない


def pid_alive(pid: int) -> bool:
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in r.stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-pid", type=int, help="先に走っている廃盤候補の起こしの PID")
    a = ap.parse_args()

    nb = start("neighbors", ["scrapers/uniqlo_ut_gone_sweep.py", "--neighbors", "--workers", "5"])
    if a.wait_pid:
        log(f"廃盤候補の起こし (PID {a.wait_pid}) を待つ")
        while pid_alive(a.wait_pid):
            time.sleep(30)
        log("廃盤候補の起こし 終了")
    rc = nb.wait()
    log(f"終了 neighbors: rc={rc}")
    run("revive_neighbors", ["scrapers/uniqlo_ut_revive.py", "--commit", "--workers", "2",
                             "--pids-file", "C:/dev/iMak_data/catalog/_ut_gone_neighbor_candidates.txt"])
    run("revive_from_raw", ["scrapers/uniqlo_ut_revive.py", "--from-raw", "--commit"])
    run("colors", ["migrations/2026-09-11_uniqlo_ut_colors_from_saved.py", "--commit"])
    shards = [start(f"sizechart{k}", ["scrapers/uniqlo_ut_sizechart.py", "--commit",
                                       "--shard", f"{k}/3"]) for k in range(3)]
    for k, p in enumerate(shards):
        log(f"終了 sizechart{k}: rc={p.wait()}")
    run("stock", ["scrapers/uniqlo_ut_stock.py", "--commit"])
    run("fp_gap", ["tools/fp_ut_gap.py"])
    run("timeline", ["tools/fp_ut_timeline_html.py"])
    run("catalog_html", ["tools/ut_catalog_html.py"])
    log("=== 全部終わり ===")


if __name__ == "__main__":
    main()
