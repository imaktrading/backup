# -*- coding: utf-8 -*-
"""現在地 — 「今どうなっているか」の**唯一の答え** (read-only)。

なぜ要るか (2026-08-01):
    ユーザーが ALPHA と BRAVO に同じ「現在地は?」を聞いたら **違う答えが返ってきた**。
    状態は動いていなかった (実測: 19:40〜19:54 で共有ファイルの変化ゼロ) ので、
    原因はデータではなく **各セッションが「現在地」を自分で定義して作文していたこと**。

    → 現在地は **このコマンドの出力** と定める。セッションは作文しない。
      「一回決めたら狂いようがない。それが program」(ユーザー 2026-08-01)。

使い方:
    python iMakHQ/tools/status_now.py

    現在地を聞かれたら **これを実行して、出力をそのまま示す**。
    補足したいことがあれば出力の**後ろに**足す。出力自体を書き換えない。
"""
import datetime
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # C:/dev/iMak
DAILY = r"C:\Users\imax2\.claude\projects\c--dev-iMak\memory\daily_report.md"


def _run(args, cwd=ROOT):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                    # noqa: BLE001
        return f"(取得失敗: {type(e).__name__}: {e})"


def _board():
    return _run([sys.executable, os.path.join(HERE, "worktree_board.py")])


def _backlog():
    """残務ボード (誰が何を持っているか / 次に取れるのは何か)。read-only。

    2026-08-01: 窓口が4つになり、同じ残務に複数窓口が着手しうる状態になった。
    着手は `claim.py next` (状態を変えるのでこの道具ではやらない)。
    """
    return _run([sys.executable, os.path.join(HERE, "claim.py"), "list"])


def _hoju():
    """補URL: **押したら何件できるか**。catalog DB / スプシを読むので数十秒かかる場合あり。

    ★2026-08-09: ここも「候補あり N件」= 足切りを通していない母数を出していた。
      パネルのラベルと同じ count_workload() を使う (数字が2箇所で食い違わない)。
    """
    code = (
        "import sys,json;sys.path.insert(0,r'%s');"
        "import psa_hoju_fill as H;"
        "w=H.count_workload();s=w['search'];c=w['confirm'];"
        "print(f\"live PSA(TCG) {w['live_psa']}件 / 補0本 {w['targets']}件 \""
        "f\"→ 目視できる {c['ready']}件 (絵柄が未判定 {c['unjudged']}) / \""
        "f\"検索できる {s['can']}件 (探索不能 {s['no_cardno']} = 番号なし)\")" % HERE
    )
    return _run([sys.executable, "-c", code]).strip()


VIEWER_DISAGREEMENT = r"C:\dev\iMak_data\catalog\viewer_disagreement.log"


def _viewer_disagreement(limit=5):
    """catalog に実在するのに viewer が確定できなかった件 (= ②の宿題)。

    ★2026-08-09: このログは **書く側が2箇所あるのに読む側がゼロ**だった。
      残務にも現在地にも出ないので、出品がここで削られていることに誰も気づけない
      (8/7 に実在 pre-check が入って以降、catalog 依頼も出なくなっていた)。
      現在地に出す = 毎セッション必ず目に入る形にする。
    """
    try:
        with open(VIEWER_DISAGREEMENT, encoding="utf-8", errors="replace") as f:
            rows = [ln.rstrip("\n") for ln in f if ln.strip()]
    except OSError:
        return []
    out = []
    for ln in rows[-limit:]:
        c = ln.split("\t")
        if len(c) >= 4:
            out.append(f"{c[0]}  {c[1]}  {c[2]}:{c[3]}")
        else:
            out.append(ln)
    return [f"計 {len(rows)}件 (直近 {len(out)}件)"] + out


CERT_SKIP_LEDGER = r"C:\dev\iMak_data\hq\extract_cert_skips.jsonl"


def _zero_qty_ghost_certs(limit=5):
    """出品の器はあるが在庫0 (取下げ済) の cert = ②出品くんの引き方の宿題 (2026-08-31)。

    ★catalog 依頼 cert152976751: `extract_cert_skips.jsonl` には毎回記録されていたが、
      読む側がゼロで、目視で8回 OK と答えても何も起きないまま気づかれなかった
      (`_viewer_disagreement` と同型の穴。同じ理由で現在地に出す)。
    """
    import json as _json
    try:
        with open(CERT_SKIP_LEDGER, encoding="utf-8", errors="replace") as f:
            recs = [_json.loads(ln) for ln in f if ln.strip()]
    except OSError:
        return []
    latest = {}          # cert → 最後に記録された時刻 (最新状態だけ見る)
    for r in recs:
        if r.get("reason") != "same_cert_zero_qty_ghost":
            continue
        for c in r.get("certs") or []:
            latest[c] = r.get("ts", "")
    if not latest:
        return []
    ordered = sorted(latest, key=lambda c: latest[c], reverse=True)
    return [f"計 {len(latest)}件 (直近 {min(limit, len(ordered))}件)"] + [
        f"cert{c}  最終検知 {latest[c]}" for c in ordered[:limit]]


def _commits():
    out = _run(["git", "log", "--since=midnight",
                "--format=%h %ad %s", "--date=format:%H:%M"])
    lines = [ln for ln in out.split("\n") if ln.strip()]
    return lines


def _next_actions():
    """daily_report 最上段の「次に何をやるか」表をそのまま出す (作文しない)。"""
    try:
        with open(DAILY, encoding="utf-8") as f:
            t = f.read()
    except OSError as e:
        return [f"(daily_report 読めず: {e})"]
    m = re.search(r"##\s*4\.\s*いま誰待ちか[^\n]*\n(.*?)(?=\n## |\n---)", t, re.S)
    if not m:
        return ["(daily_report に『いま誰待ちか』節が見つからない)"]
    return [ln for ln in m.group(1).split("\n") if ln.strip()]


STALL_DAYS = 7


def stalled_lines(rows, today, days=STALL_DAYS):
    """**詰まった時だけ** 出す1行 (純関数)。動いていれば空 = 常時は何も出さない.

    ★2026-08-18 ユーザー判断: 「PDCA が回っているなら見えなくていい。
      ただし止まった時に気づける必要はある」。一覧は増やさず、閾値を超えた時だけ出す。
      今日見つけた3件 (出品結果メール / 補URL追記 / レビュー待ち) は全部
      「壊れていた」のではなく **止まっているのが見えなかった** だけだった。

    rows: [{"updated_ts": "YYYY-MM-DD", ...}] の未対応リスト。
    日付が読めない行は数えない (推測で警告を出さない)。
    """
    import datetime as _dt
    try:
        base = _dt.date.fromisoformat(str(today)[:10])
    except Exception:                                          # noqa: BLE001
        return []
    old = []
    for r in rows or []:
        ts = str((r or {}).get("updated_ts") or "")[:10]
        try:
            d = _dt.date.fromisoformat(ts)
        except Exception:                                      # noqa: BLE001
            continue
        if (base - d).days >= days:
            old.append((d, r))
    if not old:
        return []
    old.sort()
    d0, r0 = old[0]
    return [f"⚠️ program修正の未対応が {len(old)}件、"
            f"最長 {(base - d0).days}日 動いていません "
            f"(`python iMakHQ/tools/program_fix_backlog.py` で中身)"]


def _stalled():
    """pdca の program修正 pending から、止まっている分だけ拾う (I/O)。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import pdca_store as _p
        con = _p.connect()
        rows = [dict(r) for r in con.execute(
            "SELECT item_id, updated_ts FROM improvement_queue "
            "WHERE status='pending' AND finding_type='program_fix'")]
        con.close()
        return stalled_lines(rows, datetime.date.today().isoformat())
    except Exception:                                          # noqa: BLE001
        return []


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                        # noqa: BLE001
        pass
    now = datetime.datetime.now()
    print(f"# 現在地 {now:%Y-%m-%d %H:%M}  (status_now.py の出力 = これが唯一の答え)\n")

    print("## 1. 各担当の未処理\n")
    print(_board().rstrip())

    print("\n## 2. 残務ボード (着手は claim.py next)\n")
    print(_backlog().rstrip())

    print("\n## 3. 出品の数字\n")
    print("  " + _hoju())

    vd = _viewer_disagreement()
    if vd:
        print("\n## 3b. ②の宿題 — catalog に在るのに viewer が確定できなかった件\n")
        for ln in vd:
            print("  " + ln)
        print("  → catalog の欠落ではない。同定経路(viewer/adapter)を直す side")

    gz = _zero_qty_ghost_certs()
    if gz:
        print("\n## 3c. ②の宿題 — 出品の器はあるが在庫0 (RESTOCK か End+出し直しの判断待ち)\n")
        for ln in gz:
            print("  " + ln)
        print("  → 二重出品ガードで毎回黙って落ちている。RESTOCK で数量を戻すか、"
              "器を終了して出し直すか決めること")

    for ln in _stalled():          # 動いている限り何も出ない (常時表示しない)
        print("\n" + ln)

    print("\n## 4. 今日の commit\n")
    cs = _commits()
    if cs:
        for ln in cs:
            print("  " + ln)
        print(f"  ---- 計 {len(cs)}本")
    else:
        print("  (今日はまだ commit なし)")

    print("\n## 5. 次にやること (daily_report 最上段より・原文)\n")
    for ln in _next_actions():
        print("  " + ln)

    print("\n---")
    print("この出力が現在地です。補足は後ろに足してよいが、出力自体は書き換えないこと。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
