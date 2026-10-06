#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定期処理の点検: あるべき姿 (schedule_expected.json) と実物を突き合わせ、異常を担当に知らせる (2026-10-06)。

★ユーザー「神風の定期タブ。これは過不足ないの？停止中は正常なの？ここの状態を監視して、
  異常は検知できて各担当へ確認する仕組みはあるの？」→「あるべき姿に修正して」。
  それまでの定期タブは **この PC の Windows 予約だけ**を出していて、
  - 夜の束 (job_queue)・KAGOYA・LAPTOP の監視くんが出ていなかった
  - 移設・廃止して止めた予約 33本が「停止中」として並び、本当に止まっている物と見分けがつかなかった
  - 結果を色で出すだけで、誰にも知らせていなかった

実物の取り方:
  home      … この PC の Windows 予約 (名前に iMak を含む物)
  kagoya    … KAGOYA の Windows 予約 (ssh 1回)
  job_queue … 夜の束の状態 (job_queue_state.json の last_ok)
  laptop    … 商品管理シート O列 (売り切れチェック時間) の一番新しい時刻 = 監視くんが最後に見た時刻

知らせ方: 担当ごとに requests/ に `YYYY-MM-DD_schedule_audit.md` を書く (同じ異常は24時間に1回だけ)。
  監視くん (LAPTOP) 宛は受け箱にも写す (LAPTOP からは requests/ が見えないため)。

    python schedule_audit.py            # 点検して結果を書く・知らせる
    python schedule_audit.py --dry-run  # 点検だけ (知らせない)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED = r"C:/dev/iMak_data/hq/schedule_expected.json"
RESULT = r"C:/dev/iMak_data/hq/schedule_audit_last.json"
NOTIFIED = r"C:/dev/iMak_data/hq/schedule_audit_notified.json"
JOBQ_STATE = r"C:/dev/iMak_data/hq/job_queue_state.json"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RENOTIFY_H = 24

# Windows の結果コード
OK_CODES = {0}
RUNNING = 267009            # 実行中
NEVER = 267011              # まだ一度も動いていない
OVERLAP = 2147946720        # 0x800710E0: 前の回が終わっていないので今回は見送られた

_PS = ("Get-ScheduledTask | Where-Object { $_.TaskName -like '*iMak*' } | ForEach-Object { "
       "$i = $_ | Get-ScheduledTaskInfo; [pscustomobject]@{ name = $_.TaskName; state = [string]$_.State; "
       "last = $(if ($i.LastRunTime) { $i.LastRunTime.ToString('s') } else { '' }); "
       "result = [int64]$i.LastTaskResult; "
       "next = $(if ($i.NextRunTime) { $i.NextRunTime.ToString('s') } else { '' }) } } | ConvertTo-Json -Compress")


# ---------------------------------------------------------------------------
# 純関数
# ---------------------------------------------------------------------------
def _ts(s):
    try:
        return dt.datetime.fromisoformat(str(s)[:19])
    except (TypeError, ValueError):
        return None


def judge(exp, actual, now):
    """あるべき1件と実物 (None = 見つからない) → (状態, 説明)。純関数。

    状態: ok / running / missing / disabled / failed / stale / overlap
    """
    if actual is None:
        return "missing", "予約が見つかりません"
    if actual.get("state") == "Disabled":
        return "disabled", "止まっています (あるべき姿では動いているはず)"
    last = _ts(actual.get("last"))
    res = actual.get("result")
    if res == RUNNING or actual.get("state") == "Running":
        return "running", "実行中"
    age_h = (now - last).total_seconds() / 3600 if last else None
    if res not in OK_CODES and res not in (None, NEVER, OVERLAP):
        return "failed", "前回 失敗 (結果 %s・%s)" % (res, last.strftime("%m/%d %H:%M") if last else "?")
    if age_h is None or age_h > exp["max_age_h"]:
        when = last.strftime("%m/%d %H:%M") if last else "記録なし"
        return "stale", "%s時間以内に動くはずが、最後は %s" % (exp["max_age_h"], when)
    if res == OVERLAP:
        return "overlap", "前の回が長引いて今回が見送られた (%s)" % last.strftime("%m/%d %H:%M")
    return "ok", "正常 (%s)" % last.strftime("%m/%d %H:%M")


def audit(conf, home, kagoya, jobq, laptop_last, now):
    """全体の点検。home/kagoya = {名前: 実物} / jobq = job_queue_state / laptop_last = datetime。純関数。

    Returns: {"rows": [...], "retired": [...], "unknown": [...]}
    """
    rows = []
    for e in conf["expected"]:
        w = e["where"]
        if w == "home":
            a = home.get(e["name"])
        elif w == "kagoya":
            a = kagoya.get(e["name"]) if kagoya is not None else {"state": "?", "last": "", "result": None}
        elif w == "job_queue":
            s = (jobq or {}).get(e["name"]) or {}
            a = None if not s else {"state": "Running" if s.get("pid") else "Ready",
                                    "last": s.get("last_ok") or "",
                                    "result": 0 if s.get("last_rc") in (0, None) else s.get("last_rc")}
        else:                                   # laptop
            a = {"state": "Ready", "last": laptop_last.isoformat() if laptop_last else "", "result": 0}
        if w == "kagoya" and kagoya is None:
            st, why = "unknown", "KAGOYA に繋がらず確かめられません"
        else:
            st, why = judge(e, a, now)
        rows.append({"name": e["name"], "where": w, "owner": e["owner"], "what": e.get("what", ""),
                     "status": st, "why": why,
                     "last": (a or {}).get("last", ""), "next": (a or {}).get("next", "")})
    for name, q in (conf.get("ask") or {}).items():
        a = home.get(name)
        rows.append({"name": name, "where": "home", "owner": q["owner"], "what": "",
                     "status": "ask", "why": "担当に確認中: " + q["q"],
                     "last": (a or {}).get("last", ""), "next": ""})
    known = {e["name"] for e in conf["expected"]} | set(conf.get("retired") or {}) | set(conf.get("ask") or {})
    unknown = [{"name": n, "where": "home", "owner": "HQ", "what": "", "status": "unknown_task",
                "why": "あるべき姿の台帳に無い予約 (足したなら台帳にも書く)",
                "last": a.get("last", ""), "next": a.get("next", "")}
               for n, a in sorted(home.items()) if n not in known]
    retired = [{"name": n, "why": r} for n, r in sorted((conf.get("retired") or {}).items())]
    return {"rows": rows + unknown, "retired": retired}


BAD = {"missing", "disabled", "failed", "stale", "unknown_task", "ask", "unknown"}


def to_notify(rows, notified, now, renotify_h=RENOTIFY_H):
    """知らせる物 {担当: [行]}。同じ (名前, 状態) は renotify_h 時間に1回だけ。純関数。"""
    out = {}
    for r in rows:
        if r["status"] not in BAD:
            continue
        key = "%s|%s" % (r["name"], r["status"])
        last = _ts(notified.get(key))
        if last and (now - last).total_seconds() < renotify_h * 3600:
            continue
        out.setdefault(r["owner"], []).append(r)
    return out


def note_body(owner, rows, now):
    """担当宛の知らせの本文 (純関数)。"""
    lines = ["# 定期処理の点検: 確認してください (%s)" % now.strftime("%Y-%m-%d %H:%M"), "",
             "- 依頼日: %s / 依頼者: 定期処理の点検 (schedule_audit.py・ADV 作成) / 宛: %s / 緊急度: 中 / フェーズ: 調査"
             % (now.strftime("%Y-%m-%d"), owner), "",
             "あるべき姿の台帳 `C:/dev/iMak_data/hq/schedule_expected.json` と実物を突き合わせて、",
             "次が合いませんでした。直したら台帳も合わせてください (止めたのが正しいなら retired に理由を書く)。", "",
             "## 既に判明していること (再調査するな)", ""]
    for r in rows:
        lines.append("- **%s** (%s): %s" % (r["name"], r["where"], r["why"]))
    lines += ["", "## 聞きたいこと (未回答のみ)", "",
              "上のそれぞれについて: 直したか / 止めたのが正しいならその理由。", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 実物を取る (I/O)
# ---------------------------------------------------------------------------
def home_tasks():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=90, creationflags=NOWIN)
    data = json.loads(r.stdout or "[]")
    return {t["name"]: t for t in (data if isinstance(data, list) else [data])}


def kagoya_tasks():
    """KAGOYA の予約。繋がらなければ None (= 確かめられない。異常とも正常とも言わない)。"""
    try:
        sys.path.insert(0, HERE)
        import kagoya_offload as K
        import base64
        # 文字のまま送ると、向こうのシェルが $_ などを先に展開して壊す → 符号化して渡す
        enc = base64.b64encode(_PS.encode("utf-16-le")).decode("ascii")
        rc, out = K._ssh(K._cfg(), "powershell -NoProfile -NonInteractive -EncodedCommand " + enc, timeout=90)
        if rc != 0:
            return None
        # 後ろに PowerShell の進み具合 (#< CLIXML ...) が付くので、先頭の JSON だけ読む
        i = min([k for k in (out.find("["), out.find("{")) if k >= 0], default=-1)
        if i < 0:
            return None
        data, _ = json.JSONDecoder().raw_decode(out[i:])
        return {t["name"]: t for t in (data if isinstance(data, list) else [data])}
    except Exception:                                          # noqa: BLE001
        return None


def laptop_last():
    try:
        sys.path.insert(0, HERE)
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "console"))
        import sheet_io as S
        import watcher as W
        return W.latest_check(S._product_ws().col_values(15)[1:])
    except Exception:                                          # noqa: BLE001
        return None


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                          # noqa: BLE001
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def notify(by_owner, conf, now):
    """担当の requests/ に書く (同じ日は追記)。監視くんは受け箱にも。書いたファイルを返す。"""
    wrote = []
    for owner, rows in by_owner.items():
        d = (conf.get("owners") or {}).get(owner)
        if not d or not os.path.isdir(d):
            continue
        fn = "%s_schedule_audit.md" % now.strftime("%Y-%m-%d")
        path = os.path.join(d, fn)
        body = note_body(owner, rows, now)
        mode = "a" if os.path.exists(path) else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(("\n\n---\n\n" if mode == "a" else "") + body)
        wrote.append(path)
        if owner == "監視くん":
            try:
                sys.path.insert(0, HERE)
                import request_box as RB
                RB.post("監視くん", fn, body, "定期処理の点検")
            except Exception as e:                             # noqa: BLE001
                print("  ⚠ 受け箱に写せませんでした: %s" % e)
    return wrote


def main(argv=None):
    dry = "--dry-run" in (argv if argv is not None else sys.argv[1:])
    conf = _load(EXPECTED, None)
    if not conf:
        print("台帳が読めません: %s" % EXPECTED)
        return 1
    now = dt.datetime.now()
    res = audit(conf, home_tasks(), kagoya_tasks(), _load(JOBQ_STATE, {}), laptop_last(), now)
    res["at"] = now.isoformat(timespec="seconds")
    bad = [r for r in res["rows"] if r["status"] in BAD]
    for r in res["rows"]:
        mark = "❌" if r["status"] in BAD else "✅"
        print("%s %-42s %-9s %-6s %s" % (mark, r["name"], r["where"], r["owner"], r["why"]))
    print("止めてあって正常 (移設・廃止): %d本" % len(res["retired"]))
    print("異常・要確認: %d件" % len(bad))
    _write_json(RESULT, res)
    if dry:
        return 0
    notified = _load(NOTIFIED, {})
    by_owner = to_notify(res["rows"], notified, now)
    for p in notify(by_owner, conf, now):
        print("  📨 知らせた: %s" % p)
    for rows in by_owner.values():
        for r in rows:
            notified["%s|%s" % (r["name"], r["status"])] = now.isoformat(timespec="seconds")
    _write_json(NOTIFIED, notified)
    return 0


if __name__ == "__main__":
    sys.exit(main())
