# -*- coding: utf-8 -*-
"""TCG 4カテゴリを月1回 取り切る (2026-09-10 新設・ユーザー確定「月１でいいかと」).

## なぜ月1でよいか

新弾が出ても **PSA10 が出回るまで時間がある** (鑑定に出して返ってくるまで)。
出品に要るのは「PSA が鑑定した個体が市場に出てから」なので、月1で間に合う。
ユーザー確定 (2026-09-10):「PSA10の認証が取れる期間があるから、月１でいいかと」。

## なぜ要るか

**気づく仕組み (`official_drift_*.py`) は在ったが、誰も回していなかった。**
最後に走ったのは 2026-09-05 で、それも手で回した分。
週次タスク `iMak Catalog Integrity Weekly` は整合性の監査とシート更新だけで、
公式突合も新弾の取り込みも入っていない (しかも 2026-09-07 は異常終了していた)。

UNIQLO で同じことが起きていた (2026-05 の取り込みきりで公式在庫の150件が抜けていた)。
**気づく仕組みだけでは足りない。取り込みまで自動で回す。**

## 何をするか (この順)

    1. 各 scraper --update        新弾のカードを拾う (済みは飛ばす)
    2. finish_ingest --commit     出品に出る値を付ける (Set / rarity / 英語名 / HP 等)
    3. official_drift_*           公式と突き合わせて、残っている差分を出す
    4. claim_check                検収 (全項目)

★どれも **途中保存 + 済みは飛ばす**。途中で落ちても次回が続きから走る。
★1本が落ちても後ろを止めない (止めると翌月まで何も進まない)。

実行:
    python tools/tcg_monthly.py
    python tools/tcg_monthly.py --dry-run
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = Path("C:/dev/iMak_data/catalog/_tcg_monthly_log.txt")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CATS = ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")

STEPS = (
    [(f"新弾を拾う ({c})", [f"scrapers/{c.replace('_tcg', '_tcg').replace('dragonball_scg', 'dragonball_scg')}.py", "--update"])
     for c in ("pokemon_tcg", "one_piece_tcg", "dragonball_scg", "gundam_tcg")]
    + [(f"仕上げ ({c})", ["tools/finish_ingest.py", "--cat", c, "--commit"]) for c in CATS]
    + [
        ("公式突合 (ポケモン)",       ["tools/official_drift_pokemon.py", "--all"]),
        ("公式突合 (ワンピース)",     ["tools/official_drift_check.py", "--n", "200"]),
        ("公式突合 (バンダイ2種)",    ["tools/official_drift_bandai.py"]),
        ("検収",                     ["tools/claim_check.py"]),
    ]
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    started = datetime.now()
    lines = [f"=== TCG 月次 {started:%Y-%m-%d %H:%M} ==="]
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
            tail = [x for x in (r.stdout or "").splitlines() if x.strip()][-8:]
            ok = "OK " if r.returncode == 0 else f"NG({r.returncode})"
        except Exception as e:
            tail, ok = [f"{type(e).__name__}: {str(e)[:120]}"], "NG"
        msg = f"    {ok} {int(time.time() - t0)}秒"
        print(msg, flush=True)
        lines.append(msg)
        for x in tail:
            print("      " + x, flush=True)
            lines.append("      " + x)

    end = f"=== 終わり {datetime.now():%H:%M} (かかった時間 {datetime.now() - started}) ==="
    print(end, flush=True)
    lines.append(end)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


if __name__ == "__main__":
    main()
