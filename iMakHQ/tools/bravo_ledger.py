#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ブラボーの依頼台帳 (新生ブラボー・2026-10-09)。

★目的 (ユーザー確定): **やり取りそのものを減らす = 発生源を直す**。台帳はそのための材料。
  ブラボーは来た依頼を右から左にせず、入口で判断する (本当に要るか・誤りは無いか・繰り返していないか・矛盾は無いか)。
  判断と状態を全部ここに残し、毎週「どこから無駄な依頼が出ているか」を数えて発生源の直しにつなげる。

正本は家のファイル `iMak_data/hq/bravo/ledger.jsonl` (1行 = 1つの出来事)。スプシ「既存メンテ」の
タブ「依頼台帳」は見る用の写し (sheet で全体を書き直す・書けなくても正本は残る)。

    python bravo_ledger.py add --from HQ --to カタログ --file catalog/requests/X.md --title "件名" [--urgent] [--program]
    python bravo_ledger.py check catalog/requests/X.md       # 判断の材料 (過去の同じ話題・同じカード・書式)
    python bravo_ledger.py judge B-20261009-001 --decision 通す --reason "..." [--marks 重複,蒸し返し]
    python bravo_ledger.py state B-20261009-001 受け取った|返した|閉じた
    python bravo_ledger.py list                    # 閉じていない物
    python bravo_ledger.py unfiled                 # 呼び鈴が来ていない (台帳に無い) 新しい依頼ファイル
    python bravo_ledger.py report [--days 7]       # 印・判断・依頼者ごとの件数
    python bravo_ledger.py sheet                   # スプシに写す
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = r"C:/dev/iMak_data"
LEDGER = os.path.join(DATA, "hq", "bravo", "ledger.jsonl")
TAB = "依頼台帳"
START = dt.datetime(2026, 10, 9)          # 台帳の始まり (これより前は request_ledger.py の洗い出しで見る)
DECISIONS = ("通す", "まとめる", "差し戻す", "自答", "発生源へ")
STATES = ("受付", "判断済", "受け取った", "返した", "閉じた")
MARKS = ("重複", "宛先違い", "中身不足", "蒸し返し", "矛盾", "空振り", "不要")
DIRS = {"hq": "HQ", "catalog": "カタログ", "dedupe": "重複くん", "inventory": "監視くん",
        "harvest": "抽出くん", "revise": "リバイス"}


# ---------------------------------------------------------------------------
# 台帳 (純関数 + 読み書き)
# ---------------------------------------------------------------------------
def load(path=LEDGER):
    ev = []
    if os.path.exists(path):
        for ln in open(path, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                try:
                    ev.append(json.loads(ln))
                except ValueError:
                    pass
    return ev


def fold(events):
    """出来事の列 → {id: 今の姿} (純関数)。"""
    out = {}
    for e in events:
        i = e.get("id")
        if e.get("ev") == "add":
            out[i] = dict(e, state="受付", marks=[], decision="", reason="", history=[e["at"] + " 受付"])
        elif i in out:
            r = out[i]
            if e.get("ev") == "judge":
                r.update(decision=e["decision"], reason=e.get("reason", ""), state="判断済",
                         marks=sorted(set(r["marks"]) | set(e.get("marks") or [])))
                r["history"].append("%s 判断 %s" % (e["at"], e["decision"]))
            elif e.get("ev") == "state":
                r["state"] = e["state"]
                r["history"].append("%s %s" % (e["at"], e["state"]))
                r["at_" + e["state"]] = e["at"]
    return out


def next_id(events, now):
    day = now.strftime("%Y%m%d")
    n = sum(1 for e in events if e.get("ev") == "add" and str(e.get("id", "")).startswith("B-" + day))
    return "B-%s-%03d" % (day, n + 1)


def append(rec, path=LEDGER):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _now():
    return dt.datetime.now().isoformat(timespec="minutes")


# ---------------------------------------------------------------------------
# 判断の材料 (check)
# ---------------------------------------------------------------------------
RE_CARD = re.compile(r"\b(?:[A-Z]{1,4}\d{1,3}[a-z]?-\d{2,3}|[A-Z]{2,3}-P-\d{2,3}|P-\d{3})\b")
RE_CERT = re.compile(r"(?:cert|鑑定番号)\s*[:#]?\s*(\d{8,9})", re.I)
RE_ITEM = re.compile(r"\b((?:35|82)\d{10})\b")


def _topic(stem):
    s = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", stem)
    s = re.split(r"_(?:response|processed|done|resolved|applied|go|question|draft)(?:_|$)", s)[0]
    return s


def keys_of(text):
    return (set(RE_CARD.findall(text)) | set("cert:" + c for c in RE_CERT.findall(text))
            | set("item:" + i for i in RE_ITEM.findall(text)))


def check(path):
    """判断の材料を文字で返す: 書式 / 同じ話題の過去の依頼 / 同じ番号が出る過去の依頼 (回答の頭も)。"""
    p = path if os.path.isabs(path) else os.path.join(DATA, path)
    body = open(p, encoding="utf-8", errors="replace").read()
    stem = os.path.splitext(os.path.basename(p))[0]
    topic, keys = _topic(stem), keys_of(body)
    lines = ["# 判断の材料: %s" % os.path.relpath(p, DATA).replace("\\", "/"), ""]
    lines.append("- 書式: 既に判明していること=%s / 聞きたいこと=%s / ①②の判定=%s"
                 % ("あり" if "既に判明" in body else "**無し**", "あり" if "聞きたいこと" in body else "**無し**",
                    "あり" if re.search(r"[①②]", body[:2000]) else "無し"))
    lines.append("- 出てくる番号: %s" % (", ".join(sorted(keys)[:15]) or "無し"))
    same_topic, same_key = [], collections.defaultdict(list)
    for q in glob.glob(os.path.join(DATA, "*", "requests", "*.md")):
        if os.path.abspath(q) == os.path.abspath(p):
            continue
        qs = os.path.splitext(os.path.basename(q))[0]
        if _topic(qs) == topic:
            same_topic.append(q)
        if keys:
            try:
                qb = open(q, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for k in keys & keys_of(qb):
                same_key[k].append(q)
    rel = lambda q: os.path.relpath(q, DATA).replace("\\", "/")
    lines.append("")
    lines.append("## 同じ話題の過去のファイル (%d本)" % len(same_topic))
    for q in sorted(same_topic)[-8:]:
        head = open(q, encoding="utf-8", errors="replace").read(300).splitlines()[:1]
        lines.append("- %s — %s" % (rel(q), head[0][:90] if head else ""))
    lines.append("")
    lines.append("## 同じ番号が出る過去のファイル")
    if not same_key:
        lines.append("- 無し")
    for k, qs in sorted(same_key.items(), key=lambda kv: -len(kv[1]))[:8]:
        lines.append("- **%s**: %d本 (最近: %s)" % (k, len(qs), ", ".join(rel(q) for q in sorted(qs)[-3:])))
    lines.append("")
    lines.append("→ 判断: 本当に要るか (済んでいないか・過去の回答で答えが出ていないか) / 宛先は正しいか (①②) /"
                 " 繰り返していないか / 過去の決定と矛盾していないか")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 台帳に無い新しい依頼 (呼び鈴が来なかった物)
# ---------------------------------------------------------------------------
REPLY = re.compile(r"_(?:response|processed|done|resolved|applied|ack|reply)(?:_[a-z]+)?$", re.I)


def unfiled(events, since=START):
    filed = {os.path.normpath(e.get("file", "")).lower() for e in events if e.get("ev") == "add"}
    out = []
    for wt in DIRS:
        for q in glob.glob(os.path.join(DATA, wt, "requests", "*.md")):
            if dt.datetime.fromtimestamp(os.path.getmtime(q)) < since:
                continue
            stem = os.path.splitext(os.path.basename(q))[0]
            if REPLY.search(stem):
                continue
            relp = os.path.relpath(q, DATA)
            if os.path.normpath(relp).lower() not in filed:
                out.append(relp.replace("\\", "/"))
    return sorted(out)


# ---------------------------------------------------------------------------
# まとめ (PDCA の C)
# ---------------------------------------------------------------------------
def report(cur, days=7, now=None):
    now = now or dt.datetime.now()
    rows = [r for r in cur.values() if (now - dt.datetime.fromisoformat(r["at"])).days < days]
    out = ["📒 依頼台帳 直近%d日: %d件" % (days, len(rows))]
    for name, key in (("判断", "decision"), ("状態", "state")):
        c = collections.Counter(r.get(key) or "未判断" for r in rows)
        out.append("  %s: %s" % (name, " / ".join("%s %d" % kv for kv in c.most_common())))
    mc = collections.Counter(m for r in rows for m in r.get("marks") or [])
    out.append("  印: %s" % (" / ".join("%s %d" % kv for kv in mc.most_common()) or "無し"))
    src = collections.Counter(r.get("from") for r in rows)
    out.append("  依頼者: %s" % " / ".join("%s %d" % kv for kv in src.most_common()))
    bad = collections.Counter(r.get("from") for r in rows if r.get("marks"))
    out.append("  印が付いた依頼者 (発生源の候補): %s" % (" / ".join("%s %d" % kv for kv in bad.most_common()) or "無し"))
    return "\n".join(out)


def sheet_rows(cur):
    head = ["受付ID", "受付", "依頼者", "プログラム", "宛先", "件名", "急ぎ", "判断", "理由", "印", "状態",
            "受け取った", "返した", "閉じた", "ファイル"]
    rows = [head]
    for r in sorted(cur.values(), key=lambda x: x["at"], reverse=True):
        rows.append([r["id"], r["at"].replace("T", " "), r.get("from", ""), "○" if r.get("program") else "",
                     r.get("to", ""), r.get("title", ""), "急ぎ" if r.get("urgent") else "", r.get("decision", ""),
                     r.get("reason", ""), ",".join(r.get("marks") or []), r.get("state", ""),
                     (r.get("at_受け取った") or "").replace("T", " "), (r.get("at_返した") or "").replace("T", " "),
                     (r.get("at_閉じた") or "").replace("T", " "), r.get("file", "")])
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("add")
    a.add_argument("--from", dest="frm", required=True)
    a.add_argument("--to", required=True)
    a.add_argument("--file", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--urgent", action="store_true")
    a.add_argument("--program", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("file")
    j = sub.add_parser("judge")
    j.add_argument("id")
    j.add_argument("--decision", required=True, choices=DECISIONS)
    j.add_argument("--reason", required=True)
    j.add_argument("--marks", default="")
    s = sub.add_parser("state")
    s.add_argument("id")
    s.add_argument("state", choices=STATES[2:])
    sub.add_parser("list")
    sub.add_parser("unfiled")
    r = sub.add_parser("report")
    r.add_argument("--days", type=int, default=7)
    sub.add_parser("sheet")
    o = ap.parse_args(argv)
    ev = load()
    cur = fold(ev)
    if o.cmd == "add":
        i = next_id(ev, dt.datetime.now())
        append({"ev": "add", "id": i, "at": _now(), "from": o.frm, "to": o.to, "file": o.file.replace("\\", "/"),
                "title": o.title, "urgent": o.urgent, "program": o.program})
        print("受付: %s" % i)
    elif o.cmd == "check":
        print(check(o.file))
    elif o.cmd == "judge":
        if o.id not in cur:
            print("その受付ID はありません: %s" % o.id)
            return 1
        marks = [m for m in o.marks.split(",") if m]
        bad = [m for m in marks if m not in MARKS]
        if bad:
            print("知らない印: %s (使える物: %s)" % (bad, ", ".join(MARKS)))
            return 1
        append({"ev": "judge", "id": o.id, "at": _now(), "decision": o.decision, "reason": o.reason, "marks": marks})
        print("判断: %s %s" % (o.id, o.decision))
    elif o.cmd == "state":
        if o.id not in cur:
            print("その受付ID はありません: %s" % o.id)
            return 1
        append({"ev": "state", "id": o.id, "at": _now(), "state": o.state})
        print("状態: %s %s" % (o.id, o.state))
    elif o.cmd == "list":
        op = [r for r in cur.values() if r["state"] != "閉じた"]
        print("閉じていない依頼: %d件" % len(op))
        for r in sorted(op, key=lambda x: (not x.get("urgent"), x["at"])):
            print("  %s %s %s→%s %s [%s%s] %s" % (r["id"], r["at"][5:16], r.get("from"), r.get("to"),
                                                 "急ぎ" if r.get("urgent") else "", r["state"],
                                                 ("・" + r["decision"]) if r.get("decision") else "", r.get("title", "")[:60]))
    elif o.cmd == "unfiled":
        u = unfiled(ev)
        print("呼び鈴が来ていない (台帳に無い) 新しい依頼: %d件" % len(u))
        for x in u:
            print("  " + x)
    elif o.cmd == "report":
        print(report(cur, o.days))
    elif o.cmd == "sheet":
        sys.path.insert(0, HERE)
        import sheet_io as S
        rows = sheet_rows(cur)
        S.write_rows_to_tab(TAB, rows)
        print("スプシ「既存メンテ」タブ「%s」に %d行を書いた" % (TAB, len(rows) - 1))
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    sys.exit(main())
