#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仕入上限 (cost_sanity) を **共有データ領域に書き出す**。

    python iMakHQ/tools/export_cost_sanity.py

★2026-09-20 抽出くんからの依頼。トレジャーハントで仕入上限の門を付けたいが、
  Harvest の作業場所の `pricing_engine.py` は 4/25 の古い版で `cost_sanity` が無い。
  規約上 Harvest は他の作業場所を読めず、自前で ¥70,000 と書くのも禁止。

★**数字は二重に持たない**。値を決めるのは `iMakeBayAPI/config/global.yaml` の1か所だけで、
  ここはそれを **写して置くだけ**。他の作業場所は この JSON を読む。
  ずれないように、HQ のテストが「JSON と yaml が同じか」を毎回見張る
  (`tests/test_cost_sanity_export_20260920.py`)。

★読む側 (Harvest 等) は **ファイルが無ければ走らない**こと (fail-closed)。
  7時間走って上限を素通しするより、走る前に止まる方がよい。
"""
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
API = os.path.normpath(os.path.join(HERE, "..", "..", "iMakeBayAPI"))
OUT = r"C:/dev/iMak_data/shared/cost_sanity.json"


def build():
    """global.yaml の cost_sanity を そのまま読む (I/O)。ここで値を作らない。"""
    if API not in sys.path:
        sys.path.insert(0, API)
    import config_loader
    cfg = dict(config_loader.get_cost_sanity() or {})
    cfg["_source"] = "iMakeBayAPI/config/global.yaml (cost_sanity)"
    cfg["_note"] = ("値を決めるのは global.yaml の1か所だけ。これは写し。"
                    "読む側は このファイルが無ければ走らないこと (fail-closed)")
    cfg["_exported_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    return cfg


def main(_argv):
    cfg = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    print("仕入上限を書き出しました → %s" % OUT)
    print("  上限 ¥%s / 下限 ¥%s / 有効 %s"
          % (format(int(cfg.get("max_jpy") or 0), ","),
             format(int(cfg.get("min_jpy") or 0), ","), cfg.get("enabled")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
