# -*- coding: utf-8 -*-
"""窓口が手すきの間、残務を1件ずつ自分で片付ける (2026-08-02 制定・まず ALPHA だけ)。

なぜ要るか (ユーザー「一人でも自発的に動いてくれればフン詰まりが解消しそう」):
    担当 worktree は `dispatch_watch` で自動化済みだが、**窓口の仕事は人が窓を開けるまで
    動かない**。8/2 時点で 🟡レビュー待ち3件・残件4件が滞留していた。
    窓口が律速なのに窓口だけ手動 = そこが詰まる。

やること (1回の起動につき **1件だけ**):
    1. `claim.py next` で最優先の未claim を1件取る (担当指定が別窓口の件は取らない)
    2. その1件を headless claude に渡して片付けさせる
    3. 終わったら claim を解放する (担当が `done` を打っていなければ再試行に戻す)

**1件ずつ**なのは、暴走時の被害と usage 消費を人が読める大きさに保つため。

縛り (機械的):
    - `--disallowedTools` で push / checkout / switch / reset を拒否 (commit は許す。
      未 commit 放置の方が危険 = branch 操作で消える)
    - 出品専任が同じ worktree を編集中 (`hq_busy`) の間は起動しない
    - 二重起動は lock file で防ぐ

使い方:
    python iMakHQ/tools/desk_autorun.py --who ALPHA
    python iMakHQ/tools/desk_autorun.py --who ALPHA --dry-run   # 何を取るかだけ見る
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claim as C  # noqa: E402
import dispatch_worktree as dw  # noqa: E402

# 窓口ごとの作業フォルダ。cwd をここにすると **その窓口の CLAUDE.md が役割として読まれる**。
DESK_DIR = {
    "ALPHA": Path(r"C:\dev\iMak\iMakAlpha"),
    "BRAVO": Path(r"C:\dev\iMak\iMakBravo"),
    "Advisor": Path(r"C:\dev\iMak\iMakAdvisor"),
}
TIMEOUT_SEC = 1800                      # 1件あたり30分 (dispatch と同じ)
DENY_TOOLS = ["Bash(git push:*)", "Bash(git checkout:*)",
              "Bash(git switch:*)", "Bash(git reset:*)"]
LOCK_STALE_SEC = TIMEOUT_SEC + 300


def _lock_path(who: str) -> Path:
    return dw.REVIEW_DIR / f"desk_autorun_{who}.lock"


def acquire(who: str) -> bool:
    """同じ窓口の autorun を二重に走らせない (stale は奪う)."""
    dw.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    p = _lock_path(who)
    if p.exists():
        if time.time() - p.stat().st_mtime < LOCK_STALE_SEC:
            return False
        p.unlink(missing_ok=True)       # 前回が落ちたまま残った lock
    try:
        fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} pid={os.getpid()}\n")
    return True


def release(who: str) -> None:
    _lock_path(who).unlink(missing_ok=True)


def build_prompt(who: str, item: dict) -> str:
    """headless に渡す指示。**縛りを本文に必ず入れる** (prompt だけでは効かないので deny と併用)."""
    body = (item.get("body") or "")
    if not body and item.get("path") and Path(item["path"]).exists():
        body = Path(item["path"]).read_text(encoding="utf-8", errors="replace")
    return f"""あなたは窓口 **{who}** です。署名は `[{who}]`。

残務を **1件だけ** 割り当てられました。これを最後まで片付けてください。

- ID: `{item['id']}`
- 種別: {item['kind']}
- 件名: {item['title']}
- 実体: {item['path']}

---
{body[:6000]}
---

## 必ず守ること

1. **🔀 1丁目1番地**: カタログ絡みなら、手を動かす前に
   「①カタログのデータは正しいか / ②出品くんの引き方は正しいか」を判定して**先に書く**。
   - ①が正しい → ②を直す / ②が正しい → ①を直す / 両方誤 → 両方
   - **「①②とも正しい → 直すものは無い」は禁止**。どちらかが必ず間違っている。根因を追及する
   - ①の根拠は **今その場で計算した値**。`note` に `REVIEW` が付いた行は人が焼いた未検証値なので
     正の根拠にしない
   - **②が原因ならカタログに依頼を出さない**。こちら側で直す
2. **やってはいけないこと** (人の判断が要る):
   - eBay への書込 (出品・リバイス・取下げ)・CSV 入稿・スプシの一括書換・ファイル削除
   - `git push` / `checkout` / `switch` / `reset` (CLI 側でも拒否済)
   - 出品くん listing 本体 (`psa_to_csv` / `tshirt_listing` / `tcg_listing_fields` /
     `post_title_fix`) の編集 = 出品専任の領分
   - 判断に迷ったら**やらずに残す**。理由を書いて `release` すればよい
3. **git**: `git add -A` は禁止。自分が触ったファイルだけ明示 add。add したら即 commit
4. **daily_report**: `C:\\Users\\imax2\\.claude\\projects\\c--dev-iMak\\memory\\daily_report.md`
   の最上段に `## YYYY-MM-DD HH:MM [{who}] 〜` で **Edit で追記** (Write 禁止)。
   書式は 決定 / 変更(file:line) / 検証 の3点セット
5. **終わったら必ず claim を閉じる**:
   - 片付いた: `python iMakHQ/tools/claim.py done {item['id']} --who {who} --note "..."`
   - 手を出せなかった: `python iMakHQ/tools/claim.py release {item['id']} --who {who}`

## 最後に

最終行に `SUMMARY: <done|release> / <一行で何をしたか>` を出力してください。
"""


def run(who: str, dry_run: bool = False) -> dict:
    if who not in DESK_DIR:
        return {"status": "bad-desk", "who": who}
    workdir = DESK_DIR[who]
    if not workdir.is_dir():
        return {"status": "no-dir", "who": who}
    # 出品専任が同じ worktree を編集中は避ける (index 衝突の防止。dispatch と同じ扱い)
    if dw.hq_busy():
        return {"status": "skip-busy", "who": who}
    if not acquire(who):
        return {"status": "skip-locked", "who": who}
    try:
        r = C.next_item(who)
        if not r["ok"]:
            return {"status": "skip-empty", "who": who,
                    "skipped": [(i["id"], w) for i, w in r["skipped"]]}
        item = r["item"]
        if dry_run:
            C.release(item["id"], who)
            return {"status": "dry-run", "who": who, "id": item["id"], "title": item["title"]}

        exe = dw._resolve_claude_exe()
        if not exe or not os.path.exists(exe):
            C.release(item["id"], who)
            return {"status": "no-cli", "who": who}

        dw.REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        log = dw.REVIEW_DIR / f"desk_{datetime.now():%Y-%m-%d_%H%M}_{who}.log"
        t0 = time.time()
        try:
            res = subprocess.run(
                [exe, "-p", build_prompt(who, item), "--dangerously-skip-permissions",
                 "--disallowedTools", *DENY_TOOLS,
                 "--add-dir", str(dw.DATA_ROOT)],
                cwd=str(workdir), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=TIMEOUT_SEC,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            out = (res.stdout or "") + (("\n[stderr]\n" + res.stderr) if res.stderr else "")
            status = "ok" if res.returncode == 0 else f"exit{res.returncode}"
        except subprocess.TimeoutExpired:
            out, status = "(timeout)", "timeout"
        log.write_text(out, encoding="utf-8")

        # ★claim を残さない。担当が done を打っていなければ解放して**次回の再試行に戻す**。
        #   握ったまま落ちると、その件は stale になるまで誰も触れない。
        left = C.read_claim(item["id"]) is not None
        if left:
            C.release(item["id"], who)
        summary = next((ln for ln in reversed(out.splitlines())
                        if ln.startswith("SUMMARY:")), "")
        return {"status": status, "who": who, "id": item["id"], "title": item["title"],
                "sec": int(time.time() - t0), "log": log, "unfinished": left,
                "summary": summary}
    finally:
        release(who)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="窓口が手すきの間に残務を1件片付ける")
    ap.add_argument("--who", default=os.environ.get("IMAK_DESK", "ALPHA"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    r = run(a.who, a.dry_run)
    stamp = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{r['who']}]"
    if r["status"] in ("skip-empty", "skip-busy", "skip-locked"):
        print(f"{stamp} {r['status']} — 起動しない")
        return 0
    if r["status"] == "dry-run":
        print(f"{stamp} dry-run: {r['id']} {r['title']}")
        return 0
    if r["status"] in ("bad-desk", "no-dir", "no-cli"):
        print(f"{stamp} ⚠️ {r['status']}")
        return 1
    mark = " ⚠️未完(解放して再試行に戻した)" if r.get("unfinished") else ""
    print(f"{stamp} {r['status']} / {r['sec']}秒{mark} / {r['id']} / "
          f"{r.get('summary') or '(SUMMARY 行なし)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
