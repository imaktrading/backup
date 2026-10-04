#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA 再仕入れを1回で: ① 目視 → ② 在庫を戻す → ③ 確認 (2026-10-04)。

★ユーザー「①したら②③って、一連でできないの？ボタン分けずに」。
  ② (psa_restock_build) は「RESTOCK確定」タブの分の在庫を API で 0→1 に戻すだけで、人の確認を挟まない。
  ③ (psa_restock_writeback) は ② の後に続けて回す前提。人が決めるのは ① の目視だけなので、続けて走らせる。
  - ① が失敗したら ②③ は走らせない
  - ②③ のボタンはやり直し用に残す (このファイルは呼ぶだけで中身を持たない)

    python psa_restock_chain.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STEPS = [
    ("① 目視", ["psa_resource_gate.py"]),
    ("② 在庫を戻す", ["psa_restock_build.py"]),
    ("③ 確認", ["psa_restock_writeback.py"]),
]


def run_chain(steps=STEPS, run=None):
    """順に走らせる。途中で失敗したらそこで止める。戻り値 = 最後に走った手順の終了コード。

    ② は単独で押された時は最後に自分で ③ を呼ぶ (在庫を戻した時だけ)。ここでは PSA_RESTOCK_CHAIN=1 で
    それを止め、③ を毎回1回だけ回す (戻す物が無くても ③ が走る = ③ だけ失敗した時のやり直しになる)。
    """
    env = dict(os.environ, PSA_RESTOCK_CHAIN="1")
    run = run or (lambda args: subprocess.call([sys.executable, "-X", "utf8", "-u"] + args, cwd=HERE, env=env))
    rc = 0
    for name, args in steps:
        print("\n" + "=" * 60 + f"\n▶ PSA 再仕入れ {name}\n" + "=" * 60, flush=True)
        rc = run(args)
        if rc != 0:
            print(f"⚠️ {name} が失敗 (returncode={rc}) → ここで止めます。続きはボタンから", flush=True)
            return rc
    print("\n✅ PSA 再仕入れ ①②③ 完了", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(run_chain())
