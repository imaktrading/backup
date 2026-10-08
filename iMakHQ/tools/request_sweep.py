#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依頼の見回り (2026-10-09)。呼び鈴が漏れた依頼を拾う、12時間おきの網。

★ユーザー「各担当間でスムースにやり取りができる仕組みとルールと徹底方法を考えてよ、滞るやろ」
  →「基本は呼び鈴で、穴は12時間にできる？」。
  基本は **依頼を書いた窓がその場で呼び鈴を鳴らす**。それでも漏れる物 (プログラムが書いた依頼・
  閉じていた窓・届いたか返ってこない KAGOYA / LAPTOP) を、窓口 (ADV / HQ) が12時間おきに拾う。
  ★常駐も、時刻で Claude を起動することもしない (見張り役 9/14・事務員 10/1 の廃止理由)。
    窓口の窓が自分の中の予約 (CronCreate) でこれを走らせ、出た一覧に呼び鈴を鳴らす。

やること:
  1. 各担当の「相手が返す番」の依頼を数える (worktree_board.pending_for と同じ判定)
  2. この PC の担当で窓が閉じていれば起動する (起動した窓は最初に requests/ を見る決まり)
  3. 担当ごとに「呼び鈴の文」を出す → 窓口が SendMessage で鳴らす

    python request_sweep.py            # 見回り (閉じている担当は起動する)
    python request_sweep.py --no-wake  # 数えるだけ
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# worktree → (呼び鈴の宛先 / この PC で起動するキー / 届け方の注意)
OWNERS = {
    "catalog": ("CATALOG", None, "KAGOYA の窓。閉じていたら KAGOYA で開くまで届かない"),
    "dedupe": ("📚重複くん", "DEDUPE", ""),
    "harvest": ("HARVEST", "HARVEST", ""),
    "revise": ("🔄️リバイスくん", "REVISE", ""),
    "inventory": ("💻LAPTOP", None, "LAPTOP の窓。受け箱 (request_box.py) にも写すこと"),
    "hq": ("🤖HQ", "HQ", ""),
}


def age_h(path, now=None):
    return ((now or time.time()) - os.path.getmtime(path)) / 3600


def bell_text(wt, files):
    """呼び鈴の文 (純関数)。古い順にファイル名を並べる。"""
    names = ", ".join(os.path.basename(str(f)).rsplit(".", 1)[0] for f in files)
    return ("%s/requests に未返球 %d件 (12時間おきの見回り): %s。"
            "受け取ったら1行返し、済んでいる物は _processed / _response で閉じてください。" % (wt, len(files), names))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    wake = "--no-wake" not in argv
    import worktree_board as WB
    total, out = 0, []
    for wt, (to, key, note) in OWNERS.items():
        mine = WB.pending_for(wt)[0]
        mine = sorted(mine, key=lambda p: os.path.getmtime(p))
        total += len(mine)
        if not mine:
            continue
        woke = ""
        if wake and key:
            try:
                import agent_board as AB
                ok, msg = AB.launch(key)
                woke = "起動した" if ok else "開いている"
            except Exception as e:                             # noqa: BLE001
                woke = "起動できない (%s)" % e
        oldest = age_h(mine[0])
        out.append((to, wt, mine, woke, note, oldest))
    print("📮 依頼の見回り: 相手が返す番 %d件 / 担当 %d者" % (total, len(out)))
    for to, wt, mine, woke, note, oldest in out:
        print("  - %s (%s): %d件・いちばん古いのは %.0f時間前%s%s"
              % (wt, to, len(mine), oldest, ("・" + woke) if woke else "", ("・" + note) if note else ""))
    if out:
        print("\n→ 窓口はそれぞれに呼び鈴を鳴らす (宛先 / 文):")
        for to, wt, mine, _w, _n, _o in out:
            print("  [%s] %s" % (to, bell_text(wt, mine)))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
