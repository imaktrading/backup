# -*- coding: utf-8 -*-
"""UNIQLO UT / GU を月1回 取り切る (2026-09-10 新設・ユーザー確定「月一くらいでいいやろ」).

## なぜ月1で回すか

**廃盤・コラボ終了で公式から消えるものが在り、消えたら二度と取れない。**

    実寸表          廃盤で消える (Wayback にも中身が無い。器だけ)
    原産国          廃盤で消える (商品ページに項目が無い。API だけが持つ)
    コラボ紹介文     **一番早く消える**。終わると URL は 200 のまま中身が UT トップになる

2026-09-09 実測: 2026-05 に取り込んだきりで **公式在庫 265件のうち 150件が抜けていた**。
気づいたのは、ユーザーが「公式在庫での出品物で見てみて」と言ったから。
= 気づく仕組み (`official_drift_uniqlo.py`) だけでは足りず、**取り込みまで自動で回す**。

## 何をするか (この順)

    1. uniqlo_ut.py --update            公式在庫の新商品を拾う
    2. uniqlo_ut_enrich.py --commit     画像 / 素材 / 原産国 / 透け感 / 説明
    3. uniqlo_ut_collab.py --commit     コラボ紹介文 (開催中しか取れない)
    4. gu_graphic_tee.py --commit       GU (取り込みと仕上げが1本)
    5. uniqlo_ut_sizechart.py --commit         実寸表 (Selenium)
    6. uniqlo_ut_sizechart.py --brand gu       同上 (GU)
    7. official_drift_uniqlo.py         突合して、残りを出す

★どれも **途中保存 + 済みは飛ばす** 作りなので、途中で落ちても次回が続きから走る。
★1本が落ちても **後ろを止めない**。落ちたものはログに出す。

実行:
    python tools/uniqlo_monthly.py            # そのまま実行
    python tools/uniqlo_monthly.py --dry-run  # 何を回すか見るだけ
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = Path("C:/dev/iMak_data/catalog/_uniqlo_monthly_log.txt")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

STEPS = [
    ("公式在庫の新商品",     ["scrapers/uniqlo_ut.py", "--update"]),
    ("UT の値を仕上げ",      ["scrapers/uniqlo_ut_enrich.py", "--commit"]),
    ("コラボ紹介文",         ["scrapers/uniqlo_ut_collab.py", "--commit"]),
    ("GU の取り込み",        ["scrapers/gu_graphic_tee.py", "--commit"]),
    ("UT の実寸表",          ["scrapers/uniqlo_ut_sizechart.py", "--commit"]),
    ("GU の実寸表",          ["scrapers/uniqlo_ut_sizechart.py", "--brand", "gu", "--commit"]),
    ("公式在庫との突合",      ["tools/official_drift_uniqlo.py"]),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    started = datetime.now()
    lines = [f"=== UNIQLO 月次 {started:%Y-%m-%d %H:%M} ==="]
    print(lines[0], flush=True)
    for name, cmd in STEPS:
        head = f"--- {name}: {' '.join(cmd)}"
        print(head, flush=True)
        lines.append(head)
        if a.dry_run:
            continue
        t0 = time.time()
        try:
            r = subprocess.run([sys.executable] + cmd, cwd=str(ROOT),
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=6 * 3600)
            tail = [x for x in (r.stdout or "").splitlines() if x.strip()][-6:]
            ok = "OK " if r.returncode == 0 else f"NG({r.returncode})"
        except Exception as e:
            tail, ok = [f"{type(e).__name__}: {str(e)[:120]}"], "NG"
        msg = f"    {ok} {int(time.time() - t0)}秒"
        print(msg, flush=True)
        lines.append(msg)
        for x in tail:
            print("      " + x, flush=True)
            lines.append("      " + x)
        # ★1本落ちても後ろを止めない (止めると次の月まで何も進まない)

    end = f"=== 終わり {datetime.now():%H:%M} (かかった時間 {datetime.now() - started}) ==="
    print(end, flush=True)
    lines.append(end)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


if __name__ == "__main__":
    main()
