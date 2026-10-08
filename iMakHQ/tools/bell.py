#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""呼び鈴 (新生ブラボー・2026-10-09)。プログラムからでも、ブラボーの窓に呼び鈴を鳴らす。

★ユーザー確定 (2026-10-09): 担当間・プログラムからの依頼は **全部ブラボー経由**。直接のやり取りは無し
  (急ぎもブラボー経由・ブラボーが先に処理する)。依頼のファイルは今まで通り相手の requests/ に置き、
  呼び鈴だけをブラボーに鳴らす。ブラボーが判断して担当に渡す。

届け方 (2026-10-09 に実機で確かめた):
  - 家のプログラム       → 短い Claude (headless・Haiku) を1回起動し、家のブラボーの窓へ SendMessage
  - KAGOYA のプログラム → 短い Claude → KAGOYA の **中継の窓** (名前 RELAY・C:\dev\iMakRelay) → 中継がブラボーへ
    (短い Claude からは別の PC の窓が見えないが、同じ PC の窓には届く。普通の窓からは別の PC にも届く)
  - ブラボーが閉じていれば先に起動する (家のみ)

    python bell.py bravo --from 点検 --file hq/requests/2026-10-09_x.md --text "要点1行" [--urgent]
"""
from __future__ import annotations

import datetime as dt
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = r"C:/dev/iMak_data/hq/bell_log.jsonl"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HOME_HOST = "IMAK"                 # 家の PC (ブラボーが居る)
BRAVO_MATCH = "BRAVO"              # 家ではブラボーの窓、KAGOYA では中継の窓に送る
RELAY_MATCH = "RELAY"                # KAGOYA の中継の窓 (Relay.bat・名前 RELAY)


def compose(frm, file, text, urgent=False):
    """呼び鈴の文 (純関数)。ブラボーが台帳に1行付けられる形にする。"""
    head = "【急ぎ】" if urgent else ""
    return ("%s【依頼の呼び鈴】from=%s / file=%s / %s。ブラボーは判断してから担当へ (直接のやり取りは無し)"
            % (head, frm, file, text))


def _claude_send(target_match, message, timeout=150):
    """短い Claude を起動し、名前に target_match を含む窓へ1回 SendMessage させる。戻り: (ok, 出力)。"""
    prompt = ("Call ListAgents once. Find the agent whose name contains '%s' (if several, use the one marked "
              "interactive or Remote Control, with its [ref]). Call SendMessage once to it with exactly this message: "
              "<<<%s>>> . Then print only 'SENT' if it succeeded, or 'NOTFOUND' if no such agent exists. Do nothing else."
              % (target_match, message))
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE_CODE_", "ANTHROPIC_"))}
    try:
        r = subprocess.run(["claude", "-p", prompt, "--model", "haiku", "--allowedTools", "ListAgents,SendMessage"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL, env=env, creationflags=NOWIN)
    except Exception as e:                                     # noqa: BLE001
        return False, "起動できない: %s" % e
    out = "\n".join(l for l in (r.stdout or "").splitlines() if not l.startswith("Permission allow rule"))
    return ("SENT" in out), out.strip()[-200:]


def _ensure_bravo_open(wait_s=120):
    """家でブラボーが閉じていれば起動して、一覧に出るまで待つ。戻り: 説明文。"""
    sys.path.insert(0, HERE)
    import agent_board as AB
    roster = {r["key"]: r for r in AB.read_roster()}
    if "BRAVO" not in roster:
        return "ブラボーのショートカットが無い"
    folder = AB._norm(roster["BRAVO"]["folder"])
    if folder in {AB._norm(w.get("cwd")) for w in AB.list_windows()}:
        return "開いていた"
    ok, msg = AB.launch("BRAVO")
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(5)
        if folder in {AB._norm(w.get("cwd")) for w in AB.list_windows()}:
            time.sleep(20)                     # 一覧に出てから呼び鈴を受けられるまで少し待つ
            return "起動した"
    return "起動したが %d秒で一覧に出ない (%s)" % (wait_s, msg)


def _log(rec):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def to_bravo(frm, file, text, urgent=False):
    """ブラボーに呼び鈴を鳴らす (家なら直接・KAGOYA なら中継の窓経由)。戻り: ok。走行ログに1行出す。"""
    msg = compose(frm, file, text, urgent)
    host = socket.gethostname().upper()
    if host == HOME_HOST:
        state = _ensure_bravo_open()
        ok, out = _claude_send(BRAVO_MATCH, msg)
        route = "家→ブラボー (%s)" % state
    else:
        ok, out = _claude_send(RELAY_MATCH, msg)
        route = "%s→中継の窓→ブラボー" % host
    _log({"at": dt.datetime.now().isoformat(timespec="seconds"), "host": host, "from": frm, "file": file,
          "urgent": urgent, "route": route, "ok": ok, "out": out[-120:]})
    print("🔔 呼び鈴: %s / %s / %s" % ("鳴らした" if ok else "⚠️ 鳴らせなかった", route, file))
    return ok


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("bravo")
    b.add_argument("--from", dest="frm", required=True)
    b.add_argument("--file", required=True)
    b.add_argument("--text", required=True)
    b.add_argument("--urgent", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd != "bravo":
        ap.print_help()
        return 2
    return 0 if to_bravo(a.frm, a.file, a.text, a.urgent) else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
