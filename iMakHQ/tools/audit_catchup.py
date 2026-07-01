#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""セッション開始時キャッチアップ: 前回報告以降の新しい監査/生成の問題提起を出す (2026-07-01)。

ユーザー方針: クリア(/clear)しても、新セッション開始時に HQ が未報告の監査結果を自動で拾って
「CSV化分の問題 + 非化分の原因→対策」を出す(判断・指示は人)。SessionStart フックから呼ばれ、
標準出力がセッション context に注入される → HQ がそれを見てユーザーに報告する。

marker(前回報告時刻)より新しい run_log を対象に build_problem_report を回す。
新規なし→ "(新しい監査なし)" のみ(ノイズにしない)。marker は最新に更新。
"""
import glob
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
RUN_LOG_DIR = os.path.join(_HERE, "..", "run_logs")
MARKER = r"C:/dev/iMak_data/hq/last_audit_catchup.txt"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _last_ts():
    try:
        return float(open(MARKER, encoding="utf-8").read().strip())
    except Exception:
        return 0.0


def _save_ts(ts):
    try:
        os.makedirs(os.path.dirname(MARKER), exist_ok=True)
        with open(MARKER, "w", encoding="utf-8") as f:
            f.write(str(ts))
    except Exception:
        pass


# 監査/生成を含む run_log か(価格抵抗など非監査ログは除外)。head=先頭数KB。
_AUDIT_MARKERS = ("CSV UPシグナル", "監査", "件を処理", "csv_auditor")


def is_audit_log(head):
    return any(m in head for m in _AUDIT_MARKERS)


def main():
    since = _last_ts()
    logs = glob.glob(os.path.join(RUN_LOG_DIR, "*.log"))
    # 監査/生成を含む run_log のうち marker より新しいもの
    fresh = []
    for f in logs:
        try:
            if os.path.getmtime(f) <= since:
                continue
            head = open(f, encoding="utf-8", errors="replace").read(4000)
            if is_audit_log(head):
                fresh.append(f)
        except Exception:
            continue
    if not fresh:
        print("(新しい監査なし)")
        return
    fresh.sort(key=os.path.getmtime)
    # 最新の run_log(生成+自己監査を含む)で問題提起。build_problem_report は log から
    # CSV化分(監査findings)+ 非化分(drop原因→対策)を統合。
    sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..")))
    try:
        from control_panel import build_problem_report
    except Exception as e:
        print(f"(build_problem_report 読込失敗: {type(e).__name__})")
        _save_ts(max(os.path.getmtime(f) for f in fresh))
        return
    newest = fresh[-1]
    log = open(newest, encoding="utf-8", errors="replace").read()
    rep = build_problem_report(log)
    print("[HQへの指示] 前回セッション以降に未報告の監査がある。以下の問題提起を"
          "ユーザーに冒頭で報告し、指示を仰ぐこと(判断は人)。")
    print(f"🔔 前回以降の監査 {len(fresh)}件。最新: {os.path.basename(newest)}")
    print(rep or "(問題提起なし=クリーン。入稿OK)")
    _save_ts(max(os.path.getmtime(f) for f in fresh))


if __name__ == "__main__":
    main()
