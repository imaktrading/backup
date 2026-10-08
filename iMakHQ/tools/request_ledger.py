#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依頼台帳 (新生ブラボーの材料・2026-10-09)。全担当の requests を1依頼1行にし、問題の印を付ける。

★ユーザー確定 (2026-10-09): ブラボーの目的は「やり取りそのものを減らす = 発生源を直す」。
  集約と見える化はそのための手段。まず 10/2 以降の過去分に印を付け、どこから無駄な依頼が出ているかを出す。

印 (機械で付ける候補。最後はブラボー / 人が中身を見て確かめる):
  中身不足  … 依頼に「既に判明していること」「聞きたいこと」の節が無い
  滞り      … 回答まで24時間超 / 24時間たっても回答が無い
  蒸し返し  … 同じカード番号・鑑定番号・itemID が3本以上の依頼に出る
  重複      … 同じ話題 (日付を除いた名前) の依頼が7日以内に2本以上
  空振り    … 回答に「済み・既に・問題なし・不要・誤報」等 (やらなくてよかった疑い)
  宛先違い  … 回答に「②」「担当ではない」「宛先」等 (出す先を間違えた疑い)

    python request_ledger.py              # 10/2 以降を台帳にして、まとめを出す
    python request_ledger.py --since 2026-09-20
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import sys

DATA = r"C:/dev/iMak_data"
DIRS = {"hq": "HQ", "catalog": "カタログ", "dedupe": "重複くん", "inventory": "監視くん",
        "harvest": "抽出くん", "revise": "リバイス"}
OUT = os.path.join(DATA, "hq", "request_ledger.jsonl")

REPLY_SUFFIX = re.compile(r"_(response|processed|done|resolved|applied|ack|reply|answer|result|hq_done)(_|$)", re.I)
DRAFT_SUFFIX = re.compile(r"_(draft|question)$", re.I)
DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_")
RE_FROM = re.compile(r"(?:依頼者|発行者|回答者|書いた人)\s*[:：]\s*([^/\n|。]+)")
RE_CARD = re.compile(r"\b(?:[A-Z]{1,4}\d{1,3}[a-z]?-\d{2,3}|[A-Z]{2,3}-P-\d{2,3}|P-\d{3})\b")
RE_CERT = re.compile(r"(?:cert|鑑定番号)\s*[:#]?\s*(\d{8,9})", re.I)
RE_ITEM = re.compile(r"\b((?:35|82)\d{10})\b")
NOOP_WORDS = ("既に済", "済んでいます", "済んでいた", "問題なし", "問題ありません", "対応不要", "誤報", "正しく止めて",
              "直す物は無", "変更なし", "解決済み")
MISROUTE_WORDS = ("担当ではない", "こちらではない", "こちらの担当では", "宛先が違", "別の担当", "②が原因", "判定 ②", "判定: ②")


def kind_of(stem):
    if DRAFT_SUFFIX.search(stem):
        return "下書き"
    if REPLY_SUFFIX.search(stem):
        return "回答"
    return "依頼"


def topic_of(stem):
    """話題 = 日付と末尾の印 (_response 等) を除いた名前 (純関数)。"""
    s = DATE_PREFIX.sub("", stem)
    s = REPLY_SUFFIX.split(s)[0]
    s = re.sub(r"_(go|poc|feasibility|impl|v\d+|\d+)$", "", s)
    return s


def parse(path, wt):
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        body = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        body = ""
    head = body[:1500]
    m = RE_FROM.search(head)
    who = (m.group(1).strip() if m else "")[:30]
    prog = bool(re.search(r"自動|見張り|headless|\.py|Act\b|監査くん|点検", head))
    return {
        "file": os.path.basename(path), "wt": wt, "to": DIRS[wt], "stem": stem, "topic": topic_of(stem),
        "kind": kind_of(stem), "from": who, "program": prog,
        "at": dt.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="minutes"),
        "has_known": "既に判明" in body, "has_ask": "聞きたいこと" in body,
        "cards": sorted(set(RE_CARD.findall(body)))[:20],
        "certs": sorted(set(RE_CERT.findall(body)))[:20],
        "items": sorted(set(RE_ITEM.findall(body)))[:20],
        "noop": [w for w in NOOP_WORDS if w in body.replace("既に判明", "")][:3],
        "misroute": [w for w in MISROUTE_WORDS if w in body][:3],
        "size": len(body),
    }


def collect(since):
    rows = []
    for wt in DIRS:
        d = os.path.join(DATA, wt, "requests")
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if not f.endswith(".md"):
                continue
            p = os.path.join(d, f)
            if dt.datetime.fromtimestamp(os.path.getmtime(p)) < since:
                continue
            rows.append(parse(p, wt))
    return rows


def mark(rows, now):
    """印を付ける (純関数寄り)。依頼の行に marks を足して返す。"""
    reqs = [r for r in rows if r["kind"] == "依頼"]
    replies = collections.defaultdict(list)
    for r in rows:
        if r["kind"] == "回答":
            replies[(r["wt"], r["topic"])].append(r)
    # 蒸し返し: 同じ番号が3本以上の依頼に出る
    seen = collections.Counter()
    for r in reqs:
        for k in set(r["cards"] + r["certs"] + r["items"]):
            seen[k] += 1
    by_topic = collections.defaultdict(list)
    for r in reqs:
        by_topic[(r["wt"], r["topic"])].append(r)
    for r in reqs:
        m = []
        if not (r["has_known"] and r["has_ask"]):
            m.append("中身不足")
        rep = sorted(replies.get((r["wt"], r["topic"]), []), key=lambda x: x["at"])
        t0 = dt.datetime.fromisoformat(r["at"])
        if rep:
            dh = (dt.datetime.fromisoformat(rep[0]["at"]) - t0).total_seconds() / 3600
            r["reply_h"] = round(dh, 1)
            if dh > 24:
                m.append("滞り")
            if any(x["noop"] for x in rep):
                m.append("空振り?")
            if any(x["misroute"] for x in rep):
                m.append("宛先違い?")
        elif (now - t0).total_seconds() > 24 * 3600:
            r["reply_h"] = None
            m.append("滞り(未回答)")
        rep_keys = [k for k in set(r["cards"] + r["certs"] + r["items"]) if seen[k] >= 3]
        if rep_keys:
            m.append("蒸し返し")
            r["repeat_keys"] = sorted(rep_keys, key=lambda k: -seen[k])[:5]
        same = [x for x in by_topic[(r["wt"], r["topic"])] if x is not r
                and abs((dt.datetime.fromisoformat(x["at"]) - t0).days) <= 7]
        if same:
            m.append("重複")
        r["marks"] = m
    return reqs, seen


def summary(reqs, seen):
    out = []
    out.append("📒 依頼台帳: 依頼 %d本 (回答・下書きは除く)" % len(reqs))
    mc = collections.Counter(m for r in reqs for m in r["marks"])
    out.append("  印: " + " / ".join("%s %d" % kv for kv in mc.most_common()))
    src = collections.Counter(("プログラム" if r["program"] else (r["from"] or "不明")) for r in reqs)
    out.append("  依頼者: " + " / ".join("%s %d" % kv for kv in src.most_common(10)))
    to = collections.Counter(r["to"] for r in reqs)
    out.append("  宛先: " + " / ".join("%s %d" % kv for kv in to.most_common()))
    top = [(k, n) for k, n in seen.most_common(15) if n >= 3]
    out.append("  繰り返し出る番号 (3本以上): " + ", ".join("%s×%d" % kv for kv in top))
    tp = collections.Counter((r["to"], r["topic"]) for r in reqs)
    out.append("  同じ話題が複数: " + ", ".join("%s:%s×%d" % (a, b, n) for (a, b), n in tp.most_common(12) if n >= 2))
    return "\n".join(out)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    since = dt.datetime(2026, 10, 2)
    if "--since" in argv:
        since = dt.datetime.fromisoformat(argv[argv.index("--since") + 1])
    now = dt.datetime.now()
    rows = collect(since)
    reqs, seen = mark(rows, now)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in sorted(rows, key=lambda x: x["at"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(summary(reqs, seen))
    print("  台帳: %s (%d行)" % (OUT, len(rows)))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
