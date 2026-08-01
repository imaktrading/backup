# -*- coding: utf-8 -*-
"""残務の取り合いを防ぐ — 着手する前に1件 claim する (2026-08-01 制定)。

なぜ要るか (実害の手前):
    2026-08-01 に窓口が 2 (Advisor / 出品専任) から 4 (+ALPHA/BRAVO) に増えた。
    4窓口は **同じ worktree (C:/dev/iMak master) / 同じ .git/index / 同じ daily_report** を
    共有していて、見える範囲が完全に同じ。この状態でユーザーが4窓口に
    「残務を着手して」と同じ指示を出すと、**全員が同じ表の1件目に着手する**。

    commit dd8061f では「着手前に board を見て daily_report に名乗る」と口約束にしたが、
    実測すると `worktree_board.py` も `status_now.py` も **『着手』を読む処理を持っていない**。
    さらに名乗りは起動時に1回読むだけなので、走行中の他窓口の追記は見えない。
    = 取り合いを防ぐ仕組みは無い。「一回決めたら狂いようがない。それが program」に反する。

    → **claim を取れた窓口だけが着手できる**ようにする。取れなければ次の件に回る。

なぜ requests dir と別に「残件」を置くか:
    board が扱えるのは `C:/dev/iMak_data/*/requests/` に**ファイルとして在るもの**だけ。
    daily_report 最上段の残件表 (catalog draft §B/§C・段階2・build_card_query 等) は
    ファイル実体が無いので board に出ず、claim もできなかった。
    → `_backlog/` に1件1ファイルで置き、claim 対象に載せる。

なぜ git の外 (C:/dev/iMak_data/) に置くか:
    claim は実行時の状態で、毎回作られては消える。git 管理下に置くと git status が常に汚れ、
    他セッションの commit に紛れ込む (2026-08-01 `4df3f8a` に4ファイルが乗った事故 / その後
    `45d9f23` で dispatcher の lock を git から外したのと同じ理由)。

使い方:
    python iMakHQ/tools/claim.py                     # 一覧 (誰が何を持っているか)
    python iMakHQ/tools/claim.py next                # 最優先の未claim を1件取って中身を出す
    python iMakHQ/tools/claim.py take <ID>           # 指定して取る
    python iMakHQ/tools/claim.py done <ID> --note ".."# 完了 (残件は _done へ、claim 解放)
    python iMakHQ/tools/claim.py release <ID>        # 取ったが着手しない時に返す
    python iMakHQ/tools/claim.py add "<件名>" --priority 3 --detail "..."   # 残件を足す

    窓口 (Advisor/出品専任/ALPHA/BRAVO) は cwd から自動判定する。--who で明示上書き可。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_ROOT = Path(r"C:\dev\iMak_data")
BACKLOG = DATA_ROOT / "_backlog"
BACKLOG_DONE = BACKLOG / "_done"
CLAIMS = DATA_ROOT / "_claims"
CLAIM_LOG = CLAIMS / "_log.jsonl"

# claim を取ったまま窓口が落ちる/寝る ことは普通に起きる。永久ロックにすると
# 誰も触れない件が生まれるので、一定時間で **奪える** ようにする (奪取は警告付き)。
STALE_HOURS = 6.0

# 取る順番。ここを固定しないと「最優先」が窓口ごとにブレて、また作文が始まる。
#   要返球   : 他 worktree を止めている (グローバル規約「自分の回答待ちで他を止めない」)
#   残件     : ユーザーが「残務」と呼んでいる本体
#   レビュー : 窓口が draft を検算する仕事。急がないが滞留する
KIND_ORDER = {"要返球": 0, "残件": 1, "レビュー待ち": 2}

DESK_BY_DIR = {
    "imakadvisor": "Advisor",
    "imakalpha": "ALPHA",
    "imakbravo": "BRAVO",
    "imak": "出品専任",
}

RE_PRIORITY = re.compile(r"^\s*[-*]\s*優先度\s*[:：]\s*(\d+)", re.M)
RE_BLOCKED = re.compile(r"^\s*[-*]\s*状態\s*[:：]\s*(待ち.*)$", re.M)
RE_TITLE = re.compile(r"^#\s*(.+?)\s*$", re.M)
RE_UNSAFE = re.compile(r"[^0-9A-Za-z_.-]")


# ---------------------------------------------------------------- 窓口の判定
def detect_who(cwd: str | None = None) -> str:
    """cwd から窓口名を判定する。判定できなければ ""。

    窓口はそれぞれ自分のフォルダを cwd にして起動する (commit dd8061f)。
    環境変数 IMAK_DESK があればそれを優先する (headless 実行用)。
    """
    env = os.environ.get("IMAK_DESK", "").strip()
    if env:
        return env
    p = Path(cwd or os.getcwd()).resolve()
    for part in [p] + list(p.parents):
        name = part.name.lower()
        if name in DESK_BY_DIR:
            return DESK_BY_DIR[name]
    return ""


# ---------------------------------------------------------------- 残件 (_backlog)
def _parse_backlog(path: Path) -> dict:
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        body = ""
    m = RE_TITLE.search(body)
    title = m.group(1) if m else path.stem
    mp = RE_PRIORITY.search(body)
    mb = RE_BLOCKED.search(body)
    return {
        "id": f"backlog:{path.stem}",
        "kind": "残件",
        "title": title,
        "path": path,
        "priority": int(mp.group(1)) if mp else 5,
        "blocked": mb.group(1).strip() if mb else "",
        "mtime": path.stat().st_mtime if path.exists() else 0.0,
        "body": body,
    }


def backlog_items() -> list[dict]:
    if not BACKLOG.is_dir():
        return []
    return [_parse_backlog(p) for p in sorted(BACKLOG.glob("*.md")) if p.is_file()]


def add_backlog(title: str, priority: int = 5, detail: str = "",
                who: str = "", blocked: str = "") -> Path:
    """残件を1件足す。file 名は日付 + 件名の slug。"""
    BACKLOG.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    slug = RE_UNSAFE.sub("_", title)[:40].strip("_") or "item"
    stem = f"{now:%Y-%m-%d}_{slug}"
    p = BACKLOG / f"{stem}.md"
    n = 2
    while p.exists():
        p = BACKLOG / f"{stem}_{n}.md"
        n += 1
    lines = [f"# {title}", "",
             f"- 優先度: {priority}",
             f"- 起票: {now:%Y-%m-%d %H:%M} [{who or detect_who() or '?'}]"]
    if blocked:
        lines.append(f"- 状態: {blocked}")
    lines += ["", detail.strip(), ""]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


# ---------------------------------------------------------------- requests
def request_items() -> list[dict]:
    """board が出す 🔴要返球 と 🟡レビュー待ち を claim 対象に載せる。

    判定ロジックは board と **同じ関数を呼ぶ** (二重定義すると board と claim で
    見えている件数がズレて、また窓口ごとに答えが割れる)。
    """
    try:
        import worktree_board as wb
    except Exception:                                          # noqa: BLE001
        return []
    out: list[dict] = []
    for wt, label in wb.WORKTREES:
        try:
            mine, _theirs, drafts = wb.pending_for(wt)
        except Exception:                                      # noqa: BLE001
            continue
        for kind, paths in (("要返球", mine), ("レビュー待ち", drafts)):
            for p in paths:
                out.append({
                    "id": f"{wt}:{p.stem}",
                    "kind": kind,
                    "title": f"[{label}] {p.name}",
                    "path": p,
                    "priority": 5,
                    "blocked": "",
                    "mtime": p.stat().st_mtime,
                    "body": "",
                })
    return out


# ---------------------------------------------------------------- 並べ方
def _sort_key(it: dict):
    # 残件は優先度順、requests は古い順 (止めている時間が長いものを先に)
    return (KIND_ORDER.get(it["kind"], 9), it["priority"], it["mtime"])


def all_items() -> list[dict]:
    return sorted(backlog_items() + request_items(), key=_sort_key)


# ---------------------------------------------------------------- claim 本体
def claim_path(item_id: str) -> Path:
    return CLAIMS / (RE_UNSAFE.sub("_", item_id) + ".json")


def read_claim(item_id: str) -> dict | None:
    """claim 中なら dict を返す (stale なら {"stale": True} 付き)。無ければ None。"""
    p = claim_path(item_id)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        d = {"who": "?", "id": item_id}
    age_h = (time.time() - p.stat().st_mtime) / 3600
    d["age_hours"] = age_h
    d["stale"] = age_h >= STALE_HOURS
    return d


def _log(event: str, **kw) -> None:
    CLAIMS.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now().isoformat(timespec="seconds"), "event": event}
    rec.update(kw)
    with open(CLAIM_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def take(item_id: str, who: str, title: str = "", kind: str = "",
         force: bool = False) -> dict:
    """1件 claim する。戻り: {ok, reason, holder}.

    **同時実行に耐えること**が全て。`O_CREAT|O_EXCL` で作れた側だけが勝つ。
    「存在チェックしてから書く」だと 4窓口が同時に走った時に両方通る。
    """
    CLAIMS.mkdir(parents=True, exist_ok=True)
    p = claim_path(item_id)
    cur = read_claim(item_id)
    if cur and not (force or cur.get("stale")):
        return {"ok": False, "reason": f"{cur.get('who', '?')} が保持中", "holder": cur}
    payload = json.dumps({
        "id": item_id, "who": who, "title": title, "kind": kind,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "pid": os.getpid(),
    }, ensure_ascii=False)
    if cur:
        # stale / force の奪取。**黙って奪わない** (誰から奪ったかを log に残す)
        p.write_text(payload, encoding="utf-8")
        _log("steal", id=item_id, who=who, From=cur.get("who"),
             age_hours=round(cur.get("age_hours", 0), 1))
        return {"ok": True, "reason": f"{cur.get('who', '?')} の放置 claim を引き取った",
                "holder": cur}
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        cur = read_claim(item_id)
        return {"ok": False, "reason": f"{(cur or {}).get('who', '?')} が保持中",
                "holder": cur}
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
    _log("take", id=item_id, who=who, title=title, kind=kind)
    return {"ok": True, "reason": "", "holder": None}


def release(item_id: str, who: str) -> dict:
    cur = read_claim(item_id)
    if not cur:
        return {"ok": False, "reason": "claim されていない"}
    if cur.get("who") != who and not cur.get("stale"):
        return {"ok": False, "reason": f"{cur.get('who')} の claim (自分のではない)"}
    claim_path(item_id).unlink(missing_ok=True)
    _log("release", id=item_id, who=who)
    return {"ok": True, "reason": ""}


def done(item_id: str, who: str, note: str = "") -> dict:
    """完了。残件は `_done/` に移す。requests は **ファイル名を触らない**。

    requests の決着は `_response.md` / `_processed.md` を書く既存フロー (board の
    `CLOSED_SUFFIXES`) が唯一の正。ここで勝手にリネームすると決着判定が二重になる。
    """
    cur = read_claim(item_id)
    if cur and cur.get("who") != who and not cur.get("stale"):
        return {"ok": False, "reason": f"{cur.get('who')} の claim (自分のではない)"}
    moved = None
    if item_id.startswith("backlog:"):
        src = BACKLOG / f"{item_id.split(':', 1)[1]}.md"
        if src.exists():
            BACKLOG_DONE.mkdir(parents=True, exist_ok=True)
            body = src.read_text(encoding="utf-8", errors="replace").rstrip() + "\n"
            body += (f"\n---\n- 完了: {datetime.now():%Y-%m-%d %H:%M} [{who}]\n"
                     + (f"- 記録: {note}\n" if note else ""))
            dest = BACKLOG_DONE / src.name
            dest.write_text(body, encoding="utf-8")
            src.unlink()
            moved = dest
    claim_path(item_id).unlink(missing_ok=True)
    _log("done", id=item_id, who=who, note=note)
    return {"ok": True, "reason": "", "moved": moved,
            "hint": "" if moved else "requests の決着は `_response.md` 等を書くこと (ここでは名前を変えない)"}


def next_item(who: str) -> dict:
    """最優先の未claim を1件取る。取れない件は飛ばして次を試す。

    「一覧を見せて選ばせる」だと4窓口分の選択をユーザーがやることになる。
    順番は `_sort_key` で固定してあるので、窓口が選ぶ余地は要らない。
    """
    skipped = []
    for it in all_items():
        if it["blocked"]:
            skipped.append((it, f"待ち: {it['blocked']}"))
            continue
        r = take(it["id"], who, title=it["title"], kind=it["kind"])
        if r["ok"]:
            return {"ok": True, "item": it, "note": r["reason"], "skipped": skipped}
        skipped.append((it, r["reason"]))
    return {"ok": False, "item": None, "note": "取れる残務が無い", "skipped": skipped}


# ---------------------------------------------------------------- 表示
def _age(ts: float) -> str:
    h = (time.time() - ts) / 3600
    if h < 1:
        return f"{int(h * 60)}分前"
    if h < 48:
        return f"{int(h)}時間前"
    return f"{int(h / 24)}日前"


def render_list(items: list[dict] | None = None) -> str:
    items = all_items() if items is None else items
    free, held, blocked = [], [], []
    for it in items:
        c = read_claim(it["id"])
        if it["blocked"]:
            blocked.append((it, c))
        elif c:
            held.append((it, c))
        else:
            free.append((it, c))
    out = [f"# 残務ボード ({len(free)}件が取れる / {len(held)}件が着手中 / "
           f"{len(blocked)}件が待ち)", ""]
    if held:
        out.append("## 着手中 (触らない)")
        for it, c in held:
            mark = " ⚠️放置" if c.get("stale") else ""
            out.append(f"- 🔒 **[{c.get('who', '?')}]**{mark} `{it['id']}` {it['title']}"
                       f" ({int(c.get('age_hours', 0) * 60)}分)")
        out.append("")
    if free:
        out.append("## 取れる (優先度順)")
        for it, _ in free:
            pr = f"P{it['priority']} " if it["kind"] == "残件" else ""
            out.append(f"- ⬜ [{it['kind']}] {pr}`{it['id']}` {it['title']}"
                       f" ({_age(it['mtime'])})")
        out.append("")
    if blocked:
        out.append("## 待ち (取れない)")
        for it, _ in blocked:
            out.append(f"- ⛔ `{it['id']}` {it['title']} — {it['blocked']}")
        out.append("")
    if not (free or held or blocked):
        out.append("残務なし。")
    out.append("→ 着手は `python iMakHQ/tools/claim.py next` "
               "(取れた1件だけやる。取れなかった件は他窓口が持っている)")
    return "\n".join(out)


# ---------------------------------------------------------------- CLI
def _who_or_die(args) -> str:
    who = args.who or detect_who()
    if not who:
        print("窓口を判定できない。--who Advisor|出品専任|ALPHA|BRAVO を付けるか "
              "環境変数 IMAK_DESK を設定すること。", file=sys.stderr)
        raise SystemExit(2)
    return who


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="残務の claim (取り合い防止)")
    ap.add_argument("--who", default="", help="窓口名 (既定: cwd から自動判定)")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="一覧")
    sub.add_parser("next", help="最優先の未claim を1件取る")
    for name, helptext in (("take", "指定して取る"), ("release", "返す")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("id")
    sp = sub.add_parser("done", help="完了")
    sp.add_argument("id")
    sp.add_argument("--note", default="")
    sp = sub.add_parser("add", help="残件を足す")
    sp.add_argument("title")
    sp.add_argument("--priority", type=int, default=5)
    sp.add_argument("--detail", default="")
    sp.add_argument("--blocked", default="", help="外部待ち等で着手できない理由")
    args = ap.parse_args(argv)

    cmd = args.cmd or "list"
    if cmd == "list":
        print(render_list())
        return 0
    if cmd == "next":
        who = _who_or_die(args)
        r = next_item(who)
        if not r["ok"]:
            print(f"# 取れる残務なし ({who})\n")
            for it, why in r["skipped"]:
                print(f"- {it['id']} — {why}")
            return 1
        it = r["item"]
        print(f"# [{who}] 着手: {it['title']}\n")
        print(f"- ID: `{it['id']}`  (種別 {it['kind']})")
        print(f"- 実体: {it['path']}")
        if r["note"]:
            print(f"- ⚠️ {r['note']}")
        if r["skipped"]:
            print(f"- 飛ばした {len(r['skipped'])}件: "
                  + " / ".join(f"{i['id']}({w})" for i, w in r["skipped"][:5]))
        body = it.get("body") or ""
        if not body and it["path"] and Path(it["path"]).exists():
            body = Path(it["path"]).read_text(encoding="utf-8", errors="replace")
        print("\n---\n" + body.rstrip()[:4000])
        print(f"\n---\n完了したら `python iMakHQ/tools/claim.py done {it['id']} --note \"...\"`")
        return 0
    if cmd == "take":
        who = _who_or_die(args)
        it = next((x for x in all_items() if x["id"] == args.id), None)
        r = take(args.id, who, title=(it or {}).get("title", ""),
                 kind=(it or {}).get("kind", ""))
        print(("取った" if r["ok"] else "取れない") + f": {args.id} — {r['reason'] or 'OK'}")
        return 0 if r["ok"] else 1
    if cmd == "release":
        r = release(args.id, _who_or_die(args))
        print(("返した" if r["ok"] else "返せない") + f": {args.id} — {r['reason'] or 'OK'}")
        return 0 if r["ok"] else 1
    if cmd == "done":
        who = _who_or_die(args)
        r = done(args.id, who, args.note)
        if not r["ok"]:
            print(f"完了にできない: {r['reason']}")
            return 1
        print(f"完了: {args.id}" + (f" → {r['moved']}" if r.get("moved") else ""))
        if r.get("hint"):
            print(f"※ {r['hint']}")
        return 0
    if cmd == "add":
        who = _who_or_die(args)
        p = add_backlog(args.title, args.priority, args.detail, who, args.blocked)
        print(f"追加: {p}")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
