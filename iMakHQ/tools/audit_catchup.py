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
# headless Act(csv_auditor→claude -p)の完了レポート。監査run_logとは別に surface する
# (Act は監査終了後 5-6分 BG 実行 → 完了が対話中HQに届かず「ボーっと」に見える問題の対策)。
ACT_REPORT_DIR = os.path.join(_HERE, "..", "review_logs")
ACT_MARKER = r"C:/dev/iMak_data/hq/last_act_catchup.txt"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _last_ts(marker=None):
    marker = marker or MARKER   # call時解決(monkeypatch対応)
    try:
        return float(open(marker, encoding="utf-8").read().strip())
    except Exception:
        return 0.0


def _save_ts(ts, marker=None):
    marker = marker or MARKER   # call時解決(monkeypatch対応)
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(str(ts))
    except Exception:
        pass


def collect_fresh_act_reports(report_dir, since):
    """marker より新しい ng_act_*.md を mtime 昇順で返す(純関数, test可)。"""
    out = []
    for f in glob.glob(os.path.join(report_dir, "ng_act_*.md")):
        try:
            if os.path.getmtime(f) > since:
                out.append(f)
        except Exception:
            continue
    out.sort(key=os.path.getmtime)
    return out


def summarize_act_report(text, max_lines=20):
    """Act レポート本文から要点部を抜粋(純関数, test可)。

    '要点' を含む行以降を優先(なければ先頭)、空行を除いて max_lines 行まで。
    """
    lines = text.splitlines()
    body = lines
    for i, ln in enumerate(lines):
        if "要点" in ln:
            body = lines[i:]
            break
    body = [ln for ln in body if ln.strip()][:max_lines]
    return "\n".join(body)


def report_acts():
    """未報告の headless Act 完了レポートを surface(監査blockとは独立)。"""
    since = _last_ts(ACT_MARKER)
    reports = collect_fresh_act_reports(ACT_REPORT_DIR, since)
    if not reports:
        return  # 静かに(監査block が既にステータスを出す)
    newest = reports[-1]
    try:
        text = open(newest, encoding="utf-8", errors="replace").read()
    except Exception:
        return
    print("\n[HQへの指示] 前回以降に headless Act(監査くん→自動対応)が完了している。"
          "以下の Act 結果(①CSV可否/②UP/③依頼・提案)を確認しユーザーに冒頭で報告すること。")
    print(f"🤖 未報告 Act {len(reports)}件。最新: {os.path.basename(newest)}")
    print(summarize_act_report(text))
    _save_ts(max(os.path.getmtime(f) for f in reports), ACT_MARKER)


# 監査/生成を含む run_log か(価格抵抗など非監査ログは除外)。head=先頭数KB。
_AUDIT_MARKERS = ("CSV UPシグナル", "監査", "件を処理", "csv_auditor")


def is_audit_log(head):
    return any(m in head for m in _AUDIT_MARKERS)


def report_audits():
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


def main():
    report_audits()   # 監査run_log(CSV化分/非化分)
    report_acts()     # headless Act 完了レポート(③依頼・提案)


if __name__ == "__main__":
    main()
