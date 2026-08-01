# -*- coding: utf-8 -*-
"""現在地 — 「今どうなっているか」の**唯一の答え** (read-only)。

なぜ要るか (2026-08-01):
    ユーザーが ALPHA と BRAVO に同じ「現在地は?」を聞いたら **違う答えが返ってきた**。
    状態は動いていなかった (実測: 19:40〜19:54 で共有ファイルの変化ゼロ) ので、
    原因はデータではなく **各セッションが「現在地」を自分で定義して作文していたこと**。

    → 現在地は **このコマンドの出力** と定める。セッションは作文しない。
      「一回決めたら狂いようがない。それが program」(ユーザー 2026-08-01)。

使い方:
    python iMakHQ/tools/status_now.py

    現在地を聞かれたら **これを実行して、出力をそのまま示す**。
    補足したいことがあれば出力の**後ろに**足す。出力自体を書き換えない。
"""
import datetime
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # C:/dev/iMak
DAILY = r"C:\Users\imax2\.claude\projects\c--dev-iMak\memory\daily_report.md"


def _run(args, cwd=ROOT):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                    # noqa: BLE001
        return f"(取得失敗: {type(e).__name__}: {e})"


def _board():
    return _run([sys.executable, os.path.join(HERE, "worktree_board.py")])


def _hoju():
    """補URL: 対象(補0本)の件数と内訳。catalog DB / スプシを読むので数十秒かかる場合あり。"""
    code = (
        "import sys;sys.path.insert(0,r'%s');"
        "import psa_hoju_fill as H,datetime;"
        "rows=H._read_high();cache=H._load_cache();today=datetime.date.today().isoformat();"
        "tg=H.select_backfill_targets(rows,max_backups=1);"
        "nc=sum(1 for t in tg if not (cache.get(t['itemID']) or {}).get('mercari'));"
        "hc=sum(1 for t in tg if H._cache_candidate_urls(cache.get(t['itemID'])));"
        "live=len(H.select_backfill_targets(rows,max_backups=99));"
        "print(f'live PSA(TCG) {live}件 / 補0本 {len(tg)}件 "
        "(未探索{nc} / 候補あり{hc} / 候補なし{len(tg)-nc-hc})')" % HERE
    )
    return _run([sys.executable, "-c", code]).strip()


def _commits():
    out = _run(["git", "log", "--since=midnight",
                "--format=%h %ad %s", "--date=format:%H:%M"])
    lines = [ln for ln in out.split("\n") if ln.strip()]
    return lines


def _next_actions():
    """daily_report 最上段の「次に何をやるか」表をそのまま出す (作文しない)。"""
    try:
        with open(DAILY, encoding="utf-8") as f:
            t = f.read()
    except OSError as e:
        return [f"(daily_report 読めず: {e})"]
    m = re.search(r"##\s*4\.\s*いま誰待ちか[^\n]*\n(.*?)(?=\n## |\n---)", t, re.S)
    if not m:
        return ["(daily_report に『いま誰待ちか』節が見つからない)"]
    return [ln for ln in m.group(1).split("\n") if ln.strip()]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass
    now = datetime.datetime.now()
    print(f"# 現在地 {now:%Y-%m-%d %H:%M}  (status_now.py の出力 = これが唯一の答え)\n")

    print("## 1. 各担当の未処理\n")
    print(_board().rstrip())

    print("\n## 2. 出品の数字\n")
    print("  " + _hoju())

    print("\n## 3. 今日の commit\n")
    cs = _commits()
    if cs:
        for ln in cs:
            print("  " + ln)
        print(f"  ---- 計 {len(cs)}本")
    else:
        print("  (今日はまだ commit なし)")

    print("\n## 4. 次にやること (daily_report 最上段より・原文)\n")
    for ln in _next_actions():
        print("  " + ln)

    print("\n---")
    print("この出力が現在地です。補足は後ろに足してよいが、出力自体は書き換えないこと。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
