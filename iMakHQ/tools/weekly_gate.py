# -*- coding: utf-8 -*-
"""夜の束の中で「週1回で足りる手順」を週1回だけ通す関門 (2026-10-01 全体点検)。

    python weekly_gate.py <名前> --check   # 前回から6日たっていれば 0 (走らせる) / まだなら 1 (飛ばす)
    python weekly_gate.py <名前> --done N  # N=0 (成功) の時だけ「走った日」を記録する

曜日で決めないのは、夜の束が0時をまたいで再開すると曜日が変わり、その週を丸ごと飛ばすため。
失敗した (N≠0) 時は記録しないので、次の晩にもう一度走る。
記録: C:/dev/iMak_data/hq/night_state/weekly.json
"""
import json
import os
import sys
from datetime import datetime, timedelta

PATH = r"C:/dev/iMak_data/hq/night_state/weekly.json"
EVERY = timedelta(days=6)


def load(path=PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def due(last, now, every=EVERY):
    """前回 (ISO 文字列 or 空) から every 以上たったか (純関数)。読めない値は「走らせる」。"""
    try:
        return now - datetime.fromisoformat(last) >= every
    except (TypeError, ValueError):
        return True


def main(argv, path=PATH, now=None):
    now = now or datetime.now()
    if len(argv) < 2:
        print(__doc__)
        return 2
    name, op = argv[0], argv[1]
    d = load(path)
    if op == "--check":
        if due(d.get(name), now):
            return 0
        print(f"[weekly-skip] {name}: 前回 {d.get(name)} から6日たっていない (週1回の手順)")
        return 1
    if op == "--done":
        if (argv[2] if len(argv) > 2 else "1") == "0":
            d[name] = now.isoformat(timespec="seconds")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(path + ".tmp", path)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
