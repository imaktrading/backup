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


def pending():
    """未投入の草案 (_routed に移していないもの)."""
    if not ROUTING.is_dir():
        return []
    return sorted(p for p in ROUTING.glob("*.md") if p.is_file())


def target_of(path: Path) -> str:
    """file 名から宛先を判定。判定不能は "" (窓口が --to で明示する)."""
    m = RE_TO.search(path.name)
    return m.group(1).lower() if m else ""


def inject(path: Path, to: str = "", dry_run: bool = False) -> dict:
    """草案を宛先の requests/ に投入する。戻り: {ok, target, dest, reason}."""
    to = (to or target_of(path)).lower()
    if to not in TARGETS:
        return {"ok": False, "reason": f"宛先を判定できない ({path.name})。--to で指定する"}
    dest_dir = DATA_ROOT / to / "requests"
    if not dest_dir.is_dir():
        return {"ok": False, "reason": f"宛先 dir が無い: {dest_dir}"}
    body = path.read_text(encoding="utf-8", errors="replace")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = (f"> **窓口(Advisor)が宛先を確認して投入しました** ({stamp})。\n"
              f"> 起案は他担当 (草案: `_routing/{path.name}`)。**担当どうしの直接投入は禁止**です"
              f" (相互依頼のループを防ぐため)。\n\n")
    # file 名から `_to_<相手>` を落として、相手の requests/ での自然な名前にする
    stem = re.sub(r"_to_[a-z]+", "", path.stem, flags=re.I).strip("_")
    dest = dest_dir / ((stem + ".md") if stem else path.name)
    if dry_run:
        return {"ok": True, "target": to, "dest": dest, "reason": "(dry-run)"}
    dest.write_text(header + body, encoding="utf-8")
    ROUTED.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(ROUTED / path.name))
    return {"ok": True, "target": to, "dest": dest, "reason": ""}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ROUTING.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    dry = "--dry-run" in args
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
