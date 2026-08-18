"""担当が書いた「他担当宛の依頼草案」を、窓口が宛先確認して投入する (2026-07-30).

なぜ必要か:
    担当は worktree 分離により **他担当の領域を読めない**ので、相手の状況を知らないまま
    依頼を出すことになる。さらに相互に投入できると A→B→A の往復や無限ループが起きて
    誰も止められない。よって **投入は必ず窓口を通す**。
    一方、窓口が毎回ゼロから依頼書を書くのは無駄なので、**草案までは担当に書かせる**。

置き場: C:/dev/iMak_data/_routing/
    担当は `<YYYY-MM-DD>_<from>_to_<target>_<topic>.md` を置く (ここは誰も dispatch しない)。
    窓口が中身と宛先を確認して `--inject` で相手の requests/ に投入する。
    投入済みは `_routing/_routed/` に移す (履歴)。

使い方:
    python route_inbox.py                 # 未投入の草案を一覧
    python route_inbox.py --inject <file> # 宛先を確認して投入 (宛先は file 名から判定)
    python route_inbox.py --inject <file> --to catalog   # 宛先を明示指定
"""
from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

DATA_ROOT = Path(r"C:\dev\iMak_data")
ROUTING = DATA_ROOT / "_routing"
ROUTED = ROUTING / "_routed"
TARGETS = ("hq", "catalog", "dedupe", "inventory", "harvest", "revise")
RE_TO = re.compile(r"_to_(" + "|".join(TARGETS) + r")(?:_|\.)", re.I)
# `<日付>_<担当>_internal_<topic>` = 自分宛 (担当が自分の worktree に積む改善案)
RE_INTERNAL = re.compile(r"_?(" + "|".join(TARGETS) + r")_internal_", re.I)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worktree_board as wb  # noqa: E402


def delivery_safe_stem(stem: str) -> str:
    """**配達されない名前を作らせない** (2026-08-18).

    `worktree_board` は名前の末尾で「決着済」(`_response` `_done` `_verdict` …) と
    「窓口レビュー待ち」(`_draft` `_question`) を判定する。草案の**話題**がその語で
    終わっていると、投入した瞬間に **誰にも配られない依頼**になる。
    実害: `2026-08-17_hq_machine_readable_verdict.md` (回答書に機械可読な結論行を
    足してほしい、という依頼) は投入直後から決着済扱いで、catalog に一度も配られなかった。
    → 末尾が判定語になる時だけ `_req` を足す。中身も宛先も変えない。
    """
    low = stem.lower()
    if low.endswith(wb.CLOSED_SUFFIXES) or low.endswith(wb.DRAFT_SUFFIXES):
        return stem + "_req"
    return stem


def pending():
    """未投入の草案 (_routed に移していないもの)."""
    if not ROUTING.is_dir():
        return []
    return sorted(p for p in ROUTING.glob("*.md") if p.is_file())


def target_of(path: Path) -> str:
    """file 名から宛先を判定。判定不能は "" (窓口が --to で明示する)."""
    m = RE_TO.search(path.name)
    if m:
        return m.group(1).lower()
    m = RE_INTERNAL.search(path.name)
    return m.group(1).lower() if m else ""


def inject(path: Path, to: str = "", dry_run: bool = False, auto: bool = False) -> dict:
    """草案を宛先の requests/ に投入する。戻り: {ok, target, dest, reason}."""
    to = (to or target_of(path)).lower()
    if to not in TARGETS:
        return {"ok": False, "reason": f"宛先を判定できない ({path.name})。--to で指定する"}
    dest_dir = DATA_ROOT / to / "requests"
    if not dest_dir.is_dir():
        return {"ok": False, "reason": f"宛先 dir が無い: {dest_dir}"}
    body = path.read_text(encoding="utf-8", errors="replace")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if auto:
        # ★2026-08-09: 窓口レビューを廃止し **自動投入**にした。
        #   `_routing/` は仕分けツール (draft_triage) の対象外で、7日間 8件 溜まっても
        #   誰にも警告が出ていなかった。届かない方が害が大きい (相手の作業が止まり、
        #   止まっていることに誰も気づけない) というユーザー判断。
        header = (f"> **自動投入** ({stamp}) — 起案は他担当 (草案: `_routing/{path.name}`)。\n"
                  f"> 窓口レビューは通していません。宛先違いだと思ったら "
                  f"`_question.md` で窓口に差し戻してください。\n\n")
    else:
        header = (f"> **窓口(Advisor)が宛先を確認して投入しました** ({stamp})。\n"
                  f"> 起案は他担当 (草案: `_routing/{path.name}`)。**担当どうしの直接投入は禁止**です"
                  f" (相互依頼のループを防ぐため)。\n\n")
    # file 名から `_to_<相手>` を落として、相手の requests/ での自然な名前にする
    stem = re.sub(r"_to_[a-z]+", "", path.stem, flags=re.I).strip("_")
    stem = delivery_safe_stem(stem) if stem else ""
    dest = dest_dir / ((stem + ".md") if stem else path.name)
    if dry_run:
        return {"ok": True, "target": to, "dest": dest, "reason": "(dry-run)"}
    dest.write_text(header + body, encoding="utf-8")
    ROUTED.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(ROUTED / path.name))
    return {"ok": True, "target": to, "dest": dest, "reason": ""}


def auto_route(dry_run: bool = False) -> dict:
    """未投入の草案を **全部** 宛先へ流す (窓口レビューなし)。

    2026-08-09 ユーザー判断: 窓口を必ず通す設計は「届かない」失敗を作り、しかも
    `_routing/` は仕分け対象外なので **誰も気づけない** (実際に 7日間 8件 滞留)。
    仕分けも閾値も置かず、宛先が file 名から判る草案はそのまま投入する。
    宛先が判らないものだけ残す (捨てない = silent drop しない)。
    Returns: {"injected": [(name, target)], "unknown": [name]}
    """
    injected, unknown = [], []
    for p in pending():
        if not target_of(p):
            unknown.append(p.name)
            continue
        r = inject(p, dry_run=dry_run, auto=True)
        (injected if r["ok"] else unknown).append(
            (p.name, r.get("target")) if r["ok"] else p.name)
    return {"injected": injected, "unknown": unknown}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ROUTING.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    dry = "--dry-run" in args
    if "--auto" in args:
        r = auto_route(dry_run=dry)
        for name, to in r["injected"]:
            print(f"✅ 自動投入: {to} ← {name}")
        for name in r["unknown"]:
            print(f"⚠️ 宛先不明で保留: {name} (--inject <file> --to <worktree> で投入)")
        if not r["injected"] and not r["unknown"]:
            print("ルーティング待ちなし")
        return 0
    if "--inject" in args:
        i = args.index("--inject")
        src = Path(args[i + 1]) if len(args) > i + 1 else None
        if not src or not src.exists():
            src = ROUTING / (args[i + 1] if len(args) > i + 1 else "")
        to = args[args.index("--to") + 1] if "--to" in args else ""
        if not src or not src.exists():
            print("⚠️ 草案が見つからない")
            return 2
        r = inject(src, to, dry_run=dry)
        print(("✅ 投入: " if r["ok"] else "⚠️ 失敗: ")
              + (f"{r.get('target')} ← {src.name} → {r.get('dest')}" if r["ok"] else r["reason"]))
        return 0 if r["ok"] else 1

    rows = pending()
    if not rows:
        print("ルーティング待ちの草案なし (C:/dev/iMak_data/_routing/)")
        return 0
    print(f"# ルーティング待ち {len(rows)}件 — **窓口が宛先を確認して投入する**\n")
    for p in rows:
        to = target_of(p) or "?? (--to で指定)"
        head = p.read_text(encoding="utf-8", errors="replace").splitlines()
        title = next((ln.lstrip("# ").strip() for ln in head if ln.strip()), "(空)")
        print(f"- [{to}] {p.name}\n    {title[:80]}")
    print("\n投入: python route_inbox.py --inject <file名> [--to <worktree>]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
