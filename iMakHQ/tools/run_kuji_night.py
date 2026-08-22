#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_kuji_night.py — 一番くじの夜間分を通しで回す (2026-08-22)。

★`prefetch-live` は **候補を集めるだけ**で、詳細ページ (状態/送料/セラー名/星/
  発送までの日数) は取らない。それは `prefetch-detail` の役目。
  ボタンに片方だけを繋いでいたので、目視画面のセラー情報が空のままだった。
  夜にやることは2つで1組なので、1本にまとめる。

  ① prefetch-live   候補を集める
  ② prefetch-detail 候補の詳細を取る (昼の待ち時間を無人化する本体)

片方が失敗しても もう片方は走らせる (①が空振りでも ②は前日分を温められる)。
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = [("候補を集める", ["prefetch-live", "40"]),
         ("候補の詳細を取る", ["prefetch-detail", "200"])]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    ng = 0
    for label, args in STEPS:
        print("\n===== %s (%s) =====" % (label, " ".join(args)), flush=True)
        r = subprocess.run([sys.executable, "-X", "utf8",
                            os.path.join(HERE, "ichibankuji_restock.py")] + args,
                           cwd=HERE, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        if r.returncode != 0:
            ng += 1
            print("⚠️ %s が失敗しました (returncode=%s)。続けます" % (label, r.returncode))
    if ng:
        print("\n⚠️要対応 %d/%d ステップが失敗しました" % (ng, len(STEPS)))
    else:
        print("\n✅ 夜間分 完了 (候補 + 詳細)")
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(main())
