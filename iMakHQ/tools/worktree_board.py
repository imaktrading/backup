"""全 worktree の状況を1画面に出す — 出品専任/Advisor の一元窓口用ボード.

なぜ必要か (2026-07-27 制定):
    ユーザーは監視くん/重複くん/カタログ等と直接やり取りせず、対話中のセッションを窓口にしたい。
    しかし窓口側が各 worktree の状態を知るのに毎回 requests dir を手で漁っていた。

★重要な制約 (グローバル CLAUDE.md「Worktree 分離ルール」):
    **他 worktree のフォルダ (C:/dev/iMak_inventory 等) は読取も禁止**。
    このスクリプトは **共有データ領域 (C:/dev/iMak_data/) だけ**を見る。
    調整に必要な情報 (依頼・回答・その連鎖) は全部そこに出るので、実務上これで足りる。

出力: worktree ごとに
    - 未処理 (自分が返すべき) requests
    - 相手ボール (こちらが出して回答待ち) の依頼
    - 直近の動き (最終更新ファイルと経過時間)
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

DATA_ROOT = Path(r"C:\dev\iMak_data")
# 表示名 (ユーザーの呼称に合わせる: 監視くん/抽出くん)
WORKTREES = [
    ("hq", "HQ (自分宛の受領箱)"),
    ("catalog", "カタログ"),
    ("dedupe", "重複くん"),
    ("inventory", "監視くん"),
    ("harvest", "抽出くん"),
    ("revise", "リバイス"),
]
CLOSED_SUFFIXES = (
    "_processed", "_response", "_done", "_expired", "_resolved", "_superseded",
    "_ack", "_reply", "_decision", "_verdict", "_closure", "_withdrawn",
    "_cancelled", "_acknowledged", "_confirm", "_applied", "_close",
)
RECENT_DAYS = 21
MAX_SHOW = 8
# 窓口レビューがこの時間を超えたら「放置」として色を変える。
# 8/04 の重複くん回答を3日寝かせ、その間 8/05・8/06 も重複が入稿CSVに載った。
STALE_DRAFT_H = 24


def _is_outbound(stem: str, worktree: str) -> bool:
    """こちら (HQ/Advisor) が出した側か = 相手ボール."""
    low = stem.lower()
    return worktree != "hq" and (low.startswith("hq_") or "_hq_" in low)


def _is_closed(path: Path, stems: set[str]) -> bool:
    if path.stem.lower().endswith(CLOSED_SUFFIXES):
        return True
    prefix = path.stem + "_"
    return any(s != path.stem and s.startswith(prefix) for s in stems)


# headless 担当が書く中間成果物。窓口がレビューして `_response.md` に昇格させる。
# **依頼として再 dispatch してはいけない**ので pending とは別枠に分ける。
DRAFT_SUFFIXES = ("_draft", "_question")

# ★2026-08-02: 回答が **起票した窓口に戻らない** 問題の対策。
#   実害: BRAVO が起票した pokemon の件を、Catalog が draft で返した後、
#   Advisor が裁定して GO まで出した。BRAVO は自分の依頼が決着したことを知らなかった。
#   claim には `- 担当:` を読む仕組みが既にあるのに、**依頼書の起票者を誰も owner に
#   していなかった**ため、draft は「誰のものでもない」状態で置かれていた。
#   → draft/question の持ち主は **元依頼を書いた窓口**とする。
RE_REQUESTER = (
    re.compile(r"^\s*[-*].*?窓口\s*[:：]\s*\*{0,2}([^\s*/(（]+)", re.M),   # `- 依頼日: … / 窓口: **BRAVO**`
    re.compile(r"^\s*[-*].*?(?:起票|依頼者|作成)\s*[:：].*?\[([^\]]+)\]", re.M),  # `- 起票: … [Advisor]`
    re.compile(r"^\s*[-*].*?(?:起票者|依頼者)\s*[:：]\s*\*{0,2}([^\s*/(（]+)", re.M),
)
DESK_NAMES = {
    "出品専任": "出品専任", "出品くん": "出品専任",
    "advisor": "Advisor", "adv": "Advisor",
    "alpha": "ALPHA", "bravo": "BRAVO",
}


def _base_request(path: Path) -> Path:
    """`X_draft.md` / `X_question.md` → 元依頼 `X.md`。無ければ自分自身."""
    stem = path.stem
    for suf in DRAFT_SUFFIXES:
        if stem.lower().endswith(suf):
            base = path.with_name(stem[: -len(suf)] + path.suffix)
            return base if base.is_file() else path
    return path


def requester_of(path: Path) -> str:
    """依頼書を書いた窓口名。読めなければ "" (= 誰でも取れる)。

    draft/question は **元依頼**を見る (draft を書いたのは headless 担当なので、
    そこに書いてある名前は起票者ではない)。
    """
    src = _base_request(path)
    try:
        head = src.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return ""
    for rx in RE_REQUESTER:
        m = rx.search(head)
        if not m:
            continue
        raw = m.group(1).strip().strip("*`[]")
        name = DESK_NAMES.get(raw, DESK_NAMES.get(raw.lower(), ""))
        if name:
            return name
    return ""


def current_desk() -> str:
    """今この board を見ている窓口 (cwd 由来)。判定できなければ ""."""
    try:
        import claim
        return claim.detect_who()
    except Exception:                                          # noqa: BLE001
        return ""


def _draft_is_closed(path: Path, stems: set[str]) -> bool:
    """draft / question の決着判定.

    `_is_closed` は `{stem}_*` (= draft 自身に closure が付いた形) しか見ないため、
    `X_draft.md` に対して **兄弟の `X_response.md`** が書かれた通常の decision フローを
    決着とみなせず、レビュー待ちに残り続けていた (2026-07-30: 実測12件を28件と表示)。
    draft 側は **base stem (= draft/question 接尾を外した幹) に closure が付いたか**で見る。
    """
    low = path.stem.lower()
    base = None
    for suf in DRAFT_SUFFIXES:
        if low.endswith(suf):
            base = path.stem[: -len(suf)].rstrip("_")
            break
    if base is None:
        return False
    bl = base.lower()
    for s in stems:
        sl = s.lower()
        if sl == low or not sl.startswith(bl):
            continue
        if sl.endswith(CLOSED_SUFFIXES):
            return True
    return False


def pending_for(worktree: str, recent_days: int = RECENT_DAYS):
    """(自分が返すべき, 相手ボール, 窓口レビュー待ち) の Path list を返す."""
    d = DATA_ROOT / worktree / "requests"
    if not d.is_dir():
        return [], [], []
    cutoff = time.time() - recent_days * 86400
    files = [p for p in d.glob("*.md") if p.stat().st_mtime >= cutoff]
    # closure 判定用の stem 集合は **期間で絞らない**。回答が cutoff 外にあると
    # 決着済の draft が「レビュー待ち」に復活してしまう。
    stems = {p.stem for p in d.glob("*.md")}
    mine, theirs, drafts = [], [], []
    for p in sorted(files, key=lambda x: -x.stat().st_mtime):
        if p.stem.lower().endswith(DRAFT_SUFFIXES):
            if not (_is_closed(p, stems) or _draft_is_closed(p, stems)):
                drafts.append(p)
            continue
        if _is_closed(p, stems):
            continue
        (theirs if _is_outbound(p.stem, worktree) else mine).append(p)
    return mine, theirs, drafts


# ★2026-07-30: 実装が「人がそのセッションを開くまで」動かない問題の解消。
# 窓口が draft を検算して `_response.md` に **実装 GO** と書いても、response は「決着済」
# 扱いなので二度と dispatch されず、**誰も実装しないまま滞留**していた。
# (ユーザー指摘:「閉じていいと言ったから立ち上げてない」= セッションを開く前提が崩れている)
# → GO と書かれた response を **実装キュー**として拾い、担当に実装させる。
# ★マーカーは **明示トークン1つだけ**にする (2026-07-30)。
#   最初「実装 GO」等の自然文で拾ったら、**7/22・7/26 の完了済み回答まで実装キューに入った**。
#   誤って再実装させると破壊になりうるので、窓口が意図的に書いた時だけ動くようにする。
#   窓口はこのトークンを、実装させたい `_response.md` の本文に1行入れる。
IMPLEMENT_MARKERS = ("[IMPLEMENT-GO]",)
# 実装完了の印。担当がこれを書いたらキューから外れる (証拠付きの完了報告を兼ねる)。
IMPLEMENT_DONE_SUFFIXES = ("_done", "_applied")


def has_implement_go(body: str) -> bool:
    """本文に **発火用の** 実装 GO 行があるか。

    ★2026-08-08: 部分一致 (`marker in body`) は **マーカーの話をしただけで発火する**。
      「このファイルに `[IMPLEMENT-GO]` は入れていない = まだ着手しないこと」と書いた
      回答が実装キューに入り、担当 headless が 3 回空焚きした (監視くんから3度督促)。
      CLAUDE.md の規約どおり **「本文に1行入れる」= その行がマーカーだけ** を条件にする。

    許容する飾り: 前後の空白 / 引用 `>` / 箇条書き `- * +` / 強調 `* _` `。
    許容しない: 表のセル内・文中の言及 (= 説明として書いた `[IMPLEMENT-GO]`)。

    実データで検証 (2026-08-08): 正規の GO 26件はすべて「行全体がマーカー」で、
    誤爆3件はすべて文中の言及だった。
    """
    for raw in body.splitlines():
        line = raw.strip()
        while line[:1] in (">", "-", "*", "+"):
            line = line[1:].strip()
        line = line.strip("*_` \t")
        if line in IMPLEMENT_MARKERS:
            return True
    return False


def implement_for(worktree: str, recent_days: int = RECENT_DAYS):
    """実装させるべき `_response.md` を返す (窓口が GO を書いたもの / 未完了のみ)。

    条件 (すべて満たすもののみ):
      - `*_response.md` である (= 窓口が検算して昇格させた正式回答)
      - 本文に実装 GO の印が **1行として** ある (`has_implement_go`)
      - `<stem>_done.md` / `_applied.md` がまだ無い
    """
    d = DATA_ROOT / worktree / "requests"
    if not d.is_dir():
        return []
    cutoff = time.time() - recent_days * 86400
    files = [p for p in d.glob("*.md") if p.stat().st_mtime >= cutoff]
    stems = {p.stem for p in files}
    out = []
    for p in sorted(files, key=lambda x: -x.stat().st_mtime):
        if not p.stem.lower().endswith("_response"):
            continue
        if any(f"{p.stem}{sfx}" in stems for sfx in IMPLEMENT_DONE_SUFFIXES):
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if has_implement_go(body):
            out.append(p)
    return out


def _age(ts: float) -> str:
    h = (time.time() - ts) / 3600
    if h < 1:
        return f"{int(h * 60)}分前"
    if h < 48:
        return f"{int(h)}時間前"
    return f"{int(h / 24)}日前"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cutoff = time.time() - RECENT_DAYS * 86400
    print(f"# worktree ボード (直近{RECENT_DAYS}日 / 共有領域のみ)\n")

    # ★2026-08-01: 窓口が4つになり、**同じ件に複数窓口が着手する**余地ができた。
    #   誰が何を持っているかを board の先頭に出す (詳細と着手は claim.py)。
    #   循環 import になるのでここで遅延 import する (claim.py は board を参照する)。
    try:
        import claim as _claim
        _held = [(it, c) for it in _claim.all_items()
                 if (c := _claim.read_claim(it["id"]))]
    except Exception:                                          # noqa: BLE001
        _held = []
    if _held:
        print(f"## 🔒 着手中 {len(_held)}件 — **他の窓口は触らない**")
        for it, c in _held:
            mark = " ⚠️放置(奪取可)" if c.get("stale") else ""
            print(f"- **[{c.get('who', '?')}]**{mark} {it['title']} `{it['id']}`")
        print()

    grand_mine = grand_theirs = grand_stale = 0
    desk = current_desk()          # 起票が自分の件に ★ を付けるため

    for wt, label in WORKTREES:
        d = DATA_ROOT / wt / "requests"
        if not d.is_dir():
            continue
        files = [p for p in d.glob("*.md") if p.stat().st_mtime >= cutoff]
        mine, theirs, drafts = pending_for(wt, RECENT_DAYS)
        latest = max((p.stat().st_mtime for p in files), default=0)

        if not (mine or theirs or drafts):
            state = f"動きなし (最終 {_age(latest)})" if latest else "動きなし"
            print(f"## {label} — {state}")
            print()
            continue

        grand_mine += len(mine)
        grand_theirs += len(theirs)
        print(f"## {label} — 自分が返す {len(mine)}件 / 相手待ち {len(theirs)}件"
              f" / レビュー待ち {len(drafts)}件 (最終 {_age(latest)})")
        for p in drafts[:MAX_SHOW]:
            # ★起票した窓口を必ず出す。書いていない依頼は「起票者不明」と出して、
            #   次に起票する人が名前を書くよう促す (誰のものでもない状態を作らない)。
            req = requester_of(p)
            tag = f" — 起票: **{req}**" if req else " — 起票者不明"
            if req and req == desk:
                tag += " ★**あなたのボール**"
            # ★2026-08-07: 滞留した draft を目立たせる。窓口が寝かせると **系全体が止まる**
            #   (8/04 の重複くん回答を3日寝かせた間に、8/05・8/06 も重複が入稿CSVに載った)。
            #   「毎回見る」は口約束なので、時間で自動的に色を変える。
            _h = (time.time() - p.stat().st_mtime) / 3600
            _mark = "🟡" if _h < STALE_DRAFT_H else ("🟠" if _h < STALE_DRAFT_H * 3 else "🔴")
            _late = "" if _h < STALE_DRAFT_H else f" ⏰**{int(_h)}時間 放置**"
            print(f"- {_mark} **レビュー待ち(headless下書き)** {p.name} "
                  f"({_age(p.stat().st_mtime)}){tag}{_late}")
            if _h >= STALE_DRAFT_H:
                grand_stale += 1
        for p in mine[:MAX_SHOW]:
            print(f"- 🔴 **要返球** {p.name} ({_age(p.stat().st_mtime)})")
        if len(mine) > MAX_SHOW:
            print(f"  …他{len(mine) - MAX_SHOW}件")
        for p in theirs[:MAX_SHOW]:
            print(f"- ⏳ 相手ボール {p.name} ({_age(p.stat().st_mtime)})")
        if len(theirs) > MAX_SHOW:
            print(f"  …他{len(theirs) - MAX_SHOW}件")
        print()

    # ★担当が書いた「他担当宛の依頼草案」(2026-07-30)。投入は窓口が宛先確認してから。
    #   担当は他 worktree を読めず、相互投入を許すとループを止められないため。
    _routing = sorted((DATA_ROOT / "_routing").glob("*.md")) if (DATA_ROOT / "_routing").is_dir() else []
    if _routing:
        print(f"## 🔀 ルーティング待ち {len(_routing)}件 — **窓口が宛先を確認して投入する**")
        for p in _routing:
            print(f"- {p.name} ({_age(p.stat().st_mtime)})")
        print("→ `python route_inbox.py --inject <file名>`\n")

    # ★事務員 (clerk) の死活監視 (2026-07-30)。
    #   事務員は「異常を見つける係」なので、**事務員自身が死ぬと誰も気づけない**。
    #   増員しても解決しない (同じ仕事の人数が増えるだけ) ので、外側から生存を見る。
    #   7/28-7/30 の夜間 cron が exit 0 のまま空振りしていた件と同型の失敗を防ぐ。
    reports = sorted((DATA_ROOT / "clerk" / "reports").glob("*_patrol.md"),
                     key=lambda p: p.stat().st_mtime) if (DATA_ROOT / "clerk" / "reports").is_dir() else []
    if not reports:
        print("⚠️ 事務巡回のレポートが1件も無い — 事務員が動いていない疑い\n")
    else:
        last = reports[-1]
        hours = (time.time() - last.stat().st_mtime) / 3600
        mark = "⚠️ " if hours > 24 else ""
        print(f"{mark}事務巡回: 最終 {_age(last.stat().st_mtime)} ({last.name})"
              + (" — **24h 以上動いていない**" if hours > 24 else "") + "\n")

    # ★2026-08-02: dispatch watcher の死活。**死んでも誰も気づかない**のが本当の問題だった
    #   (8/1 に 9時間 / 8/2 に2回、人が偶然気づいて手で再起動している)。
    #   事務員の死活監視と同じ理由で、外側から生存を見る。
    try:
        import dispatch_watch as _dwatch
        _watch_age = _dwatch.heartbeat_age()
    except Exception:                                          # noqa: BLE001
        _watch_age = None
    if _watch_age is None:
        print("⚠️ dispatch watcher の heartbeat が無い — **依頼が誰にも配られていない疑い**")
        print("→ `schtasks /end /tn iMakHQ_DispatchWatch; schtasks /run /tn iMakHQ_DispatchWatch`\n")
    elif _watch_age > 300:
        print(f"⚠️ dispatch watcher が {int(_watch_age / 60)}分 止まっている — "
              "**依頼が誰にも配られていない**")
        print("→ `schtasks /end /tn iMakHQ_DispatchWatch; schtasks /run /tn iMakHQ_DispatchWatch`\n")
    else:
        print(f"dispatch watcher: 稼働中 (heartbeat {int(_watch_age)}秒前)\n")

    print(f"---\n**合計: 要返球 {grand_mine}件 / 相手ボール {grand_theirs}件**")
    if grand_stale:
        print(f"🔴 **窓口が {grand_stale}件のレビューを {STALE_DRAFT_H}時間以上 止めている** "
              "— 止めると相手の worktree も止まる。先に返球すること")
    if grand_mine:
        print("→ 要返球を先に片付ける。**自分の回答待ちで他 worktree を止めない**。")
    if grand_theirs:
        print("→ 相手ボールが長く動いていなければ督促するか、"
              "headless で当該 worktree を起動して処理させる (Phase2)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
